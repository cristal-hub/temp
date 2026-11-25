# test_b2_v5_identity_and_timestamp.py
# Tsclp_v2.2_volatile — тесты v2.3.8-stage1 (B2 V5):
#   Defect A — СОХРАНЕННОЕ ВРЕМЯ ЗАПРОСА ЗАКРЫТИЯ (close timestamp):
#     время ЗАПРОСА SELL создаётся ОДИН раз ДО post_market_order(),
#     сохраняется в pos.close_requested_at И close_orders[request_id]
#     ["requested_at"] (одно и то же значение), переживает потерю ответа
#     брокера (result.state is None) и перезапуск (state.json); для старых
#     state.json без close_requested_at, но с собственным cursor'ом —
#     восстанавливается из cursor.requested_at. Время текущего запуска НЕ
#     подставляется вместо доступного timestamp. SEMANTICS: requested_at —
#     время ЗАПРОСА SELL, НЕ время фактического исполнения сделки
#     (используемый API его не подтверждает — proxy явно обозначен).
#   Defect B — FAIL-CLOSED ВАЛИДАЦИЯ ИДЕНТИЧНОСТИ RECOVERY-ЗАДАЧИ:
#     каждая задача pending_csv_recoveries при импорте и перед обработкой
#     проверяется на согласованность (rec.trade_id == snapshot.trade_id,
#     FIGI, своя close-заявка, привязка per-order cursor'а, дубликаты
#     trade_id); противоречивая задача НЕ опрашивается, НЕ изменяет CSV,
#     НЕ удаляется как завершённая — остаётся с маркером "conflict";
#     CSV-строка перед обновлением сверяется со снимком (FIGI/order_id).
#
# Соответствие сценариям ТЗ V5:
#   V5-A test_v5_a_lost_sell_response_keeps_request_timestamp
#   V5-B test_v5_b_cumulative_follows_saved_request_timestamps
#   V5-C test_v5_c_request_timestamp_survives_restart
#   V5-D test_v5_d_legacy_state_restores_ts_from_cursor
#   V5-E test_v5_e_recovery_task_trade_id_mismatch_fail_closed
#   V5-F test_v5_f_recovery_task_figi_mismatch_fail_closed
#   V5-G test_v5_g_cursor_identity_mismatch_fail_closed
#   V5-H test_v5_h_duplicate_trade_id_conflicting_tasks_fail_closed
#   V5-I test_v5_i_row_identity_mismatch_blocks_update
#   V5-J test_v5_j_valid_task_after_restart_completes_normally
#
# Инварианты:
#   - exit_time/timestamp_utc = сохранённое время ЗАПРОСА закрытия (или
#     requested_at cursor'а для легаси) — НЕ время восстановления и НЕ
#     время текущего запуска;
#   - несогласованная recovery-задача не может опросить брокера, обновить
#     чужую CSV-строку, затронуть другую позицию или считаться завершённой;
#   - маркер "conflict" персистентен (state.json) и не сбрасывается
#     повторной проверкой;
#   - валидная задача после перезапуска работает штатно (без ложных
#     блокировок).
#
# Запуск из корня репозитория: pytest test_b2_v5_identity_and_timestamp.py -v
# ТОЛЬКО fake-объекты: без сети, токенов, реального брокера и заявок.
# RESEARCH ONLY / NO LIVE ORDERS / SANDBOX.

import asyncio
import csv
import json
import os
import sys

from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import logger as research_logger
from execution import ExecutionMonitor, PositionState, TrackedPosition

_IMPORT_ERROR = None


def _install_sdk_stubs():
    """Минимальные заглушки t_tech.invest / telegram_bot (как в
    test_b2_v4_accounting_consistency.py) — нужны только для import main."""
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
# Инфраструктура (fake-клиент/отчёты — как в test_b2_v4_accounting_consistency)
# ===========================================================================

class _MV:
    """MoneyValue/Quotation-заглушка (units + nano)."""

    def __init__(self, units, nano=0):
        self.units = units
        self.nano = nano


class FakeState:
    """Отчёт заявки брокера (CANCELLED=3). executed_order_price — денежная
    СУММА исполнения: цена за инструмент = price_units / (lots * lot)."""

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
    вызовы (state_calls) — используется для проверки «опроса не было»."""

    def __init__(self, order_state=None, order_states=None, lot=1):
        self._order_state = order_state
        self._order_states = order_states or {}
        self._lot = lot
        self.state_calls = []
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
    """Управляемые детерминированные часы для main.datetime.now():
    позволяет отличить СОХРАНЁННЫЙ timestamp (время запроса) от времени
    текущего запуска/восстановления. Никаких sleep."""

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


def cum_of(*net_values):
    """Сумма 2-десятичных net-значений в том же виде, в каком её считает
    канонизация (float(строка) -> накопительная сумма -> "%.2f")."""
    running = 0.0
    for v in net_values:
        running += float(v)
    return f"{running:.2f}"


def events_of(subdir):
    parsed = []
    for line in read_events(subdir):
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return parsed


# ===========================================================================
# Единая точка создания «позиция закрыта своей SELL, CSV записан»
# (как make_closed_logged_at в test_b2_v4_accounting_consistency.py)
# ===========================================================================

ENTRY = 100.0
LOTS = 10

# Фиксированные времена (детерминированные, без привязки к now()):
T_0900 = "2026-11-20T09:00:00+00:00"
T_0905 = "2026-11-20T09:05:00+00:00"   # время ЗАПРОСА SELL первой сделки
T_1000 = "2026-11-20T10:00:00+00:00"
T_1005 = "2026-11-20T10:05:00+00:00"
T_1010 = "2026-11-20T10:10:00+00:00"
T_1020 = "2026-11-20T10:20:00+00:00"   # время ПОЗДНЕГО восстановления/запуска
T_1021 = "2026-11-20T10:21:00+00:00"
T_1022 = "2026-11-20T10:22:00+00:00"
T_1200 = "2026-11-20T12:00:00+00:00"


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
    """Регистрация НОВОЙ позиции по тому же FIGI (замена CLOSED-записи)."""
    return monitor.register(
        figi=figi, ticker=ticker, direction="BUY",
        entry_price=entry_price, quantity=lots,
        sl_price=entry_price * 0.98, tp_price=entry_price * 1.04,
        lot_size=1, state=PositionState.OPEN, trade_id=trade_id,
        signal_reason="v5-test", signal_time=T_0900,
    )


def model_commission(exit_price, entry_price=ENTRY, lots=LOTS):
    """Модельная (расчётная) СУММАРНАЯ комиссия сделки — формула штатной
    записи CSV (process_closing)."""
    turnover = (exit_price + entry_price) * lots
    return abs(turnover * config.COMMISSION_PER_SIDE)


def make_open_position(monitor, figi, trade_id, lots=LOTS):
    """OPEN-позиция в monitor.positions (как до вызова close_position)."""
    pos = TrackedPosition(
        figi=figi, ticker="TEST", direction="BUY", entry_price=ENTRY,
        quantity=lots, sl_price=ENTRY * 0.98, tp_price=ENTRY * 1.04,
        lot_size=1, state=PositionState.OPEN, trade_id=trade_id,
        price_before_order=ENTRY, close_price_before_order=ENTRY,
        order_send_time=T_0900,
    )
    monitor.positions[figi] = pos
    return pos


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


# ===========================================================================
# ТЕСТ V5-A. Потерянный ответ SELL: exit_time = время ЗАПРОСА, а не время
# позднего восстановления (result.state=None больше не теряет timestamp)
# ===========================================================================

def test_v5_a_lost_sell_response_keeps_request_timestamp(isolated_paths, clock,
                                                         monkeypatch):
    """SELL отправлена, ответ потерян (result.state=None); позиция позднее
    закрыта по восстановленному отчёту В ДРУГОЕ время. CSV exit_time должен
    соответствовать ПЕРВОНАЧАЛЬНОМУ времени запроса (сохранённому до
    сетевого вызова), а не времени позднего восстановления."""
    tmp_path = isolated_paths
    monitor = ExecutionMonitor(FakeClient())
    pos = make_open_position(monitor, "F1", "t-va5")

    # --- SELL при 09:05, ответ потерян ---
    lost = close_lost_response(clock, monitor, pos, T_0905, monkeypatch)
    req_id = pos.close_order_request_id
    # Единый timestamp сохранён ДО сетевого вызова и в позиции, и в cursor'е —
    # ОДНО И ТО ЖЕ значение:
    assert pos.close_requested_at == T_0905
    cursor = pos.close_orders[req_id]
    assert cursor["requested_at"] == T_0905
    assert pos.close_requested_at == cursor["requested_at"]
    # Заявка ушла с тем же клиентским UUID:
    assert lost.orders[0][3] == req_id

    # --- Позднее восстановление закрытия по отчёту (10:20) ---
    clock.set(T_1020)
    assert monitor.apply_close_execution(
        pos, req_id, LOTS, "CANCELLED", execution_price=110.0,
        commission=1.5, requested_lots=LOTS) is True
    assert pos.state == PositionState.CLOSED
    # timestamp запроса НЕ перезаписан восстановлением:
    assert pos.close_requested_at == T_0905

    client = FakeClient()
    run(main.process_closing(client, monitor, None))

    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["trade_id"] == "t-va5"
    # ГЛАВНОЕ: exit_time — время запроса SELL (09:05), НЕ время
    # восстановления (10:20) и НЕ время записи строки:
    assert row["exit_time"] == T_0905
    assert row["timestamp_utc"] == T_0905
    assert row["exit_time"] != T_1020
    assert row["exit_price"] == f"{110.0:.4f}"


# ===========================================================================
# ТЕСТ V5-B. Два закрытия: первая заявка отправлена раньше (ответ потерян),
# вторая сделка закрыта и записана раньше. После восстановления первой
# сделки cumulative соответствует сохранённым timestamp запросов
# ===========================================================================

def test_v5_b_cumulative_follows_saved_request_timestamps(isolated_paths, clock,
                                                           monkeypatch):
    """Сделка 1: SELL запрос при 09:05, ответ потерян; сделка 2 закрыта
    при 10:00 и записана ПЕРВОЙ. При 10:20 сделка 1 восстанавливается по
    отчёту. Хронология cumulative должна следовать СОХРАНЁННЫМ временам
    запросов (09:05 < 10:00), несмотря на порядок строк файла (2, 1) и
    на время восстановления 10:20."""
    tmp_path = isolated_paths
    monitor = ExecutionMonitor(FakeClient())
    pos1 = make_open_position(monitor, "F1", "t-vb1")

    lost = close_lost_response(clock, monitor, pos1, T_0905, monkeypatch)
    req1 = pos1.close_order_request_id

    # Вторая сделка закрыта (10:00) и записана ПЕРВОЙ (строка 1 файла):
    _mon2, pos2, _client2 = make_closed_logged_at(
        tmp_path, trade_id="t-vb2", figi="F2", oid="sell-b2",
        close_at=T_1000, price=105.0, commission=2.0)
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1 and rows[0]["trade_id"] == "t-vb2"
    assert rows[0]["exit_time"] == T_1000

    # Восстановление первой сделки по позднему отчёту (10:20).
    # resolve_closing опрашивает клиента МОНИТОРА — отчёт регистрируется
    # в том же FakeClient, что создан вместе с монитором:
    clock.set(T_1020)
    client = monitor.client
    client._order_states[req1] = FakeState(
        status_code=3, lots_executed=LOTS,
        price_units=110.0 * LOTS, commission=1.5)
    run(main.process_closing(client, monitor, None))

    rows = read_trades_csv(tmp_path)
    assert len(rows) == 2
    by_id = {r["trade_id"]: r for r in rows}
    # exit_time первой сделки = сохранённое время ЗАПРОСА (09:05),
    # не время восстановления (10:20):
    assert by_id["t-vb1"]["exit_time"] == T_0905
    assert by_id["t-vb1"]["exit_time"] != T_1020
    assert by_id["t-vb2"]["exit_time"] == T_1000
    # Хронология закрытий: t-vb1 (09:05) РАНЬШЕ t-vb2 (10:00), хотя строка
    # t-vb1 в файле ВТОРАЯ. cumulative:
    net1 = by_id["t-vb1"]["net_pnl_rub"]
    net2 = by_id["t-vb2"]["net_pnl_rub"]
    assert by_id["t-vb1"]["cumulative_net_pnl_rub"] == cum_of(net1)
    assert by_id["t-vb2"]["cumulative_net_pnl_rub"] == cum_of(net1, net2)


# ===========================================================================
# ТЕСТ V5-C. Перезапуск между потерянным ответом и восстановлением:
# timestamp сохраняется в state.json и не меняется
# ===========================================================================

def test_v5_c_request_timestamp_survives_restart(isolated_paths, clock,
                                                 monkeypatch):
    """Потерянный ответ SELL (09:05) -> перезапуск -> восстановление (10:20).
    Timestamp запроса переживает сохранение/загрузку state.json без
    изменений; CSV exit_time после рестарта = время запроса."""
    tmp_path = isolated_paths
    monitor = ExecutionMonitor(FakeClient())
    pos = make_open_position(monitor, "F1", "t-vc5")

    close_lost_response(clock, monitor, pos, T_0905, monkeypatch)
    req_id = pos.close_order_request_id

    # --- Перезапуск ---
    monitor2 = restart(tmp_path, monitor)
    pos1r = monitor2.positions["F1"]
    assert pos1r.close_requested_at == T_0905, \
        "close_requested_at сохранён в state.json без изменений"
    assert pos1r.close_orders[req_id]["requested_at"] == T_0905
    # Прямая проверка содержимого state.json:
    state_data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state_data["positions"]["F1"]["close_requested_at"] == T_0905
    assert state_data["positions"]["F1"]["close_orders"][req_id][
        "requested_at"] == T_0905

    # --- Восстановление закрытия после рестарта (10:20) ---
    clock.set(T_1020)
    assert monitor2.apply_close_execution(
        pos1r, req_id, LOTS, "CANCELLED", execution_price=110.0,
        commission=1.5, requested_lots=LOTS) is True
    client = FakeClient()
    run(main.process_closing(client, monitor2, None))

    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    assert rows[0]["exit_time"] == T_0905, \
        "после перезапуска exit_time = время запроса, не время запуска"
    assert rows[0]["timestamp_utc"] == T_0905


# ===========================================================================
# ТЕСТ V5-D. Старый state.json без close_requested_at, но с
# close_orders[request_id]["requested_at"]: время восстанавливается из
# cursor'а, время текущего запуска НЕ подставляется
# ===========================================================================

def test_v5_d_legacy_state_restores_ts_from_cursor(isolated_paths, clock):
    """Легаси-позиция: close_requested_at отсутствует (null в state.json),
    но собственный per-order cursor close-заявки содержит requested_at.
    При записи CSV время закрытия берётся ИЗ CURSOR'А, а не из времени
    текущего запуска (clock=10:10 при восстановлении != 09:05)."""
    tmp_path = isolated_paths
    monitor = ExecutionMonitor(FakeClient())
    pos = make_open_position(monitor, "F1", "t-vd5")

    # Легаси-путь: cursor создан с известным временем запроса,
    # close_requested_at в позиции ОТСУТСТВУЕТ (старый state.json).
    monitor.add_close_order(pos, "sell-d5", LOTS, requested_at=T_0905)
    pos.close_order_request_id = "sell-d5"
    pos.close_requested_lots = LOTS
    pos.close_requested_at = None
    assert monitor.apply_close_execution(
        pos, "sell-d5", LOTS, "CANCELLED", execution_price=None,
        commission=None, requested_lots=LOTS) is True
    assert pos.state == PositionState.CLOSED
    pos.close_requested_at = None  # гарантируем «легаси»-состояние

    # --- Перезапуск: в state.json поле отсутствует (null) ---
    monitor2 = restart(tmp_path, monitor)
    pos1r = monitor2.positions["F1"]
    assert not pos1r.close_requested_at
    cursor = pos1r.close_orders["sell-d5"]
    assert cursor["requested_at"] == T_0905

    # --- Запись CSV в время ТЕКУЩЕГО запуска (10:10) ---
    clock.set(T_1010)
    client = FakeClient(order_states={
        "sell-d5": FakeState(status_code=3, lots_executed=LOTS,
                             price_units=None, commission=None),
    })
    run(main.process_closing(client, monitor2, None))

    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["trade_id"] == "t-vd5"
    # ГЛАВНОЕ: время из cursor'а, НЕ время текущего запуска:
    assert row["exit_time"] == T_0905
    assert row["timestamp_utc"] == T_0905
    assert row["exit_time"] != T_1010


# ===========================================================================
# ТЕСТ V5-E. rec.trade_id != snapshot.trade_id: fail-closed (нет опроса,
# нет изменения CSV, задача не завершается)
# ===========================================================================

def test_v5_e_recovery_task_trade_id_mismatch_fail_closed(isolated_paths, clock):
    """Несогласованная внешняя запись задачи (trade_id отличается от снимка):
    при импорте задача помечается конфликтом, брокер не опрашивается,
    CSV не изменяется, задача НЕ удаляется как завершённая; событие с
    причиной конфликта записано."""
    tmp_path = isolated_paths
    monitor, pos1, _ = make_closed_logged_at(
        tmp_path, trade_id="t-ve5", figi="F1", oid="sell-e5",
        close_at=T_1000, price=None, commission=None)
    register_new_position(monitor, "F1", "t-ve5-n")
    assert len(monitor.pending_csv_recoveries) == 1
    task = monitor.pending_csv_recoveries[0]
    assert task["trade_id"] == "t-ve5"
    # Эмуляция несогласованной внешней записи (рекорд указывает на другую
    # сделку, чем его собственный снимок):
    task["trade_id"] = "t-other"
    validator_result = ExecutionMonitor.validate_recovery_identity(task)
    assert validator_result == "trade_id_mismatch"

    # --- Перезапуск: импорт обязан пометить задачу конфликтом ---
    monitor2 = restart(tmp_path, monitor)
    tasks = monitor2.pending_csv_recoveries
    assert len(tasks) == 1, "задача НЕ удаляется как успешно завершённая"
    assert tasks[0].get("conflict") == "trade_id_mismatch"

    # --- Recovery-цикл: без опроса и без изменения CSV ---
    bytes_before = read_trades_bytes(tmp_path)
    clock.set(T_1020)
    client = FakeClient(order_states={
        "sell-e5": FakeState(status_code=3, lots_executed=LOTS,
                             price_units=110.0 * LOTS, commission=1.5),
    })
    run(main.process_closing(client, monitor2, None))

    assert client.state_calls == [], "брокер НЕ опрашивается (fail-closed)"
    assert read_trades_bytes(tmp_path) == bytes_before, "CSV не изменён"
    assert len(monitor2.pending_csv_recoveries) == 1
    assert monitor2.pending_csv_recoveries[0].get("conflict") == "trade_id_mismatch"
    events = events_of(tmp_path)
    conflicts = [e for e in events
                 if e.get("event") == "CSV_RECOVERY_TASK_CONFLICT"
                 or e.get("type") == "CSV_RECOVERY_TASK_CONFLICT"]
    assert conflicts, "диагностическое событие конфликта записано"
    assert any((e.get("reason") == "trade_id_mismatch") for e in conflicts)


# ===========================================================================
# ТЕСТ V5-F. FIGI внешней задачи отличается от FIGI снимка: fail-closed
# ===========================================================================

def test_v5_f_recovery_task_figi_mismatch_fail_closed(isolated_paths, clock):
    """rec.figi != snapshot.figi: задача блокируется при импорте (конфликт
    figi_mismatch), брокер не опрашивается, CSV не изменяется, задача
    остаётся с маркером; чужая строка не обновляется."""
    tmp_path = isolated_paths
    monitor, pos1, _ = make_closed_logged_at(
        tmp_path, trade_id="t-vf5", figi="F1", oid="sell-f5",
        close_at=T_1000, price=None, commission=None)
    register_new_position(monitor, "F1", "t-vf5-n")
    task = monitor.pending_csv_recoveries[0]
    assert task["figi"] == "F1"
    task["figi"] = "F9"  # внешняя запись указывает на другой FIGI
    assert ExecutionMonitor.validate_recovery_identity(task) == "figi_mismatch"

    monitor2 = restart(tmp_path, monitor)
    assert len(monitor2.pending_csv_recoveries) == 1
    assert monitor2.pending_csv_recoveries[0].get("conflict") == "figi_mismatch"

    bytes_before = read_trades_bytes(tmp_path)
    clock.set(T_1020)
    client = FakeClient(order_states={
        "sell-f5": FakeState(status_code=3, lots_executed=LOTS,
                             price_units=110.0 * LOTS, commission=1.5),
    })
    run(main.process_closing(client, monitor2, None))

    assert client.state_calls == []
    assert read_trades_bytes(tmp_path) == bytes_before
    assert len(monitor2.pending_csv_recoveries) == 1
    assert monitor2.pending_csv_recoveries[0].get("conflict") == "figi_mismatch"
    events = events_of(tmp_path)
    assert any(e.get("reason") == "figi_mismatch"
               for e in events
               if e.get("event") == "CSV_RECOVERY_TASK_CONFLICT"
               or e.get("type") == "CSV_RECOVERY_TASK_CONFLICT")


# ===========================================================================
# ТЕСТ V5-G. Close cursor содержит другой trade_id / FIGI: fail-closed
# ===========================================================================

def test_v5_g_cursor_identity_mismatch_fail_closed(isolated_paths, clock):
    """Cursor собственной close-заявки снимка привязан к ДРУГОЙ сделке
    (другой trade_id / другой FIGI): идентичность отчёта и сделки не
    подтверждена — задача блокируется (cursor_trade_id_mismatch /
    cursor_figi_mismatch), брокер не опрашивается, CSV не изменяется."""
    tmp_path = isolated_paths
    # --- Вариант 1: cursor с другим trade_id ---
    monitor, pos1, _ = make_closed_logged_at(
        tmp_path, trade_id="t-vg5", figi="F1", oid="sell-g5",
        close_at=T_1000, price=None, commission=None)
    register_new_position(monitor, "F1", "t-vg5-n")
    task = monitor.pending_csv_recoveries[0]
    snap_cursor = task["position"]["close_orders"]["sell-g5"]
    snap_cursor["trade_id"] = "t-foreign"
    assert ExecutionMonitor.validate_recovery_identity(task) == \
        "cursor_trade_id_mismatch"
    monitor2 = restart(tmp_path, monitor)
    assert monitor2.pending_csv_recoveries[0].get("conflict") == \
        "cursor_trade_id_mismatch"

    bytes_before = read_trades_bytes(tmp_path)
    clock.set(T_1020)
    client = FakeClient(order_states={
        "sell-g5": FakeState(status_code=3, lots_executed=LOTS,
                             price_units=110.0 * LOTS, commission=1.5),
    })
    run(main.process_closing(client, monitor2, None))
    assert client.state_calls == []
    assert read_trades_bytes(tmp_path) == bytes_before
    assert len(monitor2.pending_csv_recoveries) == 1

    # --- Вариант 2: cursor с другим FIGI (прямая проверка валидатора) ---
    task2 = json.loads(json.dumps({
        "version": 1, "trade_id": "t-vg5b", "figi": "F1", "ticker": "TEST",
        "reason": "position_replaced_same_figi",
        "position": {
            "figi": "F1", "ticker": "TEST", "direction": "BUY",
            "entry_price": ENTRY, "quantity": 0, "sl_price": ENTRY * 0.98,
            "tp_price": ENTRY * 1.04, "lot_size": 1,
            "state": "CLOSED", "trade_id": "t-vg5b", "logged": True,
            "close_order_request_id": "sell-g5b",
            "close_orders": {"sell-g5b": {
                "order_id": "sell-g5b", "trade_id": "t-vg5b",
                "figi": "F9", "side": "SELL", "requested_lots": LOTS,
                "confirmed_executed_lots": LOTS, "applied_lots": LOTS,
                "status": "CANCELLED", "requested_at": T_0905,
                "avg_exec_price": None, "commission": None,
            }},
            "close_applications": [],
        },
    }))
    assert ExecutionMonitor.validate_recovery_identity(task2) == \
        "cursor_figi_mismatch"


# ===========================================================================
# ТЕСТ V5-H. Две recovery-задачи с одним trade_id, но разными close order
# IDs: никакого произвольного выбора, никаких обновлений CSV
# ===========================================================================

def test_v5_h_duplicate_trade_id_conflicting_tasks_fail_closed(isolated_paths,
                                                               clock):
    """Два задания с одним trade_id и РАЗНЫМИ снимками/close-заявками:
    при импорте ОБЕ помечаются duplicate_trade_id_conflicting, ни одна не
    выбирается произвольно, брокер не опрашивается, CSV не изменяется,
    ни одна не удаляется и не завершается."""
    tmp_path = isolated_paths
    monitor, pos1, _ = make_closed_logged_at(
        tmp_path, trade_id="t-vh5", figi="F1", oid="sell-ha",
        close_at=T_1000, price=None, commission=None)
    register_new_position(monitor, "F1", "t-vh5-n1")
    tasks = monitor.pending_csv_recoveries
    assert len(tasks) == 1
    # Вторая задача с ТОМ ЖЕ trade_id, но ДРУГОЙ close-заявкой/снимком
    # (в очередь попадает при импорте повреждённого state.json):
    task2 = json.loads(json.dumps(tasks[0]))
    task2["position"]["close_order_request_id"] = "sell-hb"
    task2["position"]["close_order_id"] = None
    task2["position"]["close_orders"] = {"sell-hb": {
        "order_id": "sell-hb", "trade_id": "t-vh5", "figi": "F1",
        "side": "SELL", "requested_lots": LOTS,
        "confirmed_executed_lots": LOTS, "applied_lots": LOTS,
        "status": "CANCELLED", "requested_at": T_1005,
        "avg_exec_price": None, "commission": None,
    }}
    tasks.append(task2)
    # Канонические тела задач различны -> конфликтующие дубликаты:
    assert (ExecutionMonitor._recovery_canonical_body(tasks[0])
            != ExecutionMonitor._recovery_canonical_body(task2))

    monitor2 = restart(tmp_path, monitor)
    imported = monitor2.pending_csv_recoveries
    assert len(imported) == 2, "ни одна задача не выбрана произвольно"
    assert all(t.get("conflict") == "duplicate_trade_id_conflicting"
               for t in imported)

    bytes_before = read_trades_bytes(tmp_path)
    clock.set(T_1020)
    client = FakeClient(order_states={
        "sell-ha": FakeState(status_code=3, lots_executed=LOTS,
                             price_units=110.0 * LOTS, commission=1.5),
        "sell-hb": FakeState(status_code=3, lots_executed=LOTS,
                             price_units=111.0 * LOTS, commission=1.6),
    })
    run(main.process_closing(client, monitor2, None))

    assert client.state_calls == [], "ни одна из конфликтующих заявок не опрошена"
    assert read_trades_bytes(tmp_path) == bytes_before, "CSV не изменён"
    assert len(monitor2.pending_csv_recoveries) == 2
    assert all(t.get("conflict") == "duplicate_trade_id_conflicting"
               for t in monitor2.pending_csv_recoveries)
    events = events_of(tmp_path)
    dup_conflicts = [e for e in events
                     if (e.get("event") == "CSV_RECOVERY_TASK_CONFLICT"
                         or e.get("type") == "CSV_RECOVERY_TASK_CONFLICT")
                     and e.get("reason") == "duplicate_trade_id_conflicting"]
    assert dup_conflicts, "диагностика конфликтующих дубликатов записана"


# ===========================================================================
# ТЕСТ V5-I. CSV-строка с противоречащим FIGI или order_id: чужая строка
# не изменяется (проверка строки перед обновлением)
# ===========================================================================

def test_v5_i_row_identity_mismatch_blocks_update(isolated_paths, clock):
    """Строка CSV, найденная по trade_id, противоречит снимку сделки по
    FIGI (вариант 1) или order_id (вариант 2) — обновление ЗАПРЕЩЕНО,
    чужая строка не изменяется, событие конфликта записано. После
    исправления строки штатное восстановление работает (контроль)."""
    tmp_path = isolated_paths
    monitor, pos1, _ = make_closed_logged_at(
        tmp_path, trade_id="t-vi5", figi="F1", oid="sell-i5",
        close_at=T_1000, price=None, commission=None)
    register_new_position(monitor, "F1", "t-vi5-n")
    assert len(monitor.pending_csv_recoveries) == 1
    report = FakeState(status_code=3, lots_executed=LOTS,
                       price_units=110.0 * LOTS, commission=1.5)

    # --- Вариант 1: figi строки противоречит снимку ---
    assert research_logger.update_trade_row(
        "t-vi5", {"figi": "F9"})[0] == "updated"
    bytes_before = read_trades_bytes(tmp_path)
    clock.set(T_1020)
    run(main.process_closing(
        FakeClient(order_states={"sell-i5": report}), monitor, None))
    assert read_trades_bytes(tmp_path) == bytes_before, \
        "чужая строка (figi) не изменяется"
    rows = read_trades_csv(tmp_path)
    assert rows[0]["exit_price"] == ""
    events = events_of(tmp_path)
    assert any(e.get("reason") == "row_figi_mismatch"
               for e in events
               if e.get("event") == "CSV_LATE_METADATA_CONFLICT"
               or e.get("type") == "CSV_LATE_METADATA_CONFLICT")
    assert len(monitor.pending_csv_recoveries) == 1, "задача не завершена"

    # --- Вариант 2: order_id строки противоречит снимку ---
    assert research_logger.update_trade_row(
        "t-vi5", {"figi": "F1", "order_id": "sell-FOREIGN"})[0] == "updated"
    bytes_before = read_trades_bytes(tmp_path)
    clock.set(T_1021)
    run(main.process_closing(
        FakeClient(order_states={"sell-i5": report}), monitor, None))
    assert read_trades_bytes(tmp_path) == bytes_before, \
        "чужая строка (order_id) не изменяется"
    rows = read_trades_csv(tmp_path)
    assert rows[0]["exit_price"] == ""
    events = events_of(tmp_path)
    assert any(e.get("reason") == "row_order_id_mismatch"
               for e in events
               if e.get("event") == "CSV_LATE_METADATA_CONFLICT"
               or e.get("type") == "CSV_LATE_METADATA_CONFLICT")
    assert len(monitor.pending_csv_recoveries) == 1

    # --- Контроль: согласованная строка обновляется штатно ---
    assert research_logger.update_trade_row(
        "t-vi5", {"figi": "F1", "order_id": "sell-i5"})[0] == "updated"
    clock.set(T_1022)
    run(main.process_closing(
        FakeClient(order_states={"sell-i5": report}), monitor, None))
    rows = read_trades_csv(tmp_path)
    assert rows[0]["exit_price"] == f"{110.0:.4f}"
    assert rows[0]["actual_commission_rub"] == "1.50"
    assert monitor.pending_csv_recoveries == [], "задача штатно завершена"


# ===========================================================================
# ТЕСТ V5-J. Корректная recovery-задача после перезапуска продолжает
# работать штатно (без ложных блокировок)
# ===========================================================================

def test_v5_j_valid_task_after_restart_completes_normally(isolated_paths, clock):
    """Валидная задача (согласованная запись, снимок, cursor) проходит
    перезапуск БЕЗ маркера конфликта и штатно восстанавливает поздние
    метаданные в СВОЮ строку; задача завершается и удаляется из очереди."""
    tmp_path = isolated_paths
    monitor, pos1, _ = make_closed_logged_at(
        tmp_path, trade_id="t-vj5", figi="F1", oid="sell-j5",
        close_at=T_1000, price=None, commission=None)
    register_new_position(monitor, "F1", "t-vj5-n")
    assert len(monitor.pending_csv_recoveries) == 1

    # --- Перезапуск: валидная задача без конфликта ---
    monitor2 = restart(tmp_path, monitor)
    tasks = monitor2.pending_csv_recoveries
    assert len(tasks) == 1
    assert "conflict" not in tasks[0], \
        "валидная задача не блокируется (нет ложного конфликта)"
    assert tasks[0]["trade_id"] == "t-vj5"
    assert tasks[0]["position"]["close_order_request_id"] == "sell-j5"
    json.dumps(monitor2.export_state(), ensure_ascii=False)

    # --- Штатное восстановление поздних данных своей заявки ---
    clock.set(T_1020)
    client = FakeClient(order_states={
        "sell-j5": FakeState(status_code=3, lots_executed=LOTS,
                             price_units=110.0 * LOTS, commission=1.5),
    })
    run(main.process_closing(client, monitor2, None))

    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1, "строка одна — дубли не создаются"
    row = rows[0]
    assert row["trade_id"] == "t-vj5"
    assert row["exit_price"] == f"{110.0:.4f}"
    assert row["actual_commission_rub"] == "1.50"
    assert "PRICE_UNKNOWN" not in row["error_note"]
    # Время закрытия не изменилось (перезапуск/recovery не трогают exit_time):
    assert row["exit_time"] == T_1000
    assert monitor2.pending_csv_recoveries == [], "задача завершена и удалена"
