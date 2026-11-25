# test_b2_close_accounting.py
# Tsclp_v2.1_volatile_Samsung — регрессионные тесты аудита B2 CLOSE ACCOUNTING
# (v2.3.4-stage1): исполнение собственной SELL-заявки в В2 применяется
# ШТАТНЫМ per-order механизмом ExecutionMonitor.apply_close_execution()
# вместо прямого _finalize_position_closed().
#
# Соответствие сценариев ТЗ (раздел 5):
#   1  test_01_full_sell_23_via_b2_applies_via_cursor
#   2  test_02_full_sell_already_applied_by_resolve_closing_no_double_apply
#   3  test_03_repeated_identical_terminal_report_no_reapplication
#   4  test_04_contradictory_repeat_with_increased_cumulative_fail_closed
#   5  test_05_partial_3_of_10_cancelled_lots_already_applied
#   6  test_06_partial_3_of_10_cancelled_b2_first_gets_terminal_report
#   7  test_07_csv_keeps_requested_10_and_executed_3
#   8  test_08_actual_commission_and_execution_price_preserved
#   9  test_09_no_fictitious_pnl_for_externally_closed_remainder
#   10 test_10_b3_external_close_without_own_sell_unchanged
#   11 test_11a_ledger_sync_failure_safe_state (сбой синхронизации реестра)
#      test_11b_unknown_status_without_broker_answer_no_false_closed
#   12 test_12_repeated_reconciliation_no_reapply_no_csv_duplicates
#
# ИЗМЕНЕНИЯ (v2.3.4-stage2 — финальные граничные дефекты B2):
#   13 test_b2_terminal_ledger_record_without_cursor_recovers_broker_commission
#      (Дефект-1: восстановление фактической комиссии из отчёта брокера,
#      когда запись реестра уже полна, а per-order cursor отсутствует)
#   14 test_b2_record_commission_reused_without_broker_poll
#      (Дефект-1: комиссия, уже сохранённая в записи, используется как
#      есть — без опроса брокера и без расчётной подстановки)
#   15 test_b2_terminal_repeat_different_status_is_contradiction
#      (Дефект-2: CANCELLED 3/10 -> FILL 3/10 — противоречие, UNCERTAIN)
#   16 test_b2_terminal_repeat_different_price_is_contradiction
#      (Дефект-2: цена 100 -> 101 при том же исполнении — UNCERTAIN)
#   17 test_b2_terminal_repeat_different_commission_is_contradiction
#      (Дефект-2: комиссия 1.5 -> 2.0 — UNCERTAIN)
#   18 test_b2_terminal_repeat_missing_optional_data_is_idempotent
#      (Дефект-2: отсутствующее необязательное поле — НЕ противоречие)
#   19 test_b2_terminal_repeat_exact_report_is_idempotent
#      (Дефект-2: полностью совпадающий отчёт — безопасный повтор)
#
# Запуск из корня репозитория: pytest test_b2_close_accounting.py -v
# Файл работает и из tests/ (раскладка не влияет на импорты).
# ТОЛЬКО fake-объекты: без сети, токенов, реального брокера и заявок.

import asyncio
import csv
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import logger as research_logger
from execution import ExecutionMonitor, PositionState, TrackedPosition
from order_ledger import OrderLedger

UTC = timezone.utc

_IMPORT_ERROR = None


def _install_sdk_stubs():
    """Минимальные заглушки t_tech.invest / telegram_bot для запуска вне
    окружения репозитория (как в test_stage1_packet_v.py)."""
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
    _INSTALL_ERROR = None

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


def make_buy_pos(**over):
    base = dict(
        figi="F1", ticker="TEST", direction="BUY", entry_price=100.0,
        quantity=10, sl_price=98.0, tp_price=104.0, lot_size=1,
        state=PositionState.OPEN, trade_id="t1",
        price_before_order=100.0,
        order_send_time=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    )
    base.update(over)
    return TrackedPosition(**base)


def run(coro):
    return asyncio.run(coro)


class _MV:
    """MoneyValue/Quotation-заглушка (units + nano)."""

    def __init__(self, units, nano=0):
        self.units = units
        self.nano = nano


class FakeState:
    """Минимальный аналог отчёта заявки брокера (FILL=1, CANCELLED=3)."""

    def __init__(self, status_code=1, lots_executed=10, price_units=1000,
                 commission=None, lot=1):
        self.execution_report_status = status_code
        self.lots_executed = lots_executed
        # executed_order_price — ДЕНЕЖНАЯ СУММА исполнения:
        # цена за инструмент = price_units / (lots_executed * lot).
        self.executed_order_price = _MV(price_units)
        self.executed_commission = commission


class FakeClient:
    """Fake-клиент: фиксирует вызовы get_sandbox_order_state (без сети)."""

    def __init__(self, order_state=None, prices=None, lot=1):
        self._order_state = order_state
        self._prices = prices or {}
        self._lot = lot
        self.state_calls = []
        self.uncertain_state = False

    async def get_sandbox_order_state(self, oid, order_id_type=None):
        self.state_calls.append((str(oid), order_id_type))
        return self._order_state

    async def get_instrument_info(self, figi):
        return {"lot": self._lot}

    async def get_last_prices(self, figis):
        return self._prices

    async def get_positions(self):
        return {}


def fresh_ledger(tmp_path):
    ledger = OrderLedger(str(tmp_path / "order_ledger.jsonl"))
    ledger.load()
    return ledger


def backdate(ledger, order_id, dt):
    """Сдвигает created_at_utc записи реестра (граница «заявка после входа»)."""
    rec = ledger.latest(order_id)
    rec["created_at_utc"] = dt.isoformat()
    ledger._latest[order_id] = rec


def setup_close_sell(ledger, pos, oid, requested, reason="close:SL",
                     monitor=None):
    """Регистрирует SELL-заявку закрытия как production close_position:
    INTENT в реестре + per-order журнал позиции (add_close_order)."""
    assert ledger.record_intent(oid, trade_id=pos.trade_id, figi=pos.figi,
                                ticker=pos.ticker, side="SELL",
                                requested_lots=requested, reason=reason)
    backdate(ledger, oid, datetime.now(UTC) - timedelta(minutes=59))
    pos.close_order_request_id = oid
    pos.close_requested_lots = requested
    pos.close_requested_at = datetime.now(UTC).isoformat()
    pos.state = PositionState.CLOSING
    if monitor is not None:
        monitor.add_close_order(pos, oid, requested,
                                pos.close_requested_at)


def monitor_with(monitor, pos):
    monitor.positions[pos.figi] = pos
    return monitor


def read_trades_csv(tmp_path):
    path = tmp_path / "research_trades.csv"
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


# ===========================================================================
# Сценарий 1. Полный SELL 23/23 через B2 без предварительного применения
# ===========================================================================

def test_01_full_sell_23_via_b2_applies_via_cursor(isolated_paths):
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=23)
    monitor = monitor_with(ExecutionMonitor(FakeClient()), pos)
    oid = "sell-full-23"
    setup_close_sell(ledger, pos, oid, requested=23)
    ledger.record_sent(oid, figi="F1", ticker="TEST", side="SELL",
                       requested_lots=23, executed_lots=0, status_hint="NEW")
    # Брокер: терминальный FILL 23/23, сумма исполнения 2300 -> цена 100.0,
    # фактическая комиссия 2.5.
    client = FakeClient(order_state=FakeState(
        status_code=1, lots_executed=23, price_units=2300,
        commission=_MV(2, 500000000)))

    action = run(main._try_resolve_absent_position(client, ledger, pos, monitor))

    assert action == "ledger_close"
    # Состояние позиции — штатное закрытие через apply_close_execution.
    assert pos.state == PositionState.CLOSED
    assert pos.quantity == 0
    assert pos.executed_lots == 23
    assert pos.partial is False
    # per-order cursor применён (не обойдён):
    cur = pos.close_orders[oid]
    assert cur["confirmed_executed_lots"] == 23
    assert cur["applied_lots"] == 23
    assert cur["status"] == "FILL"
    assert cur["avg_exec_price"] == pytest.approx(100.0)
    assert cur["commission"] == pytest.approx(2.5)
    # История применений записана штатно.
    assert len(pos.close_applications) == 1
    assert pos.close_applications[0]["delta_lots"] == 23
    # Цена/комиссия/подтверждение цены выхода — на позиции.
    assert pos.execution_price == pytest.approx(100.0)
    assert pos.exit_price_confirmed is True
    assert pos.actual_commission == pytest.approx(2.5)
    # Синхронизация реестра терминальным статусом.
    rec = ledger.latest(oid)
    assert rec["status"] == "FILL"
    assert int(rec["executed_lots"]) == 23
    # Опрос брокера — с ЯВНЫМ типом идентификатора (REQUEST: запись робота).
    assert ("sell-full-23", "REQUEST") in client.state_calls


# ===========================================================================
# Сценарий 2. Полный SELL 23/23, уже применённый штатным resolve_closing()
# ===========================================================================

def test_02_full_sell_already_applied_by_resolve_closing_no_double_apply(isolated_paths):
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=23)
    client = FakeClient(order_state=FakeState(
        status_code=1, lots_executed=23, price_units=2300))
    # Один общий клиент для монитора и B2 (resolve_closing опрашивает
    # monitor.client — тот же fake, что и в B2).
    monitor = monitor_with(ExecutionMonitor(client), pos)
    oid = "sell-full-23b"
    setup_close_sell(ledger, pos, oid, requested=23, monitor=monitor)
    # Штатное применение ДО B2 (как process_closing делает при CLOSING):
    run(monitor.resolve_closing(pos, ledger=ledger))
    assert pos.state == PositionState.CLOSED
    assert pos.close_orders[oid]["applied_lots"] == 23
    assert len(pos.close_applications) == 1
    # CSV записана штатным process_closing.
    run(main.process_closing(client, monitor, None))
    assert len(read_trades_csv(isolated_paths)) == 1

    # Повторный (запоздалый) вызов B2 по той же позиции:
    action = run(main._try_resolve_absent_position(client, ledger, pos, monitor))
    assert action == "ledger_close"          # безопасный повтор терминала
    # Повторного списания нет: cursor и история не изменились.
    assert pos.close_orders[oid]["applied_lots"] == 23
    assert pos.close_orders[oid]["confirmed_executed_lots"] == 23
    assert len(pos.close_applications) == 1
    assert pos.executed_lots == 23
    assert pos.quantity == 0
    assert pos.state == PositionState.CLOSED
    # CSV не задублировалась.
    run(main.process_closing(client, monitor, None))
    assert len(read_trades_csv(isolated_paths)) == 1


# ===========================================================================
# Сценарий 3. Повторный идентичный терминальный отчёт — без повторного списания
# ===========================================================================

def test_03_repeated_identical_terminal_report_no_reapplication(isolated_paths):
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=10)
    monitor = monitor_with(ExecutionMonitor(FakeClient()), pos)
    oid = "sell-rep"
    setup_close_sell(ledger, pos, oid, requested=10)
    ledger.record_sent(oid, figi="F1", ticker="TEST", side="SELL",
                       requested_lots=10, executed_lots=0, status_hint="NEW")
    client = FakeClient(order_state=FakeState(
        status_code=1, lots_executed=10, price_units=1000))

    first = run(main._try_resolve_absent_position(client, ledger, pos, monitor))
    assert first == "ledger_close"
    applied_after_first = pos.close_orders[oid]["applied_lots"]
    history_after_first = list(pos.close_applications)

    second = run(main._try_resolve_absent_position(client, ledger, pos, monitor))
    assert second == "ledger_close"
    assert pos.close_orders[oid]["applied_lots"] == applied_after_first == 10
    assert pos.close_applications == history_after_first  # история не выросла
    assert pos.executed_lots == 10
    assert pos.quantity == 0
    assert pos.state == PositionState.CLOSED
    # CSV после первого прогона — ровно одна строка.
    run(main.process_closing(client, monitor, None))
    assert len(read_trades_csv(isolated_paths)) == 1


# ===========================================================================
# Сценарий 4. Противоречивый повтор с увеличенным cumulative — fail-closed
# ===========================================================================

def test_04_contradictory_repeat_with_increased_cumulative_fail_closed(isolated_paths):
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=23)
    monitor = monitor_with(ExecutionMonitor(FakeClient()), pos)
    oid = "sell-bad"
    setup_close_sell(ledger, pos, oid, requested=23)
    client = FakeClient(order_state=FakeState(
        status_code=1, lots_executed=23, price_units=2300))
    assert run(main._try_resolve_absent_position(client, ledger, pos, monitor)) \
        == "ledger_close"
    run(main.process_closing(client, monitor, None))
    assert len(read_trades_csv(isolated_paths)) == 1

    # «Поздний» противоречивый отчёт: cumulative 30 > учтённого терминального 23.
    assert ledger.record_status(oid, "FILL", figi="F1", ticker="TEST",
                                side="SELL", requested_lots=23,
                                executed_lots=30, avg_exec_price=100.0)
    client2 = FakeClient(order_state=None)  # без опроса: запись «полная»
    action = run(main._try_resolve_absent_position(client2, ledger, pos, monitor))

    assert action == "uncertain"
    assert pos.state == PositionState.UNCERTAIN      # fail-closed
    assert client2.uncertain_state is True
    # Исполнение НЕ применено повторно.
    assert pos.close_orders[oid]["applied_lots"] == 23
    assert pos.close_orders[oid]["confirmed_executed_lots"] == 23
    assert len(pos.close_applications) == 1
    assert pos.executed_lots == 23
    # CSV не задублировалась и не переписана фиктивными лотами.
    assert len(read_trades_csv(isolated_paths)) == 1


# ===========================================================================
# Сценарий 5. Частичный SELL 3/10 -> CANCELLED, 3 лота уже применены
# штатным resolve_closing() до запуска B2
# ===========================================================================

def test_05_partial_3_of_10_cancelled_lots_already_applied(isolated_paths):
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=10)
    client = FakeClient(order_state=FakeState(
        status_code=3, lots_executed=3, price_units=330,
        commission=_MV(0, 500000000)))
    # Общий fake-клиент для монитора (resolve_closing) и B2.
    monitor = monitor_with(ExecutionMonitor(client), pos)
    oid = "sell-part-5"
    setup_close_sell(ledger, pos, oid, requested=10, monitor=monitor)
    # Вариант 1: 3 лота применены штатно resolve_closing() ДО B2.
    run(monitor.resolve_closing(pos, ledger=ledger))
    assert pos.state == PositionState.UNCERTAIN
    assert pos.quantity == 7
    assert pos.close_orders[oid]["applied_lots"] == 3

    action = run(main._try_resolve_absent_position(client, ledger, pos, monitor))

    assert action == "ledger_close"   # безопасный повтор терминального отчёта
    # Учтены только фактически исполненные 3 лота; остаток 7 — внешнее закрытие.
    assert pos.state == PositionState.CLOSED
    assert pos.quantity == 0
    assert pos.executed_lots == 3
    assert pos.partial is True
    # Повторного применения 3 лотов нет.
    assert pos.close_orders[oid]["applied_lots"] == 3
    assert pos.close_orders[oid]["confirmed_executed_lots"] == 3
    assert len(pos.close_applications) == 1
    # Запрошенное количество сохранено.
    assert pos.close_requested_lots == 10
    # Внешнее закрытие остатка явно различимо в error_note.
    assert "частичное исполнение SELL (3/10" in pos.error_note
    assert "остаток 7 лот. закрыт вне робота" in pos.error_note
    assert "P&L остатка не рассчитан" in pos.error_note
    # Цена первых 3 лотов не приписана остатку: цена позиции — за инструмент.
    assert pos.execution_price == pytest.approx(110.0)
    assert pos.exit_price_confirmed is True


# ===========================================================================
# Сценарий 6. Частичный SELL 3/10 -> CANCELLED, B2 первым получает отчёт
# ===========================================================================

def test_06_partial_3_of_10_cancelled_b2_first_gets_terminal_report(isolated_paths):
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=10)
    monitor = monitor_with(ExecutionMonitor(FakeClient()), pos)
    oid = "sell-part-6"
    setup_close_sell(ledger, pos, oid, requested=10)
    ledger.record_sent(oid, figi="F1", ticker="TEST", side="SELL",
                       requested_lots=10, executed_lots=0, status_hint="NEW")
    client = FakeClient(order_state=FakeState(
        status_code=3, lots_executed=3, price_units=330,
        commission=_MV(0, 500000000)))

    action = run(main._try_resolve_absent_position(client, ledger, pos, monitor))

    assert action == "ledger_close"
    # B2 применил исполнение САМОСТОЯТЕЛЬНО штатным per-order механизмом.
    cur = pos.close_orders[oid]
    assert cur["applied_lots"] == 3
    assert cur["confirmed_executed_lots"] == 3
    assert cur["status"] == "CANCELLED"
    assert cur["avg_exec_price"] == pytest.approx(110.0)
    assert cur["commission"] == pytest.approx(0.5)
    assert len(pos.close_applications) == 1
    assert pos.close_applications[0]["delta_lots"] == 3
    assert pos.close_applications[0]["from_applied_lots"] == 0
    assert pos.close_applications[0]["to_applied_lots"] == 3
    # Итог: только 3 исполненных лота, остаток закрыт внешне.
    assert pos.state == PositionState.CLOSED
    assert pos.quantity == 0
    assert pos.executed_lots == 3
    assert pos.partial is True
    assert pos.close_requested_lots == 10
    assert pos.execution_price == pytest.approx(110.0)
    assert pos.exit_price_confirmed is True
    assert pos.actual_commission == pytest.approx(0.5)
    # Реестр синхронизирован терминальным статусом с фактическим исполнением.
    rec = ledger.latest(oid)
    assert rec["status"] == "CANCELLED"
    assert int(rec["executed_lots"]) == 3
    assert float(rec["avg_exec_price"]) == pytest.approx(110.0)


# ===========================================================================
# Сценарий 7. CSV: исходные 10 запрошенных и фактические 3 исполненных
# ===========================================================================

def test_07_csv_keeps_requested_10_and_executed_3(isolated_paths):
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=10)
    monitor = monitor_with(ExecutionMonitor(FakeClient()), pos)
    oid = "sell-part-7"
    setup_close_sell(ledger, pos, oid, requested=10)
    ledger.record_sent(oid, figi="F1", ticker="TEST", side="SELL",
                       requested_lots=10, executed_lots=0, status_hint="NEW")
    client = FakeClient(order_state=FakeState(
        status_code=3, lots_executed=3, price_units=330))
    assert run(main._try_resolve_absent_position(client, ledger, pos, monitor)) \
        == "ledger_close"

    run(main.process_closing(client, monitor, None))
    rows = read_trades_csv(isolated_paths)
    assert len(rows) == 1
    row = rows[0]
    # Первоначально запрошенное количество НЕ потеряно, исполнено 3.
    assert row["requested_lots"] == "10"
    assert row["executed_lots"] == "3"
    # Частичное исполнение однозначно отражено.
    assert row["execution_status"] == "FILL_PARTIAL"
    assert "частичное исполнение SELL (3/10" in row["error_note"]
    assert "остаток 7 лот. закрыт вне робота" in row["error_note"]


# ===========================================================================
# Сценарий 8. Корректная комиссия и цена исполнения
# ===========================================================================

def test_08_actual_commission_and_execution_price_preserved(isolated_paths):
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=23, lot_size=10)  # lot_size>1: цена за инструмент
    monitor = monitor_with(ExecutionMonitor(FakeClient(lot=10)), pos)
    oid = "sell-comm"
    setup_close_sell(ledger, pos, oid, requested=23)
    ledger.record_sent(oid, figi="F1", ticker="TEST", side="SELL",
                       requested_lots=23, executed_lots=0, status_hint="NEW")
    # Брокер: FILL 23 лотов (230 штук), сумма исполнения 25300 ->
    # цена за инструмент 110.0; комиссия 4.75.
    client = FakeClient(order_state=FakeState(
        status_code=1, lots_executed=23, price_units=25300,
        commission=_MV(4, 750000000)), lot=10)

    assert run(main._try_resolve_absent_position(client, ledger, pos, monitor)) \
        == "ledger_close"

    assert pos.execution_price == pytest.approx(110.0)   # за 1 инструмент
    assert pos.actual_commission == pytest.approx(4.75)  # фактическая
    cur = pos.close_orders[oid]
    assert cur["avg_exec_price"] == pytest.approx(110.0)
    assert cur["commission"] == pytest.approx(4.75)
    assert pos.exit_price_confirmed is True

    run(main.process_closing(client, monitor, None))
    row = read_trades_csv(isolated_paths)[0]
    assert row["actual_commission_rub"] == "4.75"
    assert row["commission_source"] in ("actual", "mixed")
    assert row["exit_price"] == "110.0000"


# ===========================================================================
# Сценарий 9. Отсутствие фиктивного P&L для внешне закрытого остатка
# ===========================================================================

def test_09_no_fictitious_pnl_for_externally_closed_remainder(isolated_paths):
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=10)
    monitor = monitor_with(ExecutionMonitor(FakeClient()), pos)
    oid = "sell-pnl"
    setup_close_sell(ledger, pos, oid, requested=10)
    ledger.record_sent(oid, figi="F1", ticker="TEST", side="SELL",
                       requested_lots=10, executed_lots=0, status_hint="NEW")
    client = FakeClient(order_state=FakeState(
        status_code=3, lots_executed=3, price_units=330))
    assert run(main._try_resolve_absent_position(client, ledger, pos, monitor)) \
        == "ledger_close"

    run(main.process_closing(client, monitor, None))
    rows = read_trades_csv(isolated_paths)
    assert len(rows) == 1
    row = rows[0]
    # P&L рассчитан ТОЛЬКО по 3 исполненным лотам: (110-100)*3 = 30.00.
    # (10 лотов дали бы 100.00 — фиктивный P&L остатка запрещён.)
    assert row["gross_pnl_rub"] == "30.00"
    assert row["net_pnl_rub"] != ""
    # Остаток явно помечен как закрытый вне робота без P&L.
    assert "остаток 7 лот. закрыт вне робота" in row["error_note"]
    assert "P&L остатка не рассчитан" in row["error_note"]
    # Cumulative соответствует одной строке (3 лота), не 10.
    assert float(row["cumulative_net_pnl_rub"].replace(",", ".")) \
        == pytest.approx(float(row["net_pnl_rub"].replace(",", ".")))


# ===========================================================================
# Сценарий 10. B3 без собственной SELL-заявки — прежнее поведение
# ===========================================================================

def test_10_b3_external_close_without_own_sell_unchanged(isolated_paths):
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=10)
    monitor = monitor_with(ExecutionMonitor(FakeClient()), pos)
    client = FakeClient(prices={"F1": 101.5})

    # Двойное подтверждение сохранено.
    first = run(main._try_resolve_absent_position(client, ledger, pos, monitor))
    assert first == "candidate"
    assert pos.state == PositionState.OPEN
    assert pos.close_orders == {}            # фиктивный cursor не создаётся
    assert getattr(pos, "close_order_request_id", None) is None
    too_soon = run(main._try_resolve_absent_position(client, ledger, pos, monitor))
    assert too_soon == "candidate"
    assert pos.state == PositionState.OPEN
    main._external_close_candidates["F1"] = (
        datetime.now(UTC)
        - timedelta(seconds=config.RECONCILE_CONFIRM_MIN_AGE_SECONDS + 1)
    ).isoformat()
    second = run(main._try_resolve_absent_position(client, ledger, pos, monitor))
    assert second == "external_close"
    assert pos.state == PositionState.CLOSED
    assert pos.close_reason == "EXTERNAL_CLOSE"
    assert pos.exit_price_confirmed is False   # цена приблизительная
    assert pos.actual_commission is None       # фиктивная комиссия не создаётся
    assert pos.close_orders == {}              # per-order cursor не выдуман

    run(main.process_closing(client, monitor, None))
    row = read_trades_csv(isolated_paths)[0]
    # Фиктивный P&L запрещён: финансовые поля пустые.
    assert row["gross_pnl_rub"] == ""
    assert row["net_pnl_rub"] == ""
    assert row["cumulative_net_pnl_rub"] == ""
    assert "PRICE_UNKNOWN" in row["error_note"]
    assert "EXTERNAL_CLOSE" in row["error_note"]


# ===========================================================================
# Сценарий 11. Сбой синхронизации OrderLedger — безопасное состояние
# ===========================================================================

class _BrokenLedger(OrderLedger):
    """Реестр с отказывающей синхронизацией статуса (имитация сбоя записи)."""

    def record_status(self, order_id, status, **kwargs):
        raise RuntimeError("ledger sync failure (test)")


def test_11a_ledger_sync_failure_safe_state(isolated_paths):
    """Сбой синхронизации реестра НЕ отменяет брокерски подтверждённое
    закрытие, не создаёт ложных данных и оставляет безопасное состояние."""
    ledger = _BrokenLedger(str(isolated_paths / "order_ledger.jsonl"))
    ledger.load()
    pos = make_buy_pos(quantity=23)
    monitor = monitor_with(ExecutionMonitor(FakeClient()), pos)
    oid = "sell-syncfail"
    setup_close_sell(ledger, pos, oid, requested=23)
    ledger.record_sent(oid, figi="F1", ticker="TEST", side="SELL",
                       requested_lots=23, executed_lots=0, status_hint="NEW")
    client = FakeClient(order_state=FakeState(
        status_code=1, lots_executed=23, price_units=2300))

    action = run(main._try_resolve_absent_position(client, ledger, pos, monitor))

    # Учёт закрыт по ДОСТОВЕРНОМУ брокерскому отчёту (не по реестру).
    assert action == "ledger_close"
    assert pos.state == PositionState.CLOSED
    assert pos.executed_lots == 23
    assert pos.close_orders[oid]["applied_lots"] == 23
    # Сбой синхронизации: запись реестра осталась незавершённой ->
    # FIGI-блокировка сохранена (консервативно, без ложного снятия).
    assert ledger.figi_has_open_order("F1", "SELL") is True
    # CSV не пострадала (запись одна, данные из брокерского отчёта).
    run(main.process_closing(client, monitor, None))
    rows = read_trades_csv(isolated_paths)
    assert len(rows) == 1
    assert rows[0]["executed_lots"] == "23"


def test_11b_unknown_status_without_broker_answer_no_false_closed(isolated_paths):
    """Нетерминальная запись реестра + недоступный отчёт брокера ->
    позиция НЕ закрывается (без ложного CLOSED), повторная SELL запрещена."""
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=10)
    monitor = monitor_with(ExecutionMonitor(FakeClient()), pos)
    oid = "sell-unknown"
    setup_close_sell(ledger, pos, oid, requested=10, monitor=monitor)
    ledger.record_sent(oid, figi="F1", ticker="TEST", side="SELL",
                       requested_lots=10, executed_lots=5, status_hint="NEW")
    client = FakeClient(order_state=None)  # брокер не отвечает (state=None)

    action = run(main._try_resolve_absent_position(client, ledger, pos, monitor))

    assert action == "uncertain"
    assert pos.state == PositionState.UNCERTAIN
    assert client.uncertain_state is True
    assert pos.quantity == 10
    assert pos.close_orders[oid]["applied_lots"] == 0
    # Ни CSV, ни закрытия.
    run(main.process_closing(client, monitor, None))
    rows = read_trades_csv(isolated_paths)
    assert all(r["trade_id"] != pos.trade_id for r in rows) or not rows


# ===========================================================================
# Сценарий 12. Повторный reconciliation — без повторного применения и дублей
# ===========================================================================

def test_12_repeated_reconciliation_no_reapply_no_csv_duplicates(isolated_paths):
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=23)
    monitor = monitor_with(ExecutionMonitor(FakeClient()), pos)
    oid = "sell-rec"
    setup_close_sell(ledger, pos, oid, requested=23)
    ledger.record_sent(oid, figi="F1", ticker="TEST", side="SELL",
                       requested_lots=23, executed_lots=0, status_hint="NEW")
    client = FakeClient(order_state=FakeState(
        status_code=1, lots_executed=23, price_units=2300))

    # Первая сверка: B2 закрывает позицию штатно.
    run(main.reconcile(client, monitor, ledger, None))
    assert pos.state == PositionState.CLOSED
    assert pos.close_orders[oid]["applied_lots"] == 23
    assert len(pos.close_applications) == 1
    run(main.process_closing(client, monitor, None))
    assert len(read_trades_csv(isolated_paths)) == 1

    # Повторная сверка: CLOSED-позиция вне ACTIVE_STATES — B2 не вызывается.
    run(main.reconcile(client, monitor, ledger, None))
    run(main.process_closing(client, monitor, None))
    assert pos.close_orders[oid]["applied_lots"] == 23
    assert pos.close_orders[oid]["confirmed_executed_lots"] == 23
    assert len(pos.close_applications) == 1
    assert pos.executed_lots == 23
    assert pos.quantity == 0
    # Дублей CSV нет.
    assert len(read_trades_csv(isolated_paths)) == 1


# ===========================================================================
# v2.3.4-stage2. Сценарий 13 (Дефект-1). Терминальная запись реестра БЕЗ
# per-order cursor'а: B2 восстанавливает фактическую комиссию брокера
# ===========================================================================

def test_b2_terminal_ledger_record_without_cursor_recovers_broker_commission(isolated_paths):
    """Запись реестра уже полна (терминальный статус, executed_lots,
    avg_exec_price), per-order cursor в позиции отсутствует, комиссии в
    записи нет. Раньше опрос брокера не выполнялся и apply_close_execution
    получал commission=None — фактическая комиссия терялась. Теперь
    неизвестная комиссия — самостоятельное основание для запроса отчёта
    брокера; комиссия восстанавливается штатным применением."""
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=10)
    monitor = monitor_with(ExecutionMonitor(FakeClient()), pos)
    oid = "sell-ledger-comm"
    # 1-2. В реестре УЖЕ есть терминальная запись SELL с requested_lots,
    #       executed_lots и avg_exec_price.
    assert ledger.record_intent(oid, trade_id=pos.trade_id, figi=pos.figi,
                                ticker=pos.ticker, side="SELL",
                                requested_lots=10, reason="close:SL")
    backdate(ledger, oid, datetime.now(UTC) - timedelta(minutes=59))
    assert ledger.record_status(oid, "FILL", figi="F1", ticker="TEST",
                                side="SELL", requested_lots=10,
                                executed_lots=10, avg_exec_price=100.0)
    rec = ledger.latest(oid)
    assert rec["status"] == "FILL"
    assert int(rec["executed_lots"]) == 10
    assert float(rec["avg_exec_price"]) == pytest.approx(100.0)
    # 4. Фактической комиссии в записи нет.
    assert rec.get("commission") is None
    # 3. Per-order cursor в позиции отсутствует.
    assert oid not in (getattr(pos, "close_orders", {}) or {})
    # 5. Брокерский отчёт возвращает фактическую комиссию 1.25.
    client = FakeClient(order_state=FakeState(
        status_code=1, lots_executed=10, price_units=1000,
        commission=_MV(1, 250000000)))

    action = run(main._try_resolve_absent_position(client, ledger, pos, monitor))

    # 6. B2 применил исполнение штатно (apply_close_execution).
    assert action == "ledger_close"
    # Опрос брокера ВЫПОЛНЕН, несмотря на полную запись (ради комиссии).
    assert any(str(c[0]) == oid for c in client.state_calls)
    # 7. Cursor получил правильные confirmed/applied.
    cur = pos.close_orders[oid]
    assert cur["confirmed_executed_lots"] == 10
    assert cur["applied_lots"] == 10
    assert cur["status"] == "FILL"
    assert cur["avg_exec_price"] == pytest.approx(100.0)
    # 8. В cursor и позиции сохранена ФАКТИЧЕСКАЯ комиссия брокера.
    assert cur["commission"] == pytest.approx(1.25)
    assert pos.actual_commission == pytest.approx(1.25)
    assert pos.exit_price_confirmed is True
    assert pos.state == PositionState.CLOSED
    assert pos.quantity == 0
    assert len(pos.close_applications) == 1
    assert pos.executed_lots == 10
    # 9. Повторный reconcile не дублирует исполнение.
    second = run(main._try_resolve_absent_position(client, ledger, pos, monitor))
    assert second == "ledger_close"
    assert cur["applied_lots"] == 10
    assert cur["confirmed_executed_lots"] == 10
    assert cur["commission"] == pytest.approx(1.25)
    assert len(pos.close_applications) == 1
    run(main.process_closing(client, monitor, None))
    rows = read_trades_csv(isolated_paths)
    assert len(rows) == 1
    assert rows[0]["actual_commission_rub"] == "1.25"


# ===========================================================================
# v2.3.4-stage2. Сценарий 14 (Дефект-1, доп.). Комиссия, уже достоверно
# сохранённая в записи реестра, используется как есть
# ===========================================================================

def test_b2_record_commission_reused_without_broker_poll(isolated_paths):
    """Комиссия в записи: опрос брокера не требуется вовсе (запись полна —
    и статус, и цена, и комиссия), сохранённое значение попадает в cursor
    и позицию БЕЗ расчётной подстановки. Недоступный брокер не мешает."""
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=10)
    monitor = monitor_with(ExecutionMonitor(FakeClient()), pos)
    oid = "sell-ledger-comm2"
    assert ledger.record_intent(oid, trade_id=pos.trade_id, figi=pos.figi,
                                ticker=pos.ticker, side="SELL",
                                requested_lots=10, reason="close:TP")
    backdate(ledger, oid, datetime.now(UTC) - timedelta(minutes=59))
    assert ledger.record_status(oid, "FILL", figi="F1", ticker="TEST",
                                side="SELL", requested_lots=10,
                                executed_lots=10, avg_exec_price=100.0)
    # Фактическая комиссия достоверно сохранена в записи.
    ledger._latest[oid]["commission"] = 2.5
    # Брокер недоступен: корректная реализация НЕ опрашивает его вовсе.
    client = FakeClient(order_state=None)

    action = run(main._try_resolve_absent_position(client, ledger, pos, monitor))

    assert action == "ledger_close"
    # Опроса нет: в записи уже всё известно, включая комиссию.
    assert client.state_calls == []
    cur = pos.close_orders[oid]
    # Сохранённая фактическая комиссия — не расчётная (модельная для
    # оборота (100+100)*10 дала бы 0.5/3.0 при COMMISSION_PER_SIDE
    # 0.0005/0.003 — ни одно не равно 2.5).
    assert cur["commission"] == pytest.approx(2.5)
    assert pos.actual_commission == pytest.approx(2.5)
    assert cur["avg_exec_price"] == pytest.approx(100.0)
    assert pos.state == PositionState.CLOSED
    assert pos.quantity == 0


# ===========================================================================
# v2.3.4-stage2. Сценарий 15 (Дефект-2). Повтор терминального отчёта со
# СМЕНЕННЫМ статусом (CANCELLED 3/10 -> FILL 3/10) — противоречие
# ===========================================================================

def test_b2_terminal_repeat_different_status_is_contradiction(isolated_paths):
    """Первый отчёт CANCELLED 3/10 учтён; второй отчёт FILL 3/10 при том же
    исполнении ПРОТИВОРЕЧИТ зафиксированному терминальному результату.
    Совпадение количества и терминальности cursor'а не маскирует конфликт:
    UNCERTAIN, без повторного применения, без закрытия позиции."""
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=10)
    monitor = monitor_with(ExecutionMonitor(FakeClient()), pos)
    oid = "sell-rep-status"
    setup_close_sell(ledger, pos, oid, requested=10)
    ledger.record_sent(oid, figi="F1", ticker="TEST", side="SELL",
                       requested_lots=10, executed_lots=0, status_hint="NEW")
    # Первый терминальный отчёт: CANCELLED 3/10.
    first_client = FakeClient(order_state=FakeState(
        status_code=3, lots_executed=3, price_units=330,
        commission=_MV(1, 500000000)))
    assert run(main._try_resolve_absent_position(first_client, ledger, pos, monitor)) \
        == "ledger_close"
    cur = pos.close_orders[oid]
    assert cur["status"] == "CANCELLED"
    assert cur["applied_lots"] == 3
    assert cur["confirmed_executed_lots"] == 3
    assert pos.quantity == 0  # остаток закрыт внешне первой обработкой

    # Второй отчёт: статус сменился на FILL при том же исполнении 3/10.
    second_client = FakeClient(order_state=FakeState(
        status_code=1, lots_executed=3, price_units=330,
        commission=_MV(1, 500000000)))
    action = run(main._try_resolve_absent_position(second_client, ledger, pos, monitor))

    # Fail-closed: противоречие зафиксировано, учёт НЕ закрыт повторно.
    assert action == "uncertain"
    assert pos.state == PositionState.UNCERTAIN
    assert second_client.uncertain_state is True
    # Повторного применения нет: cursor заморожен на первом результате.
    assert cur["applied_lots"] == 3
    assert cur["confirmed_executed_lots"] == 3
    assert cur["status"] == "CANCELLED"       # статус второго отчёта НЕ применён
    assert cur["commission"] == pytest.approx(1.5)
    assert len(pos.close_applications) == 1
    assert pos.executed_lots == 3
    assert pos.quantity == 0                  # количество позиции не менялось
    # Диагностическое событие записано.
    events = (isolated_paths / "research_events.jsonl").read_text(encoding="utf-8")
    assert "SELL_CLOSE_REPORT_CONTRADICTION" in events
    # Позиция UNCERTAIN в CSV не пишется (без закрытия вторым отчётом).
    run(main.process_closing(second_client, monitor, None))
    assert read_trades_csv(isolated_paths) == []


# ===========================================================================
# v2.3.4-stage2. Сценарий 16 (Дефект-2). Повтор с ДРУГОЙ ценой исполнения
# (100 -> 101) при том же исполнении — противоречие
# ===========================================================================

def test_b2_terminal_repeat_different_price_is_contradiction(isolated_paths):
    """Первый терминальный отчёт с ценой 100 учтён; второй с ценой 101 при
    том же исполнении противоречит подтверждённой цене cursor'а — UNCERTAIN."""
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=10)
    monitor = monitor_with(ExecutionMonitor(FakeClient()), pos)
    oid = "sell-rep-price"
    setup_close_sell(ledger, pos, oid, requested=10)
    ledger.record_sent(oid, figi="F1", ticker="TEST", side="SELL",
                       requested_lots=10, executed_lots=0, status_hint="NEW")
    # Первый отчёт: CANCELLED 3/10 по цене 100 (300 / 3 лот. / lot=1).
    first_client = FakeClient(order_state=FakeState(
        status_code=3, lots_executed=3, price_units=300))
    assert run(main._try_resolve_absent_position(first_client, ledger, pos, monitor)) \
        == "ledger_close"
    cur = pos.close_orders[oid]
    assert cur["avg_exec_price"] == pytest.approx(100.0)
    assert cur["applied_lots"] == 3

    # Второй отчёт: та же заявка, но цена 101.
    second_client = FakeClient(order_state=FakeState(
        status_code=3, lots_executed=3, price_units=303))
    action = run(main._try_resolve_absent_position(second_client, ledger, pos, monitor))

    assert action == "uncertain"
    assert pos.state == PositionState.UNCERTAIN
    assert second_client.uncertain_state is True
    # Подтверждённая цена cursor'а НЕ перезаписана, исполнения не применены.
    assert cur["avg_exec_price"] == pytest.approx(100.0)
    assert cur["applied_lots"] == 3
    assert cur["confirmed_executed_lots"] == 3
    assert len(pos.close_applications) == 1
    assert pos.quantity == 0
    events = (isolated_paths / "research_events.jsonl").read_text(encoding="utf-8")
    assert "SELL_CLOSE_REPORT_CONTRADICTION" in events


# ===========================================================================
# v2.3.4-stage2. Сценарий 17 (Дефект-2). Повтор с ДРУГОЙ фактической
# комиссией (1.5 -> 2.0) при том же исполнении — противоречие
# ===========================================================================

def test_b2_terminal_repeat_different_commission_is_contradiction(isolated_paths):
    """Первый терминальный отчёт с фактической комиссией 1.5 учтён; второй с
    комиссией 2.0 противоречит подтверждённой комиссии cursor'а — UNCERTAIN."""
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=10)
    monitor = monitor_with(ExecutionMonitor(FakeClient()), pos)
    oid = "sell-rep-comm"
    setup_close_sell(ledger, pos, oid, requested=10)
    ledger.record_sent(oid, figi="F1", ticker="TEST", side="SELL",
                       requested_lots=10, executed_lots=0, status_hint="NEW")
    # Первый отчёт: CANCELLED 3/10, комиссия 1.5.
    first_client = FakeClient(order_state=FakeState(
        status_code=3, lots_executed=3, price_units=330,
        commission=_MV(1, 500000000)))
    assert run(main._try_resolve_absent_position(first_client, ledger, pos, monitor)) \
        == "ledger_close"
    cur = pos.close_orders[oid]
    assert cur["commission"] == pytest.approx(1.5)
    assert cur["applied_lots"] == 3

    # Второй отчёт: та же заявка/исполнение/цена, но комиссия 2.0.
    second_client = FakeClient(order_state=FakeState(
        status_code=3, lots_executed=3, price_units=330,
        commission=_MV(2, 000000000)))
    action = run(main._try_resolve_absent_position(second_client, ledger, pos, monitor))

    assert action == "uncertain"
    assert pos.state == PositionState.UNCERTAIN
    assert second_client.uncertain_state is True
    # Подтверждённая комиссия cursor'а НЕ перезаписана.
    assert cur["commission"] == pytest.approx(1.5)
    assert cur["applied_lots"] == 3
    assert cur["confirmed_executed_lots"] == 3
    assert len(pos.close_applications) == 1
    assert pos.quantity == 0
    events = (isolated_paths / "research_events.jsonl").read_text(encoding="utf-8")
    assert "SELL_CLOSE_REPORT_CONTRADICTION" in events


# ===========================================================================
# v2.3.4-stage2. Сценарий 18 (Дефект-2). Повтор БЕЗ необязательного поля
# (комиссия отсутствует в новом отчёте) — НЕ противоречие, идемпотентно
# ===========================================================================

def test_b2_terminal_repeat_missing_optional_data_is_idempotent(isolated_paths):
    """Новый отчёт не передал комиссию (отсутствующее значение), а в
    cursor'е она подтверждена. Отсутствие данных — не несовпадение двух
    достоверных значений: безопасный повтор, лоты повторно не списываются,
    частичный результат и error_note первой обработки не искажаются."""
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=10)
    monitor = monitor_with(ExecutionMonitor(FakeClient()), pos)
    oid = "sell-rep-missing"
    setup_close_sell(ledger, pos, oid, requested=10)
    ledger.record_sent(oid, figi="F1", ticker="TEST", side="SELL",
                       requested_lots=10, executed_lots=0, status_hint="NEW")
    # Первый отчёт: CANCELLED 3/10, комиссия 1.5.
    first_client = FakeClient(order_state=FakeState(
        status_code=3, lots_executed=3, price_units=330,
        commission=_MV(1, 500000000)))
    assert run(main._try_resolve_absent_position(first_client, ledger, pos, monitor)) \
        == "ledger_close"
    cur = pos.close_orders[oid]
    assert cur["commission"] == pytest.approx(1.5)
    assert pos.partial is True

    # Второй отчёт: те же статус/лоты/цена, НО без комиссии.
    second_client = FakeClient(order_state=FakeState(
        status_code=3, lots_executed=3, price_units=330))
    action = run(main._try_resolve_absent_position(second_client, ledger, pos, monitor))

    # Безопасный повтор (не противоречие).
    assert action == "ledger_close"
    assert second_client.uncertain_state is False
    # Лоты повторно не списаны; сохранённая комиссия не затёрта None.
    assert cur["applied_lots"] == 3
    assert cur["confirmed_executed_lots"] == 3
    assert cur["commission"] == pytest.approx(1.5)
    assert len(pos.close_applications) == 1
    assert pos.actual_commission == pytest.approx(1.5)
    # Частичный результат первой обработки сохранён (идемпотентность повтора).
    assert pos.partial is True
    assert "частичное исполнение SELL (3/10" in pos.error_note
    # CSV: одна строка, частичное исполнение отражено.
    run(main.process_closing(second_client, monitor, None))
    rows = read_trades_csv(isolated_paths)
    assert len(rows) == 1
    assert rows[0]["execution_status"] == "FILL_PARTIAL"
    assert "частичное исполнение SELL (3/10" in rows[0]["error_note"]


# ===========================================================================
# v2.3.4-stage2. Сценарий 19 (Дефект-2). Полностью совпадающий повторный
# терминальный отчёт — безопасный повтор
# ===========================================================================

def test_b2_terminal_repeat_exact_report_is_idempotent(isolated_paths):
    """Идентичный терминальный отчёт (статус, лоты, цена, комиссия)
    остаётся безопасным повтором: расширенная проверка идентичности не даёт
    ложных противоречий, повторного списания нет."""
    ledger = fresh_ledger(isolated_paths)
    pos = make_buy_pos(quantity=10)
    monitor = monitor_with(ExecutionMonitor(FakeClient()), pos)
    oid = "sell-rep-exact"
    setup_close_sell(ledger, pos, oid, requested=10)
    ledger.record_sent(oid, figi="F1", ticker="TEST", side="SELL",
                       requested_lots=10, executed_lots=0, status_hint="NEW")
    first_client = FakeClient(order_state=FakeState(
        status_code=3, lots_executed=3, price_units=330,
        commission=_MV(0, 500000000)))
    assert run(main._try_resolve_absent_position(first_client, ledger, pos, monitor)) \
        == "ledger_close"
    cur = pos.close_orders[oid]
    applied_after_first = cur["applied_lots"]
    history_after_first = list(pos.close_applications)

    # Полностью совпадающий второй отчёт.
    second_client = FakeClient(order_state=FakeState(
        status_code=3, lots_executed=3, price_units=330,
        commission=_MV(0, 500000000)))
    action = run(main._try_resolve_absent_position(second_client, ledger, pos, monitor))

    assert action == "ledger_close"
    assert second_client.uncertain_state is False
    assert cur["applied_lots"] == applied_after_first == 3
    assert cur["confirmed_executed_lots"] == 3
    assert cur["avg_exec_price"] == pytest.approx(110.0)
    assert cur["commission"] == pytest.approx(0.5)
    assert pos.close_applications == history_after_first  # история не выросла
    assert pos.executed_lots == 3
    assert pos.quantity == 0
    assert pos.state == PositionState.CLOSED
    assert pos.partial is True
    run(main.process_closing(second_client, monitor, None))
    assert len(read_trades_csv(isolated_paths)) == 1
