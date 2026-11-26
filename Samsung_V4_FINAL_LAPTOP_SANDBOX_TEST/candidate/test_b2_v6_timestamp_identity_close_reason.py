# test_b2_v6_timestamp_identity_close_reason.py
# Tsclp_v2.2_volatile — тесты v2.3.9-stage1 (B2 V6):
#   Defect A — ПЕРВОНАЧАЛЬНОЕ ВРЕМЯ ЗАПРОСА SELL НЕ ПЕРЕЗАПИСЫВАЕТСЯ
#     через B2 reconcile: pos.close_requested_at (если валиден) —
#     неизменяемый факт; updated_at_utc/timestamp_utc реестра (время
#     ПОЗДНЕЙ синхронизации записи) и время восстановления статуса его
#     не заменяют; при отсутствии — requested_at СВОЕГО per-order
#     cursor'а / собственной записи close_orders; если исторического
#     времени нет вообще — остаётся None (datetime.now() внутрь функции
#     восстановления НЕ подставляется, управление передаётся явно
#     обозначенной legacy-политике записи CSV); timestamp другой заявки
#     или другой сделки не используется никогда.
#   Defect B — СТРОГАЯ проверка идентичности per-order cursor'а при
#     восстановлении pending CSV recovery: НОВЫЙ формат cursor'а (явный
#     маркер identity_version) требует trade_id, FIGI, side,
#     идентификатора собственной заявки (order_id == ключу) — пустое
#     обязательное поле = конфликт (cursor_missing_*), противоречие =
#     конфликт (cursor_*_mismatch); LEGACY cursor (без маркера) —
#     отдельная политика: проверяются все ДОСТУПНЫЕ идентификаторы,
#     противоречие fail-closed, неполнота НЕ выдаётся за полную
#     (cursor_validation="legacy_limited"); клиентский UUID, биржевой ID
#     и trade_id не подменяют друг друга.
#   Defect C — ПУСТОЙ close_reason в _try_resolve_absent_position()
#     больше не вызывает IndexError ("close:" -> .split()[0]); прежняя
#     известная причина сохраняется, неизвестная — существующий
#     безопасный fallback проекта ("LEDGER_CLOSE"); семантика обычных
#     причин (close:STOP_LOSS и т.п.) не изменилась.
#
# Соответствие сценариям ТЗ V6:
#   V6-A test_v6_a_reconcile_keeps_initial_request_timestamp
#   V6-B test_v6_b_missing_position_ts_restored_from_own_cursor
#   V6-C test_v6_c_no_historical_ts_left_absent_legacy_policy
#   V6-D test_v6_d_cross_trade_timestamp_isolated_and_fail_closed
#   V6-E test_v6_e_new_cursor_missing_trade_id_fail_closed
#   V6-F test_v6_f_new_cursor_missing_figi_fail_closed
#   V6-G test_v6_g_new_cursor_missing_side_fail_closed
#   V6-H test_v6_h_new_cursor_wrong_identity_fail_closed
#   V6-I test_v6_i_valid_new_cursor_recovery_completes
#   V6-J test_v6_j_valid_legacy_cursor_recovery_completes
#   V6-K test_v6_k_legacy_cursor_contradiction_fail_closed
#   V6-L test_v6_l_conflict_task_stays_blocked_after_restart
#   V6-M test_v6_m_empty_close_reason_no_indexerror_fallback
#   V6-N test_v6_n_empty_close_reason_keeps_known_reason
#   V6-O test_v6_o_normal_close_reason_unchanged
#   V6-P test_v6_p_empty_reason_reconcile_uncertain_no_side_effects
#
# Инварианты:
#   - первоначальный timestamp SELL переживает поздний reconcile,
#     перезапуск и восстановление без перезаписи;
#   - новый cursor проходит проверку только при ПОЛНОМ наборе
#     обязательных идентификаторов; legacy — по отдельной политике;
#   - конфликтная задача после перезапуска не разблокируется и не
#     опрашивает брокера;
#   - пустой close_reason не роняет reconcile и не создаёт новых типов
#     закрытия.
#
# Запуск из корня репозитория: pytest test_b2_v6_timestamp_identity_close_reason.py -v
# ТОЛЬКО fake-объекты: без сети, токенов, реального брокера и заявок.
# RESEARCH ONLY / NO LIVE ORDERS / SANDBOX.

import asyncio
import copy
import csv
import json
import os
import sys

from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import logger as research_logger
import order_ledger as order_ledger_mod
from order_ledger import OrderLedger
from execution import ExecutionMonitor, PositionState, TrackedPosition

_IMPORT_ERROR = None


def _install_sdk_stubs():
    """Минимальные заглушки t_tech.invest / telegram_bot (как в
    test_b2_v5_identity_and_timestamp.py) — нужны только для import main."""
    import types

    class _EnumVal:
        def __init__(self, name):
            self.name = name
            self.value = name

    invest = types.ModuleType("t_tech.invest")
    invest.CandleInterval = types.SimpleNamespace(
        CANDLE_INTERVAL_5_MIN=_EnumVal("5min"))
    invest.OrderDirection = types.SimpleNamespace(
        ORDER_DIRECTION_BUY=_EnumVal("BUY"),
        ORDER_DIRECTION_SELL=_EnumVal("SELL"))
    invest.OrderExecutionReportStatus = types.SimpleNamespace(
        EXECUTION_REPORT_STATUS_FILL=_EnumVal("FILL"),
        EXECUTION_REPORT_STATUS_PARTIALLYFILL=_EnumVal("PARTIALLYFILL"),
        EXECUTION_REPORT_STATUS_NEW=_EnumVal("NEW"),
        EXECUTION_REPORT_STATUS_CANCELLED=_EnumVal("CANCELLED"),
        EXECUTION_REPORT_STATUS_REJECTED=_EnumVal("REJECTED"),
        EXECUTION_REPORT_STATUS_EXPIRED=_EnumVal("EXPIRED"))
    ttech = types.ModuleType("t_tech")
    ttech.invest = invest
    telegram_bot = types.ModuleType("telegram_bot")
    telegram_bot.TelegramBot = object

    sys.modules.setdefault("t_tech", ttech)
    sys.modules.setdefault("t_tech.invest", invest)
    sys.modules.setdefault("telegram_bot", telegram_bot)


try:
    import main
except Exception as exc:  # noqa: BLE001
    _INSTALL_ERROR = exc
    _install_sdk_stubs()
    try:
        import main  # noqa: F811
        _IMPORT_ERROR = None
    except Exception as exc2:  # noqa: BLE001
        _IMPORT_ERROR = exc2
else:
    _IMPORT_ERROR = None

pytestmark = pytest.mark.skipif(
    _IMPORT_ERROR is not None,
    reason=f"main.py недоступен: {_IMPORT_ERROR}",
)


@pytest.fixture()
def isolated_paths(tmp_path, monkeypatch):
    """Все файловые записи тестов — в tmp_path (не трогаем рабочие файлы)."""
    monkeypatch.setattr(research_logger, "EVENTS_FILE",
                        str(tmp_path / "research_events.jsonl"))
    monkeypatch.setattr(research_logger, "TRADES_FILE",
                        str(tmp_path / "research_trades.csv"))
    monkeypatch.setattr(main, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(main, "STATE_FILE_TMP", str(tmp_path / "state.json.tmp"))
    monkeypatch.setattr(main, "_external_close_candidates", {})
    yield tmp_path


# ===========================================================================
# Инфраструктура (fake-клиент/отчёты — как в test_b2_v5_identity_and_timestamp)
# ===========================================================================

class _MV:
    """MoneyValue/Quotation-заглушка (units + nano)."""

    def __init__(self, units, nano=0):
        self.units = units
        self.nano = nano


class FakeState:
    """Отчёт заявки брокера (FILL=1, CANCELLED=3). executed_order_price —
    денежная СУММА исполнения: цена = price_units / (lots_executed * lot)."""

    def __init__(self, status_code=3, lots_executed=10, price_units=None,
                 commission=None, lot=1):
        self.execution_report_status = status_code
        self.lots_executed = lots_executed
        self.executed_order_price = (
            _MV(price_units) if price_units is not None else None)
        if commission is None or isinstance(commission, _MV):
            self.executed_commission = commission
        else:
            units = int(commission)
            nano = int(round((float(commission) - units) * 1e9))
            self.executed_commission = _MV(units, nano)


class FakeClient:
    """Fake-клиент: get_sandbox_order_state возвращает отчёт по ключу
    order_id (dict order_states) либо общий отчёт. Без сети; фиксирует
    вызовы (state_calls) — используется для проверки «опроса не было».
    Торговые методы (post_market_order/cancel_order) ТОЛЬКО фиксируются —
    используется для проверки «побочных торговых действий не было»."""

    def __init__(self, order_state=None, order_states=None, lot=1):
        self._order_state = order_state
        self._order_states = order_states or {}
        self._lot = lot
        self.state_calls = []
        self.orders = []
        self.cancels = []
        self.uncertain_state = False

    async def get_sandbox_order_state(self, oid, order_id_type=None):
        self.state_calls.append((str(oid), order_id_type))
        if str(oid) in self._order_states:
            return self._order_states[str(oid)]
        return self._order_state

    async def get_instrument_info(self, figi):
        return {"lot": self._lot}

    async def get_last_prices(self, figis):
        return []

    async def get_positions(self):
        return {}

    async def post_market_order(self, figi, quantity, direction, order_id=None):
        self.orders.append((figi, quantity, direction, order_id))
        raise AssertionError("торговое действие запрещено в тесте (fake)")

    async def cancel_order(self, order_id, order_id_type=None):
        self.cancels.append((str(order_id), order_id_type))
        raise AssertionError("отмена заявки запрещена в тесте (fake)")


class FakeLostClient:
    """Fake-клиент, у которого post_market_order ТЕРЯЕТ ответ брокера:
    result.state is None (сетевая ошибка после отправки SELL)."""

    def __init__(self):
        self.orders = []
        self.uncertain_state = False

    async def post_market_order(self, figi, quantity, direction, order_id=None):
        self.orders.append((figi, quantity, direction, order_id))

        class _Result:
            state = None
            error = "connection lost"
            exchange_order_id = None

        return _Result()


class _Clock:
    """Управляемые детерминированные часы: main.datetime.now() И
    order_ledger.utc_now_iso() (timestamps записей реестра). Позволяет
    отличить СОХРАНЁННЫЙ timestamp (время запроса SELL) от времени
    восстановления/синхронизации реестра и от времени текущего запуска.
    Никаких sleep."""

    def __init__(self):
        self._fixed = None

    def set(self, iso):
        self._fixed = iso

    def install(self, monkeypatch):
        clock = self

        class _FixedDT(datetime):
            @classmethod
            def now(cls, tz=None):
                if clock._fixed is None:
                    return datetime.now(tz)
                dt = datetime.fromisoformat(clock._fixed)
                return dt if tz is None else dt.astimezone(tz)

        monkeypatch.setattr(main, "datetime", _FixedDT)

        def _fixed_now_iso():
            if clock._fixed is None:
                return datetime.now(timezone.utc).isoformat()
            return clock._fixed

        # order_ledger.append() берёт utc_now_iso из СВОЕГО модуля:
        monkeypatch.setattr(order_ledger_mod, "utc_now_iso", _fixed_now_iso)
        return _FixedDT


@pytest.fixture()
def clock(monkeypatch):
    c = _Clock()
    c.install(monkeypatch)
    c.set("2026-11-20T12:00:00+00:00")
    return c


def run(coro):
    return asyncio.run(coro)


def read_trades_csv(subdir):
    path = subdir / "research_trades.csv"
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def read_trades_bytes(subdir):
    path = subdir / "research_trades.csv"
    if not os.path.isfile(path):
        return b""
    with open(path, "rb") as f:
        return f.read()


def read_events(subdir):
    path = subdir / "research_events.jsonl"
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line for line in f.read().splitlines() if line.strip()]


def events_of(subdir):
    parsed = []
    for line in read_events(subdir):
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return parsed


# ===========================================================================
# Единые конструкторы сценариев
# ===========================================================================

ENTRY = 100.0
LOTS = 10

# Фиксированные времена (детерминированные):
T_0900 = "2026-11-20T09:00:00+00:00"
T_0905 = "2026-11-20T09:05:00+00:00"   # время ЗАПРОСА SELL
T_1000 = "2026-11-20T10:00:00+00:00"
T_1005 = "2026-11-20T10:05:00+00:00"
T_1010 = "2026-11-20T10:10:00+00:00"
T_1015 = "2026-11-20T10:15:00+00:00"   # момент ЗАПИСИ строки CSV (legacy)
T_1020 = "2026-11-20T10:20:00+00:00"   # время ПОЗДНЕГО восстановления
T_1021 = "2026-11-20T10:21:00+00:00"
T_1022 = "2026-11-20T10:22:00+00:00"


def make_open_position(monitor, figi, trade_id, ticker="TEST",
                       entry_price=ENTRY, lots=LOTS):
    """OPEN-позиция в monitor.positions (как до вызова close_position)."""
    pos = TrackedPosition(
        figi=figi, ticker=ticker, direction="BUY", entry_price=entry_price,
        quantity=lots, sl_price=entry_price * 0.98, tp_price=entry_price * 1.04,
        lot_size=1, state=PositionState.OPEN, trade_id=trade_id,
        price_before_order=entry_price, close_price_before_order=entry_price,
        order_send_time=T_0900,
    )
    monitor.positions[figi] = pos
    return pos


def fresh_ledger(tmp_path):
    ledger = OrderLedger(str(tmp_path / "order_ledger.jsonl"))
    ledger.load()
    return ledger


def make_b2_ledger_case(tmp_path, clock, pos, oid, *, requested,
                        reason, intent_at, late_status="NEW",
                        late_at=None):
    """Реестр заявок для ветки В2: INTENT СВОЕЙ SELL-заявки в intent_at
    (reason = причина закрытия из close_position) + поздний нетерминальный
    статус late_status в late_at — updated_at_utc записи = late_at
    (время ПОЗДНЕЙ синхронизации реестра, как после перезапуска робота).
    Позиция получает ссылку на СВОЮ заявку (close_order_request_id)."""
    ledger = fresh_ledger(tmp_path)
    clock.set(intent_at)
    assert ledger.record_intent(
        oid, trade_id=pos.trade_id, figi=pos.figi, ticker=pos.ticker,
        side="SELL", requested_lots=requested, reason=reason)
    if late_at is not None and late_status is not None:
        clock.set(late_at)
        # Причина close:* сопровождает запись СВОЕЙ заявки и в
        # production-пути переносится при последующих статусах
        # (resolve_closing/_try_resolve_absent_position передают
        # reason=prev_reason) — повторяем это поведение:
        assert ledger.record_status(oid, late_status, reason=reason)
    pos.close_order_request_id = oid
    pos.close_requested_lots = requested
    return ledger


def make_closed_logged_at(subdir, *, trade_id, figi, oid,
                          close_at, price, commission,
                          entry_price=ENTRY, close_before=ENTRY,
                          entry_actual=None, lots=LOTS):
    """Позиция BUY, закрытая ПОЛНЫМ исполнением своей SELL-заявки
    (cumulative == requested -> CLOSED), CSV-строка записана штатным
    process_closing (logged=True). close_at — авторитетное время закрытия
    (close_requested_at), попадает в exit_time CSV-строки."""
    monitor = ExecutionMonitor(FakeClient())
    pos = TrackedPosition(
        figi=figi, ticker="TEST", direction="BUY", entry_price=entry_price,
        quantity=lots, sl_price=entry_price * 0.98,
        tp_price=entry_price * 1.04, lot_size=1,
        state=PositionState.OPEN, trade_id=trade_id,
        price_before_order=entry_price, close_price_before_order=close_before,
        order_send_time=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        entry_actual_commission=entry_actual,
    )
    monitor.positions[pos.figi] = pos
    monitor.add_close_order(pos, oid, lots)
    pos.close_order_request_id = oid
    pos.close_requested_lots = lots
    pos.close_requested_at = close_at
    assert monitor.apply_close_execution(
        pos, oid, lots, "CANCELLED",
        execution_price=price, commission=commission,
        requested_lots=lots) is True
    assert pos.state == PositionState.CLOSED
    assert pos.quantity == 0
    client = FakeClient(order_states={
        oid: FakeState(status_code=3, lots_executed=lots,
                       price_units=((price * lots) if price is not None else None),
                       commission=commission),
    })
    rows_before = read_trades_csv(subdir)
    run(main.process_closing(client, monitor, None))
    rows = read_trades_csv(subdir)
    assert len(rows) == len(rows_before) + 1, \
        "исходная CSV-строка должна быть дописана ровно одна"
    new_row = rows[-1]
    assert new_row["trade_id"] == trade_id
    assert pos.logged is True
    assert new_row["exit_time"] == close_at, \
        "exit_time = авторитетное время закрытия (close_requested_at)"
    return monitor, pos, client


def register_new_position(monitor, figi, trade_id, ticker="TEST",
                          entry_price=ENTRY, lots=LOTS):
    """Регистрация НОВОЙ позиции по тому же FIGI (замена CLOSED-записи;
    прежняя сделка архивируется в pending_csv_recoveries)."""
    return monitor.register(
        figi=figi, ticker=ticker, direction="BUY",
        entry_price=entry_price, quantity=lots,
        sl_price=entry_price * 0.98, tp_price=entry_price * 1.04,
        lot_size=1, state=PositionState.OPEN, trade_id=trade_id,
        signal_reason="v6-test", signal_time=T_0900,
    )


def restart(tmp_path, monitor):
    """Имитация перезапуска: _save_state -> state.json -> _load_state."""
    rm = main.RiskManager(FakeClient())
    assert main._save_state(monitor, rm) is True
    monitor2 = ExecutionMonitor(FakeClient())
    rm2 = main.RiskManager(FakeClient())
    assert main._load_state(monitor2, rm2) is True
    return monitor2


def close_lost_response(clock, monitor, pos, request_at, monkeypatch):
    """close_position() при ПОТЕРЯННОМ ответе брокера (result.state=None)
    в управляемое время request_at; monitor_ref/ledger_ref подставлены.
    Возвращает fake-клиент."""
    monkeypatch.setattr(main, "monitor_ref", monitor)
    monkeypatch.setattr(main, "ledger_ref", None)
    clock.set(request_at)
    lost = FakeLostClient()
    run(main.close_position(lost, pos, ENTRY))
    assert pos.state == PositionState.UNCERTAIN
    assert pos.close_order_request_id
    return lost


def make_recovery_case(tmp_path, trade_id, oid):
    """CSV-строка закрытой сделки (без цены/комиссии) + recovery-задача
    (позиция заменена новой позицией того же FIGI). Возвращает
    (monitor, task)."""
    monitor, _pos1, _client = make_closed_logged_at(
        tmp_path, trade_id=trade_id, figi="F1", oid=oid,
        close_at=T_1000, price=None, commission=None)
    register_new_position(monitor, "F1", trade_id + "-n")
    assert len(monitor.pending_csv_recoveries) == 1
    task = monitor.pending_csv_recoveries[0]
    assert task["trade_id"] == trade_id
    return monitor, task


def terminal_report(price=110.0, commission=1.5, lots=LOTS):
    return FakeState(status_code=3, lots_executed=lots,
                     price_units=price * lots, commission=commission)


# ===========================================================================
# ТЕСТ V6-A. Основной сценарий: первоначальный timestamp SELL (09:05) НЕ
# перезаписывается временем позднего B2 reconcile (updated_at_utc = 10:20)
# ===========================================================================

def test_v6_a_reconcile_keeps_initial_request_timestamp(isolated_paths, clock,
                                                        monkeypatch):
    """SELL отправлена в 09:05, ответ брокера потерян, первоначальное время
    сохранено в close cursor; робот перезапускается; в 10:20 B2 reconcile
    восстанавливает состояние заявки (updated_at_utc записи реестра = 10:20).
    Итоговый close_requested_at ОСТАЁТСЯ 09:05; CSV exit_time = 09:05,
    а не 10:20."""
    tmp_path = isolated_paths
    monitor = ExecutionMonitor(FakeClient())
    pos = make_open_position(monitor, "F1", "t-v6a")
    pos.close_reason = "STOP_LOSS"

    # --- SELL при 09:05, ответ потерян; timestamp сохранён ДО отправки ---
    lost = close_lost_response(clock, monitor, pos, T_0905, monkeypatch)
    req_id = pos.close_order_request_id
    assert pos.close_requested_at == T_0905
    assert pos.close_orders[req_id]["requested_at"] == T_0905
    assert lost.orders[0][3] == req_id

    # --- Перезапуск робота ---
    monitor2 = restart(tmp_path, monitor)
    pos_r = monitor2.positions["F1"]
    assert pos_r.close_requested_at == T_0905

    # --- Реестр: INTENT 09:05, поздняя синхронизация статуса 10:20
    #     (updated_at_utc = 10:20 — время ВОССТАНОВЛЕНИЯ, не запроса) ---
    ledger = make_b2_ledger_case(
        tmp_path, clock, pos_r, req_id, requested=LOTS,
        reason="close:STOP_LOSS", intent_at=T_0905, late_status="NEW",
        late_at=T_1020)
    assert ledger.latest(req_id)["updated_at_utc"] == T_1020
    assert ledger.latest(req_id)["created_at_utc"] == T_0905

    # --- B2 reconcile в 10:20 восстанавливает закрытие по отчёту ---
    clock.set(T_1020)
    client = FakeClient(order_state=terminal_report())
    action = run(main._try_resolve_absent_position(client, ledger, pos_r, monitor2))
    assert action == "ledger_close"
    assert pos_r.state == PositionState.CLOSED

    # ГЛАВНОЕ: первоначальный timestamp НЕ перезаписан временем
    # восстановления (10:20) и не временем запуска:
    assert pos_r.close_requested_at == T_0905, \
        "close_requested_at = первоначальное время запроса SELL (неизменяемый факт)"
    assert pos_r.close_requested_at != T_1020
    assert pos_r.close_requested_at == pos_r.close_orders[req_id]["requested_at"]

    # --- CSV: exit_time соответствует 09:05, а не 10:20 ---
    run(main.process_closing(FakeClient(), monitor2, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["trade_id"] == "t-v6a"
    assert row["exit_time"] == T_0905
    assert row["timestamp_utc"] == T_0905
    assert row["exit_time"] != T_1020
    assert row["exit_price"] == f"{110.0:.4f}"


# ===========================================================================
# ТЕСТ V6-B. Timestamp отсутствует в позиции (close_requested_at=None),
# собственный close cursor содержит requested_at=09:05, ledger содержит
# updated_at_utc=10:20 -> после восстановления используется 09:05
# ===========================================================================

def test_v6_b_missing_position_ts_restored_from_own_cursor(isolated_paths,
                                                           clock):
    """Легаси-позиция (старый state.json): close_requested_at отсутствует,
    но СВОЙ per-order cursor содержит requested_at. При восстановлении
    через B2 reconcile используется 09:05 (cursor), а НЕ updated_at_utc
    реестра (10:20) и не время текущего запуска."""
    tmp_path = isolated_paths
    monitor = ExecutionMonitor(FakeClient())
    pos = make_open_position(monitor, "F1", "t-v6b")
    # cursor создан с известным временем запроса; в позиции timestamp
    # ОТСУТСТВУЕТ (старый state.json):
    monitor.add_close_order(pos, "sell-b6", LOTS, requested_at=T_0905)
    pos.close_order_request_id = "sell-b6"
    pos.close_requested_lots = LOTS
    pos.close_requested_at = None

    # --- Перезапуск: в state.json close_requested_at = null ---
    monitor2 = restart(tmp_path, monitor)
    pos_r = monitor2.positions["F1"]
    assert not pos_r.close_requested_at
    assert pos_r.close_orders["sell-b6"]["requested_at"] == T_0905

    # --- Реестр: поздняя синхронизация 10:20 ---
    ledger = make_b2_ledger_case(
        tmp_path, clock, pos_r, "sell-b6", requested=LOTS,
        reason="close:STOP_LOSS", intent_at=T_0905, late_status="NEW",
        late_at=T_1020)
    assert ledger.latest("sell-b6")["updated_at_utc"] == T_1020

    # --- B2 reconcile в 10:20 ---
    clock.set(T_1020)
    client = FakeClient(order_state=terminal_report())
    action = run(main._try_resolve_absent_position(client, ledger, pos_r, monitor2))
    assert action == "ledger_close"
    assert pos_r.state == PositionState.CLOSED

    # Использован timestamp СОБСТВЕННОГО cursor'а (09:05):
    assert pos_r.close_requested_at == T_0905
    assert pos_r.close_requested_at != T_1020

    run(main.process_closing(FakeClient(), monitor2, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    assert rows[0]["exit_time"] == T_0905
    assert rows[0]["timestamp_utc"] == T_0905
    assert rows[0]["exit_time"] != T_1020


# ===========================================================================
# ТЕСТ V6-C. Timestamp отсутствует и в позиции, и в cursor: никакое
# достоверное историческое время не выдумывается (None; datetime.now()
# не подставляется внутрь восстановления); legacy-политика явно обозначена
# и применяется ТОЛЬКО на записи CSV
# ===========================================================================

def test_v6_c_no_historical_ts_left_absent_legacy_policy(isolated_paths,
                                                         clock):
    """Нет достоверного исторического времени (ни в позиции, ни в cursor).
    После B2 reconcile close_requested_at ОСТАЁТСЯ None — никакой
    timestamp от другой заявки не используется, datetime.now() внутрь
    функции восстановления не подставляется. Явно обозначенная
    legacy-политика проекта (момент записи строки CSV) применяется
    ОТДЕЛЬНО — на записи trade_row."""
    tmp_path = isolated_paths
    monitor = ExecutionMonitor(FakeClient())
    pos = make_open_position(monitor, "F1", "t-v6c")
    # cursor БЕЗ requested_at (старый формат/потеря), timestamp позиции
    # отсутствует:
    monitor.add_close_order(pos, "sell-c6", LOTS)
    pos.close_order_request_id = "sell-c6"
    pos.close_requested_lots = LOTS
    pos.close_requested_at = None
    assert pos.close_orders["sell-c6"]["requested_at"] is None

    # --- Реестр: INTENT 09:00, поздняя синхронизация 10:20 ---
    ledger = make_b2_ledger_case(
        tmp_path, clock, pos, "sell-c6", requested=LOTS,
        reason="close:STOP_LOSS", intent_at=T_0900, late_status="NEW",
        late_at=T_1020)
    assert ledger.latest("sell-c6")["updated_at_utc"] == T_1020

    # --- B2 reconcile в 10:10 (время восстановления != 10:20 реестра) ---
    clock.set(T_1010)
    client = FakeClient(order_state=terminal_report())
    action = run(main._try_resolve_absent_position(client, ledger, pos, monitor))
    assert action == "ledger_close"
    assert pos.state == PositionState.CLOSED

    # Исторического времени нет — оно НЕ выдумано внутрь восстановления:
    assert pos.close_requested_at is None, \
        "без достоверного исторического времени close_requested_at остаётся None"
    assert pos.close_requested_at != T_1010, \
        "datetime.now() времени восстановления НЕ подставляется"
    assert pos.close_requested_at != T_1020, \
        "updated_at_utc реестра НЕ подставляется"

    # --- ЯВНО обозначенная legacy-политика: на записи CSV (в 10:15) ---
    clock.set(T_1015)
    run(main.process_closing(FakeClient(), monitor, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    # Момент записи строки — единственная доступная оценка, применяется
    # ТОЛЬКО в месте записи trade_row (не скрытая подстановка):
    assert row["exit_time"] == T_1015
    assert row["exit_time"] != T_1010 and row["exit_time"] != T_1020
    # timestamp_utc без сохранённого времени остаётся ПУСТЫМ — подстановка
    # не выдаётся за сохранённое время:
    assert row["timestamp_utc"] == ""


# ===========================================================================
# ТЕСТ V6-D. Конфликт идентификаторов: две сделки ОДНОГО FIGI с разными
# trade_id и close order IDs; восстановление одной сделки не берёт
# timestamp второй; неоднозначная привязка — fail-closed
# ===========================================================================

def test_v6_d_cross_trade_timestamp_isolated_and_fail_closed(isolated_paths,
                                                             clock):
    """(a) У позиции ссылка на СВОЮ заявку sell-d1, но в close_orders лежит
    только cursor ЧУЖОЙ сделки того же FIGI (sell-d2, другой trade_id,
    requested_at=10:05) — timestamp чужой сделки НЕ используется.
    (b) Recovery-задача сделки t-v6d2, в снимке которой cursor ДРУГОЙ
    сделки того же FIGI (другой trade_id / другой close order ID) —
    fail-closed: брокер не опрашивается, CSV (включая exit_time чужой
    сделки) не изменяется, задача не завершается."""
    tmp_path = isolated_paths

    # --- (a) timestamp другой сделки не используется ---
    monitor = ExecutionMonitor(FakeClient())
    pos = make_open_position(monitor, "F1", "t-v6d")
    pos.close_order_request_id = "sell-d1"
    pos.close_requested_lots = LOTS
    pos.close_requested_at = None
    foreign_cursor = {
        "order_id": "sell-d2", "trade_id": "t-v6d-other", "figi": "F1",
        "side": "SELL", "requested_lots": LOTS,
        "confirmed_executed_lots": LOTS, "applied_lots": LOTS,
        "status": "CANCELLED", "requested_at": T_1005,
        "avg_exec_price": None, "commission": None,
    }
    pos.close_orders["sell-d2"] = foreign_cursor
    # Прямая проверка: восстановление не берёт timestamp чужой заявки:
    assert main._restore_close_requested_at(pos, "sell-d1") is None

    ledger = make_b2_ledger_case(
        tmp_path, clock, pos, "sell-d1", requested=LOTS,
        reason="close:STOP_LOSS", intent_at=T_0905, late_status="NEW",
        late_at=T_1020)
    clock.set(T_1020)
    client = FakeClient(order_state=terminal_report())
    action = run(main._try_resolve_absent_position(client, ledger, pos, monitor))
    assert action == "ledger_close"
    # Чужой timestamp (10:05) и время восстановления (10:20) не подставлены:
    assert pos.close_requested_at is None
    assert pos.close_requested_at != T_1005 and pos.close_requested_at != T_1020

    # --- (b) recovery-задача с cursor'ом другой сделки — fail-closed ---
    monitor_b, task = make_recovery_case(tmp_path, "t-v6d2", "sell-d1b")
    snap_cursor = task["position"]["close_orders"]["sell-d1b"]
    # Контаминация между сделками одного FIGI: cursor выдаёт себя за
    # заявку ДРУГОЙ сделки (другой trade_id, другой close order ID):
    snap_cursor["trade_id"] = "t-v6d-other"
    snap_cursor["requested_at"] = T_1005
    assert ExecutionMonitor.validate_recovery_identity(task) == \
        "cursor_trade_id_mismatch"

    monitor_b2 = restart(tmp_path, monitor_b)
    tasks = monitor_b2.pending_csv_recoveries
    assert len(tasks) == 1, "задача НЕ удаляется как успешно завершённая"
    assert tasks[0].get("conflict") == "cursor_trade_id_mismatch"

    bytes_before = read_trades_bytes(tmp_path)
    clock.set(T_1021)
    client_b = FakeClient(order_states={
        "sell-d1b": terminal_report(),
    })
    run(main.process_closing(client_b, monitor_b2, None))
    assert client_b.state_calls == [], \
        "чужая заявка и неоднозначная привязка не опрашиваются (fail-closed)"
    assert read_trades_bytes(tmp_path) == bytes_before, "CSV не изменён"
    assert len(monitor_b2.pending_csv_recoveries) == 1
    # exit_time строки сделки t-v6d2 остаётся её собственным временем
    # закрытия (10:00), а не timestamp'ом другой сделки (10:05):
    rows = read_trades_csv(tmp_path)
    by_id = {r["trade_id"]: r for r in rows}
    assert by_id["t-v6d2"]["exit_time"] == T_1000


# ===========================================================================
# ТЕСТ V6-E. Новый cursor (identity_version) без trade_id -> fail-closed
# ===========================================================================

def test_v6_e_new_cursor_missing_trade_id_fail_closed(isolated_paths, clock):
    """Новый формат cursor'а без обязательного trade_id: проверка не
    пропускает пустое обязательное поле (cursor_missing_trade_id),
    брокер не опрашивается, CSV не изменяется, задача остаётся."""
    tmp_path = isolated_paths
    monitor, task = make_recovery_case(tmp_path, "t-v6e", "sell-e6")
    snap_cursor = task["position"]["close_orders"]["sell-e6"]
    assert ExecutionMonitor._cursor_is_new_format(snap_cursor) is True
    del snap_cursor["trade_id"]  # обязательное поле ОТСУТСТВУЕТ
    assert ExecutionMonitor.validate_recovery_identity(task) == \
        "cursor_missing_trade_id"

    monitor2 = restart(tmp_path, monitor)
    assert len(monitor2.pending_csv_recoveries) == 1
    assert monitor2.pending_csv_recoveries[0].get("conflict") == \
        "cursor_missing_trade_id"

    bytes_before = read_trades_bytes(tmp_path)
    clock.set(T_1020)
    client = FakeClient(order_states={"sell-e6": terminal_report()})
    run(main.process_closing(client, monitor2, None))
    assert client.state_calls == [], "брокер НЕ опрашивается (fail-closed)"
    assert read_trades_bytes(tmp_path) == bytes_before, "CSV не изменён"
    assert len(monitor2.pending_csv_recoveries) == 1
    events = events_of(tmp_path)
    assert any(e.get("reason") == "cursor_missing_trade_id"
               for e in events
               if e.get("event") == "CSV_RECOVERY_TASK_CONFLICT"
               or e.get("type") == "CSV_RECOVERY_TASK_CONFLICT")


# ===========================================================================
# ТЕСТ V6-F. Новый cursor без FIGI (пустое значение) -> fail-closed
# ===========================================================================

def test_v6_f_new_cursor_missing_figi_fail_closed(isolated_paths, clock):
    """Новый формат cursor'а с ПУСТЫМ обязательным FIGI: молчаливого
    пропуска нет (cursor_missing_figi), задача блокируется целиком."""
    tmp_path = isolated_paths
    monitor, task = make_recovery_case(tmp_path, "t-v6f", "sell-f6")
    snap_cursor = task["position"]["close_orders"]["sell-f6"]
    snap_cursor["figi"] = ""  # обязательное поле ПУСТОЕ
    assert ExecutionMonitor.validate_recovery_identity(task) == \
        "cursor_missing_figi"

    monitor2 = restart(tmp_path, monitor)
    assert len(monitor2.pending_csv_recoveries) == 1
    assert monitor2.pending_csv_recoveries[0].get("conflict") == \
        "cursor_missing_figi"

    bytes_before = read_trades_bytes(tmp_path)
    clock.set(T_1020)
    client = FakeClient(order_states={"sell-f6": terminal_report()})
    run(main.process_closing(client, monitor2, None))
    assert client.state_calls == []
    assert read_trades_bytes(tmp_path) == bytes_before
    assert len(monitor2.pending_csv_recoveries) == 1


# ===========================================================================
# ТЕСТ V6-G. Новый cursor без side -> fail-closed
# ===========================================================================

def test_v6_g_new_cursor_missing_side_fail_closed(isolated_paths, clock):
    """Новый формат cursor'а без обязательного side: конфликт
    cursor_missing_side, восстановления нет."""
    tmp_path = isolated_paths
    monitor, task = make_recovery_case(tmp_path, "t-v6g", "sell-g6")
    snap_cursor = task["position"]["close_orders"]["sell-g6"]
    del snap_cursor["side"]  # обязательное поле ОТСУТСТВУЕТ
    assert ExecutionMonitor.validate_recovery_identity(task) == \
        "cursor_missing_side"

    monitor2 = restart(tmp_path, monitor)
    assert len(monitor2.pending_csv_recoveries) == 1
    assert monitor2.pending_csv_recoveries[0].get("conflict") == \
        "cursor_missing_side"

    bytes_before = read_trades_bytes(tmp_path)
    clock.set(T_1020)
    client = FakeClient(order_states={"sell-g6": terminal_report()})
    run(main.process_closing(client, monitor2, None))
    assert client.state_calls == []
    assert read_trades_bytes(tmp_path) == bytes_before
    assert len(monitor2.pending_csv_recoveries) == 1


# ===========================================================================
# ТЕСТ V6-H. Новый cursor с неправильным trade_id / FIGI / side / order_id
# -> fail-closed (каждое противоречие распознаётся отдельно)
# ===========================================================================

def test_v6_h_new_cursor_wrong_identity_fail_closed(isolated_paths, clock):
    """Новый формат cursor'а с НЕПРАВИЛЬНЫМИ значениями обязательных
    идентификаторов: каждое противоречие снимку распознаётся отдельно
    (cursor_trade_id_mismatch / cursor_figi_mismatch /
    cursor_side_mismatch / cursor_order_id_mismatch) — ни один
    идентификатор не подменяет другой только потому, что все они строки."""
    tmp_path = isolated_paths
    monitor, task = make_recovery_case(tmp_path, "t-v6h", "sell-h6")
    snap_cursor = task["position"]["close_orders"]["sell-h6"]

    def validated(mutations):
        cur = copy.deepcopy(snap_cursor)
        cur.update(mutations)
        probe = copy.deepcopy(task)
        probe["position"]["close_orders"]["sell-h6"] = cur
        return ExecutionMonitor.validate_recovery_identity(probe)

    # Неправильный trade_id:
    assert validated({"trade_id": "t-foreign"}) == "cursor_trade_id_mismatch"
    # Неправильный FIGI:
    assert validated({"figi": "F9"}) == "cursor_figi_mismatch"
    # Неправильная сторона (BUY вместо SELL закрытия BUY-позиции):
    assert validated({"side": "BUY"}) == "cursor_side_mismatch"
    # Идентификатор собственной заявки не совпадает с ключом close_orders
    # (клиентский UUID не подменяет биржевой ID и наоборот):
    assert validated({"order_id": "sell-FOREIGN"}) == "cursor_order_id_mismatch"

    # Основной вариант (все «чужие») -> fail-closed через перезапуск:
    snap_cursor["trade_id"] = "t-foreign"
    snap_cursor["figi"] = "F9"
    snap_cursor["side"] = "BUY"
    assert ExecutionMonitor.validate_recovery_identity(task) == \
        "cursor_trade_id_mismatch"
    monitor2 = restart(tmp_path, monitor)
    assert len(monitor2.pending_csv_recoveries) == 1
    assert monitor2.pending_csv_recoveries[0].get("conflict") == \
        "cursor_trade_id_mismatch"

    bytes_before = read_trades_bytes(tmp_path)
    clock.set(T_1020)
    client = FakeClient(order_states={"sell-h6": terminal_report()})
    run(main.process_closing(client, monitor2, None))
    assert client.state_calls == []
    assert read_trades_bytes(tmp_path) == bytes_before
    assert len(monitor2.pending_csv_recoveries) == 1


# ===========================================================================
# ТЕСТ V6-I. Корректный НОВЫЙ cursor -> штатное восстановление (без
# ложных блокировок)
# ===========================================================================

def test_v6_i_valid_new_cursor_recovery_completes(isolated_paths, clock):
    """Новый формат cursor'а с ПОЛНЫМ набором идентификаторов (trade_id,
    FIGI, side, order_id, связь с close-заявкой): задача проходит
    проверку (cursor_validation='full') и штатно восстанавливает CSV
    (цена + фактическая комиссия), после чего завершается."""
    tmp_path = isolated_paths
    monitor, task = make_recovery_case(tmp_path, "t-v6i", "sell-i6")
    snap_cursor = task["position"]["close_orders"]["sell-i6"]
    # Новый формат: все обязательные идентификаторы на месте и согласованы:
    assert ExecutionMonitor._cursor_is_new_format(snap_cursor) is True
    assert snap_cursor["trade_id"] == "t-v6i"
    assert snap_cursor["figi"] == "F1"
    assert snap_cursor["side"] == "SELL"
    assert snap_cursor["order_id"] == "sell-i6"
    assert ExecutionMonitor.validate_recovery_identity(task) is None

    monitor2 = restart(tmp_path, monitor)
    tasks = monitor2.pending_csv_recoveries
    assert len(tasks) == 1
    assert tasks[0].get("conflict") is None
    assert tasks[0].get("cursor_validation") == "full"

    clock.set(T_1020)
    run(main.process_closing(
        FakeClient(order_states={"sell-i6": terminal_report()}), monitor2, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["trade_id"] == "t-v6i"
    assert row["exit_price"] == f"{110.0:.4f}"
    assert row["actual_commission_rub"] == "1.50"
    # exit_time НЕ перезаписан восстановлением (осталось время закрытия):
    assert row["exit_time"] == T_1000
    assert monitor2.pending_csv_recoveries == [], "задача штатно завершена"


# ===========================================================================
# ТЕСТ V6-J. Корректный LEGACY cursor -> штатная legacy-ветка с
# ОГРАНИЧЕННОЙ проверкой (неполнота НЕ выдаётся за полную)
# ===========================================================================

def test_v6_j_valid_legacy_cursor_recovery_completes(isolated_paths, clock):
    """Legacy cursor (старый state.json, без маркера identity_version) со
    всеми ДОСТУПНЫМИ и согласованными идентификаторами: противоречия нет —
    восстановление идёт штатно, но режим проверки явно помечается как
    ОГРАНИЧЕННЫЙ (cursor_validation='legacy_limited'), а не выдаётся за
    полную проверку."""
    tmp_path = isolated_paths
    monitor, task = make_recovery_case(tmp_path, "t-v6j", "sell-j6")
    snap_cursor = task["position"]["close_orders"]["sell-j6"]
    # Старая запись: маркера нового формата нет, остальные идентификаторы
    # доступны и согласованы:
    del snap_cursor["identity_version"]
    assert ExecutionMonitor._cursor_is_new_format(snap_cursor) is False
    assert ExecutionMonitor.validate_recovery_identity(task) is None, \
        "согласованный legacy cursor не блокируется (обратная совместимость)"

    monitor2 = restart(tmp_path, monitor)
    tasks = monitor2.pending_csv_recoveries
    assert len(tasks) == 1
    assert tasks[0].get("conflict") is None
    # Неполная проверка зафиксирована ЯВНО (персистентно в state.json):
    assert tasks[0].get("cursor_validation") == "legacy_limited"
    rm3 = main.RiskManager(FakeClient())
    assert main._save_state(monitor2, rm3) is True
    state_data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state_data["pending_csv_recoveries"][0]["cursor_validation"] == \
        "legacy_limited"

    clock.set(T_1020)
    run(main.process_closing(
        FakeClient(order_states={"sell-j6": terminal_report()}), monitor2, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    assert rows[0]["exit_price"] == f"{110.0:.4f}"
    assert rows[0]["actual_commission_rub"] == "1.50"
    assert monitor2.pending_csv_recoveries == [], "задача штатно завершена"


# ===========================================================================
# ТЕСТ V6-K. LEGACY cursor с противоречащим FIGI или order ID -> fail-closed
# ===========================================================================

def test_v6_k_legacy_cursor_contradiction_fail_closed(isolated_paths, clock):
    """Legacy-политика проверяет ВСЕ доступные идентификаторы: противоречие
    снимку в legacy cursor'е (чужой FIGI или order_id, не совпадающий с
    ключом close_orders) — fail-closed, как и в новом формате."""
    tmp_path = isolated_paths
    # --- вариант 1: противоречащий FIGI ---
    monitor, task = make_recovery_case(tmp_path, "t-v6k", "sell-k6")
    snap_cursor = task["position"]["close_orders"]["sell-k6"]
    del snap_cursor["identity_version"]  # legacy
    snap_cursor["figi"] = "F9"
    assert ExecutionMonitor.validate_recovery_identity(task) == \
        "cursor_figi_mismatch"
    monitor2 = restart(tmp_path, monitor)
    assert len(monitor2.pending_csv_recoveries) == 1
    assert monitor2.pending_csv_recoveries[0].get("conflict") == \
        "cursor_figi_mismatch"
    bytes_before = read_trades_bytes(tmp_path)
    clock.set(T_1020)
    client = FakeClient(order_states={"sell-k6": terminal_report()})
    run(main.process_closing(client, monitor2, None))
    assert client.state_calls == []
    assert read_trades_bytes(tmp_path) == bytes_before
    assert len(monitor2.pending_csv_recoveries) == 1

    # --- вариант 2: order_id, не совпадающий с ключом (подмена типа
    #     идентификатора: клиентский UUID vs биржевой ID) ---
    monitor3, task3 = make_recovery_case(tmp_path, "t-v6k2", "sell-k6b")
    snap_cursor3 = task3["position"]["close_orders"]["sell-k6b"]
    del snap_cursor3["identity_version"]  # legacy
    snap_cursor3["order_id"] = "sell-FOREIGN"
    assert ExecutionMonitor.validate_recovery_identity(task3) == \
        "cursor_order_id_mismatch"


# ===========================================================================
# ТЕСТ V6-L. После перезапуска конфликтная задача ОСТАЁТСЯ заблокированной
# и не начинает опрашивать брокера
# ===========================================================================

def test_v6_l_conflict_task_stays_blocked_after_restart(isolated_paths, clock):
    """Задача, заблокированная при импорте (новый cursor без trade_id),
    переживает повторный перезапуск с тем же маркером конфликта: не
    разблокируется повторной проверкой, не опрашивает брокера, не
    изменяет CSV, не завершается."""
    tmp_path = isolated_paths
    monitor, task = make_recovery_case(tmp_path, "t-v6l", "sell-l6")
    del task["position"]["close_orders"]["sell-l6"]["trade_id"]

    # --- первый перезапуск: конфликт зафиксирован ---
    monitor2 = restart(tmp_path, monitor)
    assert len(monitor2.pending_csv_recoveries) == 1
    assert monitor2.pending_csv_recoveries[0].get("conflict") == \
        "cursor_missing_trade_id"

    # --- второй перезапуск: конфликт ПЕРСИСТЕНТЕН ---
    monitor3 = restart(tmp_path, monitor2)
    tasks = monitor3.pending_csv_recoveries
    assert len(tasks) == 1, "задача не удалена и не «завершена» при импорте"
    assert tasks[0].get("conflict") == "cursor_missing_trade_id", \
        "маркер конфликта персистентен (state.json)"

    bytes_before = read_trades_bytes(tmp_path)
    clock.set(T_1021)
    client = FakeClient(order_states={"sell-l6": terminal_report()})
    run(main.process_closing(client, monitor3, None))
    assert client.state_calls == [], \
        "заблокированная задача не опрашивает брокера после перезапусков"
    assert read_trades_bytes(tmp_path) == bytes_before, "CSV не изменён"
    assert len(monitor3.pending_csv_recoveries) == 1
    assert monitor3.pending_csv_recoveries[0].get("conflict") == \
        "cursor_missing_trade_id"
    events = events_of(tmp_path)
    conflicts = [e for e in events
                 if (e.get("event") == "CSV_RECOVERY_TASK_CONFLICT"
                     or e.get("type") == "CSV_RECOVERY_TASK_CONFLICT")
                 and e.get("reason") == "cursor_missing_trade_id"]
    assert conflicts, "диагностическое событие конфликта записано"


# ===========================================================================
# ТЕСТ V6-M. reason_text="close:", причина неизвестна -> НЕТ IndexError,
# применяется существующий безопасный fallback проекта
# ===========================================================================

def test_v6_m_empty_close_reason_no_indexerror_fallback(isolated_paths, clock):
    """ПУСТАЯ причина в реестре ("close:") при неизвестной прежней причине
    (pos.close_reason=None): никакого IndexError, разрешение В2 завершается
    штатно, применяется существующий безопасный fallback проекта
    ("LEDGER_CLOSE") — новый тип закрытия не придумывается."""
    tmp_path = isolated_paths
    monitor = ExecutionMonitor(FakeClient())
    pos = make_open_position(monitor, "F1", "t-v6m")
    pos.state = PositionState.UNCERTAIN  # достижимый путь: UNCERTAIN-позиция
    pos.close_reason = None              # причина неизвестна
    monitor.add_close_order(pos, "sell-m6", LOTS)
    pos.close_order_request_id = "sell-m6"
    pos.close_requested_lots = LOTS
    pos.close_requested_at = None

    ledger = make_b2_ledger_case(
        tmp_path, clock, pos, "sell-m6", requested=LOTS,
        reason="close:", intent_at=T_0905, late_status="NEW",
        late_at=T_1020)

    clock.set(T_1020)
    client = FakeClient(order_state=terminal_report())
    # До v6 здесь было IndexError: list index out of range:
    action = run(main._try_resolve_absent_position(client, ledger, pos, monitor))
    assert action == "ledger_close"
    assert pos.state == PositionState.CLOSED
    # Существующий безопасный fallback проекта:
    assert pos.close_reason == "LEDGER_CLOSE"
    # Опрос СВОЕЙ заявки с явным типом идентификатора; никаких других
    # обращений (побочных торговых действий нет):
    assert client.state_calls == [("sell-m6", "REQUEST")]
    assert client.orders == []
    assert client.cancels == []


# ===========================================================================
# ТЕСТ V6-N. reason_text="close:", старая причина уже известна — старая
# причина сохраняется
# ===========================================================================

def test_v6_n_empty_close_reason_keeps_known_reason(isolated_paths, clock):
    """ПУСТАЯ причина в реестре ("close:") при ИЗВЕСТНОЙ прежней причине
    позиции (STOP_LOSS): прежняя причина сохраняется, не заменяется на
    fallback и не придумывается заново."""
    tmp_path = isolated_paths
    monitor = ExecutionMonitor(FakeClient())
    pos = make_open_position(monitor, "F1", "t-v6n")
    pos.state = PositionState.UNCERTAIN
    pos.close_reason = "STOP_LOSS"  # прежняя причина известна
    monitor.add_close_order(pos, "sell-n6", LOTS)
    pos.close_order_request_id = "sell-n6"
    pos.close_requested_lots = LOTS
    pos.close_requested_at = None

    ledger = make_b2_ledger_case(
        tmp_path, clock, pos, "sell-n6", requested=LOTS,
        reason="close:", intent_at=T_0905, late_status="NEW",
        late_at=T_1020)

    clock.set(T_1020)
    client = FakeClient(order_state=terminal_report())
    action = run(main._try_resolve_absent_position(client, ledger, pos, monitor))
    assert action == "ledger_close"
    assert pos.state == PositionState.CLOSED
    # Старая известная причина сохранена:
    assert pos.close_reason == "STOP_LOSS"
    run(main.process_closing(FakeClient(), monitor, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    assert rows[0]["exit_reason"] == "STOP_LOSS"


# ===========================================================================
# ТЕСТ V6-O. Обычная причина close:STOP_LOSS обрабатывается ТОЧНО как раньше
# ===========================================================================

def test_v6_o_normal_close_reason_unchanged(isolated_paths, clock):
    """Семантика обычных причин НЕ изменилась: 'close:STOP_LOSS' ->
    STOP_LOSS (как в v1-v5)."""
    tmp_path = isolated_paths
    monitor = ExecutionMonitor(FakeClient())
    pos = make_open_position(monitor, "F1", "t-v6o")
    pos.state = PositionState.UNCERTAIN
    pos.close_reason = None
    monitor.add_close_order(pos, "sell-o6", LOTS)
    pos.close_order_request_id = "sell-o6"
    pos.close_requested_lots = LOTS
    pos.close_requested_at = None

    ledger = make_b2_ledger_case(
        tmp_path, clock, pos, "sell-o6", requested=LOTS,
        reason="close:STOP_LOSS", intent_at=T_0905, late_status="NEW",
        late_at=T_1020)

    clock.set(T_1020)
    client = FakeClient(order_state=terminal_report())
    action = run(main._try_resolve_absent_position(client, ledger, pos, monitor))
    assert action == "ledger_close"
    assert pos.close_reason == "STOP_LOSS"
    run(main.process_closing(FakeClient(), monitor, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    assert rows[0]["exit_reason"] == "STOP_LOSS"


# ===========================================================================
# ТЕСТ V6-P. Пустая причина в РЕАЛЬНОМ пути reconcile для UNCERTAIN-позиции:
# сценарий завершается без исключения и без побочных торговых действий
# ===========================================================================

def test_v6_p_empty_reason_reconcile_uncertain_no_side_effects(isolated_paths,
                                                               clock):
    """Полный reconcile: UNCERTAIN-позиция, отсутствующая у брокера, со
    СВОЕЙ close-заявкой и ПУСТОЙ причиной ("close:"). Сценарий завершается
    без исключения: закрытие по терминальному отчёту СВОЕЙ заявки через
    штатный per-order механизм, CSV записан один раз; побочных торговых
    действий нет (заявки не отправляются и не отменяются, чужие заявки
    не опрашиваются)."""
    tmp_path = isolated_paths
    monitor = ExecutionMonitor(FakeClient())
    pos = make_open_position(monitor, "F1", "t-v6p")
    pos.state = PositionState.UNCERTAIN
    pos.close_reason = None
    monitor.add_close_order(pos, "sell-p6", LOTS)
    pos.close_order_request_id = "sell-p6"
    pos.close_requested_lots = LOTS
    pos.close_requested_at = None

    ledger = make_b2_ledger_case(
        tmp_path, clock, pos, "sell-p6", requested=LOTS,
        reason="close:", intent_at=T_0905, late_status="NEW",
        late_at=T_1020)

    clock.set(T_1020)
    client = FakeClient(order_state=terminal_report())
    # Полный reconcile (внутри вызывается _try_resolve_absent_position):
    run(main.reconcile(client, monitor, ledger, None))

    # Разрешение В2 штатно: учёт закрыт по терминальному отчёту СВОЕЙ
    # заявки через per-order cursor (не в обход):
    assert pos.state == PositionState.CLOSED
    assert pos.quantity == 0
    assert pos.close_reason == "LEDGER_CLOSE"
    assert pos.close_orders["sell-p6"]["applied_lots"] == LOTS
    assert pos.close_orders["sell-p6"]["confirmed_executed_lots"] == LOTS
    assert len(pos.close_applications) == 1
    # Опрошена ТОЛЬКО своя заявка; побочных торговых действий нет:
    assert client.state_calls == [("sell-p6", "REQUEST")]
    assert client.orders == []
    assert client.cancels == []

    # CSV записан ровно один раз, без исключений:
    run(main.process_closing(client, monitor, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    assert rows[0]["trade_id"] == "t-v6p"
    assert rows[0]["executed_lots"] == str(LOTS)
    assert rows[0]["exit_price"] == f"{110.0:.4f}"

    # Повторный reconcile: CLOSED-позиция вне ACTIVE_STATES — повторного
    # применения и дублей CSV нет (идемпотентность не нарушена):
    bytes_before = read_trades_bytes(tmp_path)
    run(main.reconcile(client, monitor, ledger, None))
    run(main.process_closing(client, monitor, None))
    assert len(pos.close_applications) == 1
    assert len(read_trades_csv(tmp_path)) == 1
    assert read_trades_bytes(tmp_path) == bytes_before
