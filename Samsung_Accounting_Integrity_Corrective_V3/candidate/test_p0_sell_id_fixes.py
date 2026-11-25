# tests/test_p0_sell_id_fixes.py
# ОБЯЗАТЕЛЬНЫЕ ТЕСТЫ ЭТАПА 5Б — P0: защита от повторной SELL и
# разделение клиентского UUID / биржевого order_id.
#
# Основание: постановка ЭТАП 5Б (базовый commit e762e6df) + аудит Этапа 5А.
#
# Главный инвариант: если судьба предыдущей SELL неизвестна, робот не
# отправляет новую SELL или BUY по этому FIGI.
#
# Группы (нумерация — по §8 постановки):
#   SELL safety     — сценарии 1..10;
#   Идентификаторы  — сценарии 11..18;
#   Миграция        — сценарии 19..23.
#
# Требование §8 к фейкам: клиентский UUID и биржевой ID РАЗНЫЕ; заявка
# ищется строго по паре (идентификатор, тип); неправильный тип поиска
# даёт отрицательный результат (None), а не «ту же заявку».

import asyncio
import csv
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import logger as research_logger
from execution import ExecutionMonitor, PositionState, TrackedPosition
from order_ledger import OrderLedger
from tinkoff_client import OrderResult

UTC = timezone.utc

_IMPORT_ERROR = None
try:
    import main
except Exception as exc:  # noqa: BLE001
    _IMPORT_ERROR = exc

pytestmark = pytest.mark.skipif(
    _IMPORT_ERROR is not None,
    reason=f"main.py недоступен: {_IMPORT_ERROR}",
)

_ORIG_IS_TRADING_ENABLED = main.is_trading_enabled
_ORIG_SAVE_STATE = main._save_state


# ---------------------------------------------------------------- fakes

class PosData:
    """Минимальный аналог PositionData брокера."""
    def __init__(self, lots, direction):
        self.lots = lots
        self.direction = direction


class _MV:
    def __init__(self, units, nano=0):
        self.units = units
        self.nano = nano


class FakeOrderState:
    """Отчёт заявки брокера: FILL=1, REJECTED=2, CANCELLED=3, NEW=4, PARTIALLYFILL=5."""
    def __init__(self, status_code=1, lots_executed=0, total_price_units=0,
                 exchange_order_id=None, order_request_id=None):
        self.execution_report_status = status_code
        self.lots_executed = lots_executed
        self.executed_order_price = _MV(total_price_units)
        self.executed_commission = None
        self.order_id = exchange_order_id          # БИРЖЕВОЙ ID (OrderState)
        self.order_request_id = order_request_id   # КЛИЕНТСКИЙ UUID (OrderState)


def _id_type_name(order_id_type):
    """'EXCHANGE'/'REQUEST'/None из члена enum/строки (см. контракты GetOrderState)."""
    if order_id_type is None:
        return None
    name = getattr(order_id_type, "name", None)
    if name:
        return "EXCHANGE" if str(name).endswith("EXCHANGE") else (
            "REQUEST" if str(name).endswith("REQUEST") else str(name))
    return str(order_id_type)


class IdAwareBroker:
    """Фейковый брокер, различающий клиентский UUID и биржевой ID.

    Заявки хранятся строго по паре (идентификатор, тип). Требование §8:
      - UUID и биржевой ID РАЗНЫЕ (exchange_id = "EX-" + request_id);
      - неправильный тип поиска даёт отрицательный результат (None);
      - потерянный ответ (lost_response=True): заявка могла быть принята —
        она видна брокеру (GetSandboxOrders/state), но пост-ответ не вернулся.
    """
    def __init__(self, positions=None, prices=None, lost_response=False,
                 unknown_fate=False):
        self.positions = positions if positions is not None else {}
        self.prices = prices if prices is not None else {}
        self.states = {}          # (order_id, "EXCHANGE"|"REQUEST") -> FakeOrderState
        self.orders_list = []     # активные заявки брокера (GetSandboxOrders)
        self.orders_sent = []     # (figi, lots, direction, request_uuid)
        self.cancel_calls = []    # (order_id, type_name)
        self.poll_calls = []      # (order_id, type_name) — аудит типов опроса
        self.uncertain_state = False
        self.lost_response = lost_response
        # unknown_fate: СУДЬБА ЗАЯВКИ ПОЛНОСТЬЮ НЕИЗВЕСТНА — пост-ответ
        # потерян, у брокера заявка НЕ видна (ни в списке активных, ни по
        # статусу). Ни один источник не подтверждает ни принятие, ни отказ.
        self.unknown_fate = unknown_fate

    def is_uncertain(self):
        return self.uncertain_state

    async def get_positions(self):
        return self.positions

    async def get_last_prices(self, figis):
        return {f: self.prices[f] for f in figis if f in self.prices}

    async def get_instrument_info(self, figi):
        return {"lot": 1, "ticker": "TEST"}

    async def get_sandbox_order_state(self, oid, order_id_type=None):
        t = _id_type_name(order_id_type)
        self.poll_calls.append((str(oid), t))
        if t is None:
            # прежнее поведение (запрос без order_id_type): имитируем
            # брокера, который находит заявку по любому из её ID
            found = self.states.get((str(oid), "REQUEST"))
            if found is None:
                found = self.states.get((str(oid), "EXCHANGE"))
            return found
        return self.states.get((str(oid), t))

    async def get_sandbox_orders(self):
        return list(self.orders_list)

    async def post_market_order(self, figi, quantity, direction, order_id=None):
        request_id = str(order_id)
        exchange_id = f"EX-{request_id[:8]}"
        self.orders_sent.append((figi, quantity, str(direction), request_id))
        if self.unknown_fate:
            # ответ потерян; у брокера заявка не видна НИ В ОДНОМ источнике —
            # судьба (принята/отклонена) неизвестна
            return OrderResult(order_id=request_id, state=None, error=None,
                               exchange_order_id=None, order_request_id=None)
        if self.lost_response:
            # заявка ПРИНЯТА брокером (видна в списке активных и по обоим ID),
            # но пост-ответ к роботу не вернулся
            state = FakeOrderState(4, 0, 0, exchange_order_id=exchange_id,
                                   order_request_id=request_id)
            self.states[(request_id, "REQUEST")] = state
            self.states[(exchange_id, "EXCHANGE")] = state
            self.orders_list.append(SimpleNamespace(
                order_id=exchange_id, order_request_id=request_id, figi=figi,
                direction=direction, lots_requested=quantity, lots_executed=0,
            ))
            return OrderResult(order_id=request_id, state=None, error=None,
                               exchange_order_id=None, order_request_id=None)
        state = FakeOrderState(4, 0, 0, exchange_order_id=exchange_id,
                               order_request_id=request_id)
        self.states[(request_id, "REQUEST")] = state
        self.states[(exchange_id, "EXCHANGE")] = state
        return OrderResult(order_id=request_id, state=state, error=None,
                           exchange_order_id=exchange_id, order_request_id=request_id)

    async def cancel_order(self, oid, order_id_type=None):
        self.cancel_calls.append((str(oid), _id_type_name(order_id_type)))
        return SimpleNamespace(status="OK")


# ---------------------------------------------------------------- helpers

def make_buy_pos(**over):
    base = dict(
        figi="F1", ticker="TEST", direction="BUY", entry_price=100.0,
        quantity=10, sl_price=98.0, tp_price=104.0, lot_size=1,
        state=PositionState.OPEN, trade_id="t1",
        order_send_time=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        entry_order_id="buy-1",
    )
    base.update(over)
    return TrackedPosition(**base)


def fresh_monitor(pos, client):
    monitor = ExecutionMonitor(client)
    monitor.positions[pos.figi] = pos
    return monitor


def proven_buy(ledger, figi="F1", lots=10):
    assert ledger.record_intent("buy-1", trade_id="t1", figi=figi, ticker="TEST",
                                side="BUY", requested_lots=lots, reason="")
    assert ledger.record_sent("buy-1", figi=figi, ticker="TEST", side="BUY",
                              requested_lots=lots, executed_lots=lots,
                              status_hint="FILL", reason="", source="post_response")


def run(coro):
    return asyncio.run(coro)


def read_events(tmp_path):
    path = tmp_path / "research_events.jsonl"
    if not path.is_file():
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def read_trades(tmp_path):
    path = tmp_path / "research_trades.csv"
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Изолированная среда: записи в tmp_path, торговля выключена."""
    monkeypatch.setattr(main, "is_trading_enabled", _ORIG_IS_TRADING_ENABLED)
    monkeypatch.setattr(main, "_save_state", _ORIG_SAVE_STATE)
    monkeypatch.setattr(research_logger, "EVENTS_FILE", str(tmp_path / "research_events.jsonl"))
    monkeypatch.setattr(research_logger, "TRADES_FILE", str(tmp_path / "research_trades.csv"))
    monkeypatch.setattr(main, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(main, "STATE_FILE_TMP", str(tmp_path / "state.json.tmp"))
    monkeypatch.setattr(main, "TRADING_FLAG", str(tmp_path / "trading.flag"))
    monkeypatch.setattr(config, "RECONCILE_CONFIRM_MIN_AGE_SECONDS", 30.0)
    monkeypatch.setattr(main, "_external_close_candidates", {})
    monkeypatch.setattr(main, "reconcile_done", False)
    monkeypatch.setattr(main, "state_save_failed", False)
    monkeypatch.setattr(main, "telegram_bot", None)
    monkeypatch.setattr(main, "top_instruments", [])
    monkeypatch.setattr(main, "monitor_ref", None)
    ledger = OrderLedger(str(tmp_path / "order_ledger.jsonl"))
    ledger.load()
    monkeypatch.setattr(main, "ledger_ref", ledger)
    yield SimpleNamespace(tmp_path=tmp_path, ledger=ledger, monkeypatch=monkeypatch)


# ============================================================================
# ГРУППА 1: SELL SAFETY (сценарии 1-10)
# ============================================================================

def test_1_lost_response_saves_request_uuid(env):
    """Сценарий 1: потерянный ответ (state=None) сохраняет request UUID
    в позиции; биржевой ID НЕ выдумывается и НЕ подменяется UUID."""
    ledger = env.ledger
    proven_buy(ledger)
    pos = make_buy_pos(state=PositionState.OPEN, close_reason=None)
    broker = IdAwareBroker(positions={"F1": PosData(10, "LONG")},
                           prices={"F1": 97.0}, lost_response=True)
    monitor = fresh_monitor(pos, broker)
    main.monitor_ref = monitor
    rm = main.RiskManager(None)

    run(main.close_position(broker, pos, 97.0))

    # заявка отправлена ровно один раз, UUID известен ДО вызова
    assert len(broker.orders_sent) == 1
    sent_request = broker.orders_sent[0][3]
    # клиентский UUID сохранён в позиции
    assert pos.close_order_request_id == sent_request
    # биржевой ID пуст — подмена UUID запрещена
    assert pos.close_order_id is None
    # позиция UNCERTAIN
    assert pos.state == PositionState.UNCERTAIN
    # реестр: UNCERTAIN-запись под клиентским UUID
    rec = ledger.latest(sent_request)
    assert rec is not None and rec["status"] == "UNCERTAIN"
    assert rec["side"] == "SELL"
    assert rec["order_request_id"] == sent_request
    assert rec["exchange_order_id"] is None


def test_2_no_open_on_lot_match_after_lost_response(env):
    """Сценарий 2: после потери ответа (судьба заявки полностью неизвестна:
    нет ни пост-ответа, ни заявки у брокера) позиция НЕ переходит в OPEN
    при совпадении брокерского количества — совпадение не доказывает, что
    потерянная SELL не принята брокером."""
    ledger = env.ledger
    proven_buy(ledger)
    pos = make_buy_pos(state=PositionState.OPEN)
    broker = IdAwareBroker(positions={"F1": PosData(10, "LONG")},
                           prices={"F1": 97.0}, unknown_fate=True)
    monitor = fresh_monitor(pos, broker)
    rm = main.RiskManager(None)

    run(main.trading_cycle(broker, rm, None, monitor, ledger))
    assert pos.state == PositionState.UNCERTAIN
    assert pos.close_order_request_id is not None
    assert pos.close_order_id is None
    # повторный цикл: совпадение 10 == 10 не открывает позицию
    run(main.trading_cycle(broker, rm, None, monitor, ledger))
    assert pos.state == PositionState.UNCERTAIN
    assert pos.state != PositionState.OPEN
    assert pos.quantity == 10
    assert len(broker.orders_sent) == 1  # вторая SELL не отправлялась


def test_3_repeated_close_position_no_second_sell(env):
    """Сценарий 3: повторный close_position не отправляет вторую SELL —
    SL/TP снова пробивает уровень по позиции с незавершённой SELL
    (заявка не отправляется, причина блокировки фиксируется в журнале)."""
    ledger = env.ledger
    proven_buy(ledger)
    pos = make_buy_pos(state=PositionState.OPEN)
    broker = IdAwareBroker(positions={"F1": PosData(10, "LONG")},
                           prices={"F1": 97.0}, lost_response=True)
    monitor = fresh_monitor(pos, broker)
    rm = main.RiskManager(None)

    # первый вызов: потерянный ответ, заявка принята брокером (NEW)
    run(main.trading_cycle(broker, rm, None, monitor, ledger))
    assert pos.state != PositionState.OPEN, "позиция открыта при незавершённой SELL"
    assert len(broker.orders_sent) == 1

    # SL/TP снова пробивает (позиция должна была бы закрыться, но она UNCERTAIN) —
    # прямой контроль: принудительный повторный вызов close_position запрещён
    pos.state = PositionState.OPEN  # гипотетическая попытка обхода
    run(main.close_position(broker, pos, 97.0))
    assert len(broker.orders_sent) == 1, "повторная SELL отправлена при незавершённой предыдущей"
    assert pos.state == PositionState.UNCERTAIN, "позиция оставлена в OPEN при незавершённой SELL"
    # событие блокировки записано
    events = [e["event"] for e in read_events(env.tmp_path)]
    assert "SELL_DUPLICATE_BLOCKED" in events


def test_4_uncertain_sell_blocks_buy_same_figi(env):
    """Сценарий 4: UNCERTAIN SELL блокирует BUY по тому же FIGI —
    и на уровне реестра, и в торговом цикле."""
    ledger = env.ledger
    # реестр: незавершённая SELL по F1
    assert ledger.record_intent("sell-u1", trade_id="t1", figi="F1", ticker="TEST",
                                side="SELL", requested_lots=10)
    assert ledger.record_uncertain("sell-u1", figi="F1", ticker="TEST", side="SELL",
                                   requested_lots=10, reason="ответ потерян")
    # unit-уровень: блокировки реестра
    assert ledger.figi_blocks_buy("F1") is True, "UNCERTAIN SELL обязан блокировать BUY"
    assert ledger.figi_has_open_order("F1", "SELL") is True
    # другой FIGI не блокируется
    assert ledger.figi_blocks_buy("OTHER") is False
    assert ledger.figi_blocks_buy("buy-1") is False  # terminal BUY не блокирует

    # интеграция: торговый цикл не доходит до построения свечей/входа
    broker = IdAwareBroker(positions={}, prices={"F1": 100.0})
    monitor = ExecutionMonitor(broker)
    rm = main.RiskManager(None)
    sm = SimpleNamespace(get_signal=lambda df, price, drop_incomplete=True: ("BUY", "test"))

    async def fail_df(*a, **k):
        raise AssertionError("_build_candles_df вызван — FIGI-блокировка не сработала")

    env.monkeypatch.setattr(main, "_build_candles_df", fail_df)
    env.monkeypatch.setattr(main, "top_instruments",
                            [{"figi": "F1", "ticker": "TEST"}])
    run(main.trading_cycle(broker, rm, sm, monitor, ledger))
    assert broker.orders_sent == [], "BUY отправлен при незавершённой SELL по FIGI"


def test_5_restart_keeps_unresolved_sell_blocked(env):
    """Сценарий 5: после перезапуска незавершённая SELL остаётся
    заблокированной (state.json + реестр восстанавливаются; новая среда;
    повторная SELL не отправляется, OPEN недоступен)."""
    ledger = env.ledger
    proven_buy(ledger)
    pos = make_buy_pos(state=PositionState.OPEN)
    broker = IdAwareBroker(positions={"F1": PosData(10, "LONG")},
                           prices={"F1": 97.0}, lost_response=True)
    monitor = fresh_monitor(pos, broker)
    main.monitor_ref = monitor
    rm = main.RiskManager(None)
    run(main.trading_cycle(broker, rm, None, monitor, ledger))
    assert pos.state != PositionState.OPEN
    request_id = pos.close_order_request_id

    # --- перезапуск: сохранение и восстановление состояния ---
    assert main._save_state(monitor, rm) is True
    monitor2 = ExecutionMonitor(broker)
    rm2 = main.RiskManager(None)
    assert main._load_state(monitor2, rm2) is True
    restored = monitor2.positions["F1"]
    assert restored.state != PositionState.OPEN, "рестарт открыл позицию при незавершённой SELL"
    assert restored.close_order_request_id == request_id
    ledger2 = OrderLedger(str(env.tmp_path / "order_ledger.jsonl"))
    ledger2.load()
    restarted_rec = ledger2.latest(request_id)
    assert restarted_rec["status"] in ("UNCERTAIN", "NEW", "SENT", "PARTIALLYFILL"), \
        "незавершённая SELL стала терминальной без отчёта брокера"
    # блокировка BUY по FIGI активна и после рестарта
    assert ledger2.figi_blocks_buy("F1") is True

    # --- новая среда: брокерский остаток совпадает, незавершённая SELL
    #     по-прежнему блокирует новую SELL и OPEN ---
    env.monkeypatch.setattr(main, "ledger_ref", ledger2)
    env.monkeypatch.setattr(main, "monitor_ref", monitor2)
    run(main.trading_cycle(broker, rm2, None, monitor2, ledger2))
    assert restored.state != PositionState.OPEN
    assert len(broker.orders_sent) == 1, "после рестарта отправлена вторая SELL"


def test_6_active_broker_order_linked_via_request_id(env):
    """Сценарий 6: активная заявка брокера связывается с ledger через
    order_request_id; биржевой ID восстанавливается в существующую запись
    и в позицию (обе ссылки), вторая запись реестра не создаётся."""
    ledger = env.ledger
    proven_buy(ledger)
    request_id = str(uuid.uuid4())
    exchange_id = "EX-LINK01"
    # запись робота: SELL отправлена, пост-ответ потерян (UNCERTAIN)
    assert ledger.record_intent(request_id, trade_id="t1", figi="F1", ticker="TEST",
                                side="SELL", requested_lots=10, reason="close:SL")
    assert ledger.record_uncertain(request_id, figi="F1", ticker="TEST", side="SELL",
                                   requested_lots=10, reason="post: ответ потерян")

    pos = make_buy_pos(state=PositionState.UNCERTAIN, close_reason="SL",
                       close_order_request_id=request_id, close_requested_lots=10)
    broker = IdAwareBroker(positions={"F1": PosData(10, "LONG")}, prices={"F1": 100.0})
    # активная заявка брокера: биржевой ID + клиентский UUID
    broker.orders_list.append(SimpleNamespace(
        order_id=exchange_id, order_request_id=request_id, figi="F1",
        direction=2, lots_requested=10, lots_executed=0,  # direction SELL
    ))
    monitor = fresh_monitor(pos, broker)
    rm = main.RiskManager(None)
    main.monitor_ref = monitor

    run(main.startup_recovery(broker, monitor, rm, ledger))

    # дубликат не создан: в реестре ровно одна запись этой SELL — под UUID
    assert ledger.has_order(request_id) is True
    assert ledger.has_order(exchange_id) is False
    sell_records = [r for r in ledger.latest_all().values() if r["side"] == "SELL"]
    assert len(sell_records) == 1
    # биржевой ID сохранён в СУЩЕСТВУЮЩЕЙ записи отдельным полем
    rec = ledger.latest(request_id)
    assert rec["exchange_order_id"] == exchange_id
    assert rec["order_request_id"] == request_id
    # позиция связана: обе ссылки восстановлены
    assert pos.close_order_request_id == request_id
    assert pos.close_order_id == exchange_id


def test_7_get_sandbox_orders_duplicate_no_new_record(env):
    """Сценарий 7: заявка, известная реестру (совпадение order_request_id),
    из GetSandboxOrders НЕ создаёт вторую запись реестра."""
    ledger = env.ledger
    proven_buy(ledger)
    request_id = str(uuid.uuid4())
    exchange_id = "EX-DUP001"
    assert ledger.record_intent(request_id, trade_id="t1", figi="F1", ticker="TEST",
                                side="SELL", requested_lots=10)
    before_keys = set(ledger.latest_all().keys())
    before_count = len(ledger.latest_all())

    pos = make_buy_pos(state=PositionState.UNCERTAIN, close_reason="SL",
                       close_order_request_id=request_id, close_requested_lots=10)
    broker = IdAwareBroker(positions={"F1": PosData(10, "LONG")}, prices={"F1": 100.0})
    broker.orders_list.append(SimpleNamespace(
        order_id=exchange_id, order_request_id=request_id, figi="F1",
        direction=2, lots_requested=10, lots_executed=0,
    ))
    monitor = fresh_monitor(pos, broker)
    rm = main.RiskManager(None)
    main.monitor_ref = monitor

    run(main.startup_recovery(broker, monitor, rm, ledger))

    after = ledger.latest_all()
    assert len(after) == before_count, "создана вторая запись для известной заявки"
    assert exchange_id not in after, "биржевой ID стал отдельной записью"
    assert set(after.keys()) - before_keys == set(), "ключи записей изменились"
    assert ledger.latest(request_id)["exchange_order_id"] == exchange_id


def test_8_ambiguous_match_stays_uncertain(env):
    """Сценарий 8: неоднозначное сопоставление (trade_id записи не совпадает
    с trade_id позиции) НЕ связывает заявку с позицией и оставляет
    неопределённость; новая заявка не отправляется."""
    ledger = env.ledger
    proven_buy(ledger, figi="F1")
    request_id = str(uuid.uuid4())
    exchange_id = "EX-AMB001"
    # запись ДРУГОЙ сделки (trade_id=tX)
    assert ledger.record_intent(request_id, trade_id="tX", figi="F1", ticker="TEST",
                                side="SELL", requested_lots=10)
    assert ledger.record_uncertain(request_id, figi="F1", ticker="TEST", side="SELL",
                                   requested_lots=10, reason="неопределённость")

    pos = make_buy_pos(state=PositionState.UNCERTAIN, trade_id="t1",
                       close_order_request_id=None, close_requested_lots=10)
    broker = IdAwareBroker(positions={"F1": PosData(10, "LONG")}, prices={"F1": 100.0})
    broker.orders_list.append(SimpleNamespace(
        order_id=exchange_id, order_request_id=request_id, figi="F1",
        direction=2, lots_requested=10, lots_executed=0,
    ))
    monitor = fresh_monitor(pos, broker)
    rm = main.RiskManager(None)
    main.monitor_ref = monitor

    run(main.startup_recovery(broker, monitor, rm, ledger))

    # позиция НЕ привязана: совпадение только по FIGI/времени недостаточно
    assert pos.close_order_request_id is None
    assert pos.close_order_id is None
    # запись остаётся незавершённой — блокировка сохраняется
    rec = ledger.latest(request_id)
    assert rec["status"] not in main._TERMINAL_ORDER_STATUSES
    assert ledger.figi_blocks_buy("F1") is True
    # новая SELL не отправляется
    assert broker.orders_sent == []
    # повторный цикл: OPEN запрещён (незавершённая SELL-запись реестра по FIGI)
    run(main.trading_cycle(broker, rm, None, monitor, ledger))
    assert pos.state != PositionState.OPEN
    assert len(broker.orders_sent) == 0


def test_9_terminal_result_allows_existing_processing(env):
    """Сценарий 9: терминальный результат исходной заявки разрешает
    дальнейшую обработку по существующим правилам: CANCELLED с исполнением
    -> подтверждение остатка снимком -> OPEN -> SL отправляет РОВНО ОДНУ
    новую SELL на остаток."""
    ledger = env.ledger
    proven_buy(ledger)
    pos = make_buy_pos(state=PositionState.OPEN)
    broker = IdAwareBroker(positions={"F1": PosData(7, "LONG")},
                           prices={"F1": 97.0}, lost_response=True)
    monitor = fresh_monitor(pos, broker)
    rm = main.RiskManager(None)

    run(main.trading_cycle(broker, rm, None, monitor, ledger))
    request_id = pos.close_order_request_id
    assert pos.state != PositionState.OPEN, "позиция открыта при незавершённой SELL"
    # исполнение 3 лотов по потерянной заявке
    broker.states[(request_id, "REQUEST")].lots_executed = 3
    broker.states[(request_id, "REQUEST")].execution_report_status = 5  # PARTIALLYFILL
    run(main.trading_cycle(broker, rm, None, monitor, ledger))
    assert pos.quantity == 7
    assert pos.state == PositionState.UNCERTAIN

    # терминальный отчёт: CANCELLED (3 исполнено) — заявка разрешена
    broker.states[(request_id, "REQUEST")].execution_report_status = 3
    broker.states[(exchange_key := f"EX-{request_id[:8]}", "EXCHANGE")] = \
        broker.states[(request_id, "REQUEST")]
    run(main.trading_cycle(broker, rm, None, monitor, ledger))
    assert pos.state == PositionState.OPEN, "терминальный отчёт не разрешил остаток"
    assert pos.quantity == 7
    assert pos.close_order_request_id is None
    assert pos.close_order_id is None
    assert len(broker.orders_sent) == 1

    # штатное возобновление: SL пробит — РОВНО ОДНА новая SELL на 7 лотов
    broker.prices["F1"] = 97.0
    run(main.trading_cycle(broker, rm, None, monitor, ledger))
    assert len(broker.orders_sent) == 2, "новая SELL после терминала не отправлена или дублирована"
    assert broker.orders_sent[1][1] == 7
    new_request = broker.orders_sent[1][3]
    assert new_request != request_id, "повторно использован старый клиентский UUID"
    assert pos.state == PositionState.CLOSING


def test_10_absence_in_one_source_does_not_unblock(env):
    """Сценарий 10: отсутствие заявки в ОДНОМ источнике не разблокирует
    FIGI: GetSandboxOrders не содержит заявку и статус недоступен —
    запись остаётся UNCERTAIN, BUY и новая SELL запрещены."""
    ledger = env.ledger
    proven_buy(ledger)
    request_id = str(uuid.uuid4())
    assert ledger.record_intent(request_id, trade_id="t1", figi="F1", ticker="TEST",
                                side="SELL", requested_lots=10)
    assert ledger.record_uncertain(request_id, figi="F1", ticker="TEST", side="SELL",
                                   requested_lots=10, reason="post: ответ потерян")
    pos = make_buy_pos(state=PositionState.UNCERTAIN, close_reason="SL",
                       close_order_request_id=request_id, close_requested_lots=10)
    broker = IdAwareBroker(positions={"F1": PosData(10, "LONG")}, prices={"F1": 100.0})
    # заявка НЕ в списке активных (orders_list пуст) и статус недоступен
    # (states пуст) — НИ ОДИН источник не разблокирует FIGI
    monitor = fresh_monitor(pos, broker)
    rm = main.RiskManager(None)
    main.monitor_ref = monitor

    run(main.startup_recovery(broker, monitor, rm, ledger))
    assert ledger.latest(request_id)["status"] == "UNCERTAIN"
    assert ledger.figi_blocks_buy("F1") is True

    run(main.trading_cycle(broker, rm, None, monitor, ledger))
    assert pos.state != PositionState.OPEN
    assert ledger.latest(request_id)["status"] == "UNCERTAIN"
    assert ledger.figi_blocks_buy("F1") is True, "разблокировка без терминального результата"
    assert broker.orders_sent == []
    events = [e["event"] for e in read_events(env.tmp_path)]
    assert "BUY_UNKNOWN" not in events


# ============================================================================
# ГРУППА 2: ИДЕНТИФИКАТОРЫ (сценарии 11-18)
# ============================================================================

def test_11_order_result_saves_both_ids():
    """Сценарий 11: OrderResult сохраняет ОБА идентификатора (клиентский
    UUID и биржевой), order_id — прежний клиентский UUID (совместимость)."""
    broker = IdAwareBroker()
    result = run(broker.post_market_order("F1", 5, "BUY", order_id="req-abc"))
    assert isinstance(result, OrderResult)
    assert result.order_id == "req-abc"                 # совместимость
    assert result.exchange_order_id == "EX-req-abc"     # биржевой
    assert result.order_request_id == "req-abc"         # клиентский из ответа
    assert result.exchange_order_id != result.order_id  # РАЗНЫЕ (§8)


def test_12_post_order_response_exchange_id_not_lost(env):
    """Сценарий 12: PostOrderResponse.order_id (БИРЖЕВОЙ) не теряется —
    сохраняется в OrderResult и в записи реестра."""
    ledger = env.ledger
    proven_buy(ledger)
    pos = make_buy_pos(state=PositionState.OPEN)
    broker = IdAwareBroker(positions={"F1": PosData(10, "LONG")}, prices={"F1": 97.0})
    monitor = fresh_monitor(pos, broker)
    main.monitor_ref = monitor
    rm = main.RiskManager(None)

    run(main.trading_cycle(broker, rm, None, monitor, ledger))
    request_id = broker.orders_sent[0][3]
    exchange_id = f"EX-{request_id[:8]}"
    # OrderResult сохранил биржевой ID
    assert pos.close_order_id == exchange_id
    # запись реестра SENT содержит биржевой ID
    rec = ledger.latest(request_id)
    assert rec["status"] in ("NEW", "SENT")
    assert rec["exchange_order_id"] == exchange_id
    assert rec["order_request_id"] == request_id


def test_13_post_order_response_request_id_not_lost(env):
    """Сценарий 13: PostOrderResponse.order_request_id (КЛИЕНТСКИЙ UUID)
    не теряется — сохраняется в OrderResult и в записи реестра."""
    broker = IdAwareBroker()
    result = run(broker.post_market_order("F1", 5, "BUY", order_id="req-xyz"))
    assert result.order_request_id == "req-xyz"
    assert result.state.order_request_id == "req-xyz"  # OrderState тоже

    # в реестре: record_intent фиксирует order_request_id == order_id
    ledger = env.ledger
    assert ledger.record_intent("req-xyz", trade_id="t9", figi="F9", ticker="T9",
                                side="BUY", requested_lots=5)
    rec = ledger.latest("req-xyz")
    assert rec["order_request_id"] == "req-xyz"
    # record_sent наследует и не теряет
    assert ledger.record_sent("req-xyz", figi="F9", ticker="T9", side="BUY",
                              requested_lots=5, executed_lots=0,
                              status_hint="NEW", exchange_order_id="EX-req-xyz")
    rec = ledger.latest("req-xyz")
    assert rec["order_request_id"] == "req-xyz"
    assert rec["exchange_order_id"] == "EX-req-xyz"


def test_14_get_order_state_exchange_id_uses_exchange_type():
    """Сценарий 14: GetOrderState с БИРЖЕВЫМ ID использует
    ORDER_ID_TYPE_EXCHANGE."""
    broker = IdAwareBroker()
    run(broker.post_market_order("F1", 5, "BUY", order_id="req-e1"))
    exchange_id = "EX-req-e1"
    state = run(broker.get_sandbox_order_state(exchange_id, order_id_type="EXCHANGE"))
    assert state is not None
    assert ("EX-req-e1", "EXCHANGE") in [(o, t) for o, t in broker.poll_calls]


def test_15_get_order_state_uuid_uses_request_type():
    """Сценарий 15: GetOrderState с КЛИЕНТСКИМ UUID использует
    ORDER_ID_TYPE_REQUEST (UUID не передаётся как биржевой ID)."""
    broker = IdAwareBroker()
    run(broker.post_market_order("F1", 5, "BUY", order_id="req-u1"))
    state = run(broker.get_sandbox_order_state("req-u1", order_id_type="REQUEST"))
    assert state is not None
    # неправильный тип для UUID — отрицательный результат (§8)
    wrong = run(broker.get_sandbox_order_state("req-u1", order_id_type="EXCHANGE"))
    assert wrong is None, "фейк вернул заявку при неправильном типе поиска"


def test_16_request_lookup_unavailable_fails_closed(env):
    """Сценарий 16: невозможность запроса по REQUEST приводит к
    fail-closed (состояние НЕИЗВЕСТНО, позиция UNCERTAIN), а не к ложному
    NOT_FOUND."""
    # 16a: SDK не позволяет запрос по REQUEST — клиент возвращает None,
    # сетевой вызов НЕ выполняется (никакой имитации успешного поиска).
    import tinkoff_client
    # CORRECTIVE AUDIT V2 (FIX-2): имя атрибута приведено к фактическому
    # контракту модуля tinkoff_client (production импортирует enum как
    # OrderIdType из t_tech.invest.schemas; атрибута Order_id_type у
    # модуля нет — прежнее имя вызывало AttributeError ДО начала проверки,
    # тест не выполнялся ни на одном состоянии кода). Смысл проверки
    # НЕ меняется: подмена enum на None имитирует «SDK не экспортирует
    # OrderIdType» и должна давать fail-closed (None) без сетевого вызова.
    saved_enum = tinkoff_client.OrderIdType
    try:
        tinkoff_client.OrderIdType = None
        client = tinkoff_client.TinkoffClient(token="test-token")

        class FailBroker:
            def __init__(self):
                self.calls = []

            async def get_sandbox_order_state(self, **kwargs):
                self.calls.append(kwargs)
                raise AssertionError("сетевой вызов не должен выполняться")

            async def cancel_sandbox_order(self, **kwargs):
                self.calls.append(kwargs)
                raise AssertionError("сетевой вызов не должен выполняться")

        fb = FailBroker()
        client.account_id = "acc"
        client.client = SimpleNamespace(sandbox=fb)
        assert run(client.get_sandbox_order_state("req-1", order_id_type="REQUEST")) is None
        assert run(client.cancel_order("req-1", order_id_type="REQUEST")) is None
        assert fb.calls == [], "при недоступном SDK-enum выполнен сетевой вызов"
        # legacy-вызов (без типа) по-прежнему выполняется — прежнее поведение
        assert run(client.get_sandbox_order_state("req-1")) is None  # исключение -> None
        assert len(fb.calls) == 1
    finally:
        tinkoff_client.OrderIdType = saved_enum

    # 16b: заявка ищется только по правильной паре (ID, тип): неправильный
    # тип даёт None -> позиция остаётся UNCERTAIN, разблокировки нет.
    ledger = env.ledger
    proven_buy(ledger)
    request_id = str(uuid.uuid4())
    assert ledger.record_intent(request_id, trade_id="t1", figi="F1", ticker="TEST",
                                side="SELL", requested_lots=10)
    pos = make_buy_pos(state=PositionState.CLOSING, close_reason="SL",
                       close_order_request_id=request_id, close_requested_lots=10)
    broker = IdAwareBroker(positions={"F1": PosData(10, "LONG")}, prices={"F1": 100.0})
    # заявка известна брокеру ТОЛЬКО по биржевому ID (REQUEST-поиск не найдёт)
    exchange_id = "EX-ONLY01"
    broker.states[(exchange_id, "EXCHANGE")] = FakeOrderState(3, 0, 0,
                                                              exchange_order_id=exchange_id,
                                                              order_request_id=request_id)
    monitor = fresh_monitor(pos, broker)
    rm = main.RiskManager(None)
    run(main.trading_cycle(broker, rm, None, monitor, ledger))
    assert pos.state == PositionState.UNCERTAIN, "ложный NOT_FOUND разблокировал позицию"
    assert len(broker.orders_sent) == 0
    # опрос шёл по REQUEST с клиентским UUID — и не «нашёл» чужую пару
    assert (request_id, "REQUEST") in [(o, t) for o, t in broker.poll_calls]


def test_17_ledger_saves_both_ids_roundtrip(tmp_path):
    """Сценарий 17: Ledger сохраняет ОБА идентификатора, перезапуск
    (JSONL round-trip) их не теряет."""
    path = str(tmp_path / "order_ledger.jsonl")
    ledger = OrderLedger(path)
    ledger.load()
    assert ledger.record_intent("req-17", trade_id="t17", figi="F17", ticker="T17",
                                side="SELL", requested_lots=4)
    assert ledger.record_sent("req-17", figi="F17", ticker="T17", side="SELL",
                              requested_lots=4, executed_lots=0, status_hint="NEW",
                              exchange_order_id="EX-17", order_request_id="req-17")
    assert ledger.record_status("req-17", "PARTIALLYFILL", figi="F17", ticker="T17",
                                side="SELL", requested_lots=4, executed_lots=2)

    # перезапуск
    ledger2 = OrderLedger(path)
    ledger2.load()
    rec = ledger2.latest("req-17")
    assert rec is not None
    assert rec["exchange_order_id"] == "EX-17"
    assert rec["order_request_id"] == "req-17"
    assert rec["status"] == "PARTIALLYFILL"
    assert rec["executed_lots"] == 2


def test_18_old_ledger_records_readable(tmp_path):
    """Сценарий 18: старые ledger-записи (без новых полей) читаются без
    ошибок; поверх них append работает; блокировки работают."""
    path = str(tmp_path / "order_ledger.jsonl")
    old_line = json.dumps({
        "record_type": "ORDER_STATUS", "timestamp_utc": "2025-01-01T00:00:00+00:00",
        "status": "INTENT", "order_id": "old-uuid-1", "trade_id": "t-old",
        "figi": "F-OLD", "ticker": "OLD", "side": "SELL", "requested_lots": 3,
        "executed_lots": None, "lots_left": None, "avg_exec_price": None,
        "reason": "close:SL", "source": "pre_send",
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(old_line + "\n")
    ledger = OrderLedger(path)
    ledger.load()
    assert ledger.is_reliable()
    rec = ledger.latest("old-uuid-1")
    assert rec["status"] == "INTENT"
    assert rec["exchange_order_id"] is None      # старые записи — поля None
    assert rec["order_request_id"] is None
    # append поверх старой записи работает
    assert ledger.record_status("old-uuid-1", "PARTIALLYFILL", figi="F-OLD",
                                ticker="OLD", side="SELL", requested_lots=3,
                                executed_lots=1)
    rec = ledger.latest("old-uuid-1")
    assert rec["status"] == "PARTIALLYFILL"
    # идентичность сохранена, новые поля не «выдуманы»
    assert rec["figi"] == "F-OLD"
    # блокировки работают на старых записях
    assert ledger.figi_has_open_order("F-OLD", "SELL") is True
    assert ledger.figi_blocks_buy("F-OLD") is True


# ============================================================================
# ГРУППА 3: МИГРАЦИЯ state.json (сценарии 19-23)
# ============================================================================

def _legacy_state_dict(close_oid):
    """Старый формат state.json: close_order_id фактически содержит
    КЛИЕНТСКИЙ UUID; новых полей нет."""
    return {
        "figi": "F1", "ticker": "TEST", "direction": "BUY", "entry_price": 100.0,
        "quantity": 10, "sl_price": 98.0, "tp_price": 104.0, "lot_size": 1,
        "state": "CLOSING", "close_reason": "SL", "close_order_id": close_oid,
        "close_requested_at": "2025-01-01T00:00:00+00:00",
        "close_price_before_order": 100.0, "executed_lots": 0,
        "execution_price": None, "trade_id": "t1",
        "close_requested_lots": 10, "close_applied_lots": 0,
    }


def test_19_legacy_state_migrates_uuid():
    """Сценарий 19: старый state.json с close_order_id=UUID корректно
    мигрирует: UUID -> close_order_request_id, close_order_id очищается
    (фиктивный биржевой ID не создаётся)."""
    legacy_uuid = "11111111-2222-3333-4444-555555555555"
    pos = TrackedPosition.from_dict(_legacy_state_dict(legacy_uuid))
    assert pos.close_order_request_id == legacy_uuid
    assert pos.close_order_id is None
    # остальные данные не потеряны
    assert pos.quantity == 10
    assert pos.close_requested_lots == 10
    assert pos.state == PositionState.CLOSING


def test_20_new_state_restores_both_ids():
    """Сценарий 20: новый state.json с двумя ID корректно восстанавливается
    (миграция не трогает уже разделённые идентификаторы)."""
    d = _legacy_state_dict("legacy")
    d["close_order_id"] = "EX-NEW01"
    d["close_order_request_id"] = "req-new-1"
    d["close_orders"] = {
        "req-new-1": {"order_id": "req-new-1", "trade_id": "t1", "figi": "F1",
                      "side": "SELL", "requested_lots": 10,
                      "confirmed_executed_lots": 0, "applied_lots": 0,
                      "status": "NEW", "requested_at": None,
                      "avg_exec_price": None, "commission": None},
    }
    d["close_applications"] = []
    pos = TrackedPosition.from_dict(d)
    assert pos.close_order_id == "EX-NEW01"
    assert pos.close_order_request_id == "req-new-1"
    assert pos.close_orders["req-new-1"]["status"] == "NEW"


def test_21_migration_idempotent():
    """Сценарий 21: повторная миграция (загрузка/сохранение/загрузка) не
    меняет смысл идентификаторов и не теряет данные."""
    legacy_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    pos1 = TrackedPosition.from_dict(_legacy_state_dict(legacy_uuid))
    exported = pos1.to_dict()
    pos2 = TrackedPosition.from_dict(exported)
    assert pos2.close_order_request_id == legacy_uuid
    assert pos2.close_order_id is None
    exported2 = pos2.to_dict()
    assert exported2 == exported, "повторное сохранение изменило данные"
    pos3 = TrackedPosition.from_dict(exported2)
    assert pos3.to_dict() == exported, "третья миграция изменила данные"


def test_22_uncertain_stays_uncertain_after_migration(env):
    """Сценарий 22: UNCERTAIN после миграции остаётся UNCERTAIN (миграция
    не сбрасывает состояние в OPEN), опрос идёт по клиентскому UUID."""
    legacy_uuid = "99999999-8888-7777-6666-555555555555"
    d = _legacy_state_dict(legacy_uuid)
    d["state"] = "UNCERTAIN"
    monitor = ExecutionMonitor(IdAwareBroker())
    monitor.import_state({"positions": {"F1": d}, "monitoring_error": False,
                          "closed_entry_order_ids": []})
    pos = monitor.positions["F1"]
    assert pos.state == PositionState.UNCERTAIN, "миграция сбросила UNCERTAIN"
    assert pos.close_order_request_id == legacy_uuid
    assert pos.close_order_id is None
    # восстановленная позиция не разрешается в OPEN при совпадающем снимке
    monitor.resolve_uncertain(
        pos, {"F1": PosData(10, "LONG")},
        ledger=None,
    )
    assert pos.state == PositionState.UNCERTAIN


def test_23_legacy_v2v3_state_no_data_loss(env):
    """Сценарий 23: legacy V2/V3 позиции без новых полей загружаются без
    потери данных (все прежние поля сохраняются, недостающие — безопасные
    значения по умолчанию)."""
    v2_state = {
        "figi": "F-V2", "ticker": "V2TICK", "direction": "BUY",
        "entry_price": 55.15, "quantity": 945, "sl_price": 54.15,
        "tp_price": 57.0, "lot_size": 1, "state": "OPEN",
        "trade_id": "v2trade", "signal_reason": "TEST_REASON",
        "signal_time": "2025-01-01T10:00:00+00:00",
        "price_before_order": 55.10,
        "order_send_time": "2025-01-01T10:00:01+00:00",
        "partial": False, "logged": False,
        # НЕТ: close_orders, close_applications, телеметрии С1,
        # close_order_request_id, exit_price_confirmed
    }
    monitor = ExecutionMonitor(IdAwareBroker())
    monitor.import_state({"positions": {"F-V2": v2_state}, "monitoring_error": False})
    pos = monitor.positions["F-V2"]
    # все данные V2 на месте
    assert pos.entry_price == 55.15
    assert pos.quantity == 945
    assert pos.sl_price == 54.15
    assert pos.tp_price == 57.0
    assert pos.trade_id == "v2trade"
    assert pos.signal_reason == "TEST_REASON"
    assert pos.state == PositionState.OPEN
    # безопасные defaults, данные не «выдуманы»
    assert pos.close_order_id is None
    assert pos.close_order_request_id is None
    assert pos.close_orders == {}
    assert pos.close_applications == []
    assert pos.exit_price_confirmed is False
    assert pos.initial_sl_price == 54.15  # восстановлен из sl
    assert pos.initial_tp_price == 57.0
    # round-trip сохраняет всё
    exported = pos.to_dict()
    pos2 = TrackedPosition.from_dict(exported)
    assert pos2.entry_price == 55.15 and pos2.quantity == 945
    assert pos2.close_order_request_id is None
    assert pos2.close_order_id is None


# ============================================================================
# ДИАГНОСТИЧЕСКИЙ ТЕСТ (вне нумерации §8): конфликт биржевых ID при
# привязке активной заявки брокера — добавлен по отдельному заданию
# ЭТАП 5Б, TEST ONLY: production-код не изменяется.
# ============================================================================

def test_24_link_broker_order_exchange_id_conflict_not_silent_success():
    """Диагностика: конфликт двух РАЗНЫХ биржевых ID не должен молча
    считаться успешной привязкой (_link_broker_order_to_position, §5.4).

    Позиция (BUY, UNCERTAIN, trade_id=t1, figi=F1) уже несёт
    close_order_request_id=request_id и close_order_id="EX-OLD". В
    _link_broker_order_to_position передаётся тот же request_id, но
    ДРУГОЙ биржевой ID "EX-NEW". Безопасное поведение: функция возвращает
    False (конфликт требует ручного разбора), оба исходных ID остаются
    без изменений; существующий биржевой ID не перезаписывается."""
    request_id = str(uuid.uuid4())
    pos = make_buy_pos(
        state=PositionState.UNCERTAIN,
        close_order_request_id=request_id,
        close_order_id="EX-OLD",
    )
    # предусловия: позиция удовлетворяет условиям сопоставления
    assert pos.figi == "F1" and pos.trade_id == "t1"
    assert pos.direction == "BUY" and pos.state == PositionState.UNCERTAIN
    assert pos.close_order_request_id == request_id
    assert pos.close_order_id == "EX-OLD"

    broker = IdAwareBroker(positions={"F1": PosData(10, "LONG")},
                           prices={"F1": 100.0})
    monitor = fresh_monitor(pos, broker)
    rec = {"figi": "F1", "side": "SELL", "trade_id": "t1"}

    result = main._link_broker_order_to_position(monitor, request_id,
                                                 "EX-NEW", rec)

    # 1) конфликт двух разных биржевых ID (EX-OLD в позиции против
    #    EX-NEW у брокера) — НЕ успешная привязка
    assert result is False, (
        "конфликт биржевых ID молча принят как успешная привязка: "
        f"result={result!r}, close_order_id={pos.close_order_id!r}, "
        f"close_order_request_id={pos.close_order_request_id!r}"
    )
    # 2) существующий биржевой ID НЕ перезаписан значением брокера
    assert pos.close_order_id == "EX-OLD", (
        f"close_order_id перезаписан: {pos.close_order_id!r} "
        "(ожидалось 'EX-OLD')"
    )
    # 3) клиентский UUID остался исходным
    assert pos.close_order_request_id == request_id, (
        f"close_order_request_id изменён: {pos.close_order_request_id!r}"
    )
