# test_buy_accounting_audit.py
# Tsclp_v2.1_volatile_Samsung — BUY ACCOUNTING AUDIT (этап 1, каталог
# samsung_BUY_accounting_audit_v1).
#
# РЕЖИМ: RESEARCH ONLY. NO LIVE ORDERS. NO BROKER OPERATIONS.
# Все брокерские объекты — fake/stub, все файлы — во временных каталогах.
# Реальные state.json / order_ledger.jsonl / research_trades.csv не
# затрагиваются (изоляция через monkeypatch в fixture env_audit).
#
# Состав (номера сценариев ТЗ раздела 3):
#   01 test_tz01_full_buy_registers_open_position
#   02 test_tz02_repeated_terminal_report_no_reaccounting
#   03 test_tz03_partial_buy_counts_only_executed
#   04 test_tz04_multiple_partials_final_quantity_correct
#   05 test_tz05_restart_after_fill_before_position_saved
#   06 test_tz06_ledger_saved_state_missing_safe_recovery
#   07 test_tz07_state_saved_ledger_missing_safe
#   08 test_tz08_late_commission_enriches_existing_entry
#   09 test_tz09_zero_commission_distinguished_from_missing
#   10 test_tz10_late_execution_price_enriches_recovery
#   11 test_tz11_contradictory_repeat_fail_closed
#   12 test_tz12_two_orders_same_figi_not_mixed
#   13 test_tz13_two_different_figis_not_mixed
#   14 test_tz14_broker_filled_no_local_position_recovery_no_double
#   15 test_tz15_existing_recovery_not_duplicated_by_reconcile
#   16 test_tz16_state_write_error_no_false_registration_confirmation
#   17 test_tz17_ledger_write_error_no_false_confirmation
#   18 test_tz18_late_report_after_restart_idempotent
#   19 test_tz19_csv_reupdate_no_duplicates_no_history_loss
#   20 test_tz20_cumulative_recomputed_after_buy_metadata_update
#   21 test_wush_synthetic_buy495_recovery   (СИНТЕТИЧЕСКИЙ сценарий WUSH:
#        BUY 495 исполнен брокером, ledger сохранён, локальная позиция
#        отсутствует; восстановление без двойного учёта. Реальные логи
#        инцидента недоступны — сценарий полностью синтетический.)
#   22 test_ledger_identity_conflict_figi_change_fail_closed
#   23 test_ledger_price_not_wiped_by_later_record
#
# Запуск из корня каталога кандидата:
#   PYTHONPATH=. pytest test_buy_accounting_audit.py -v
# (PYTHONPATH обязателен: каталог кандидата содержит __init__.py, и pytest
#  при importmode=prepend поднимает sys.path до родительского каталога,
#  где может лежать другой main.py — затенение модуля недопустимо.)

import asyncio
import csv
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import logger as research_logger
import main
from execution import ExecutionMonitor, PositionState
from order_ledger import OrderLedger
from tinkoff_client import PositionData

FIGI = "BBG00WUSHBUY1"
FIGI2 = "BBG00WUSHBUY2"
TICKER = "WUSH"
OID = "buy-audit-oid-1"
OID_B = "buy-audit-oid-2"

# Коды статусов T-Invest (как в tests/test_p0_defect_fixes.py)
FILL, REJECTED, CANCELLED, NEW, PARTIALLYFILL, EXPIRED = 1, 2, 3, 4, 5, 6


def run(coro):
    return asyncio.run(coro)


def _Q(units, nano=0):
    return SimpleNamespace(units=units, nano=nano)


def fake_state(status_code, lots_executed=0, price_total=None,
               commission=None):
    """OrderState-подобный отчёт брокера. price_total — ДЕНЕЖНАЯ СУММА
    исполнения (executed_order_price, units): цена за лот =
    price_total / (lots_executed * lot_size). commission — float (руб)
    или None (поле отсутствует в отчёте)."""
    st = SimpleNamespace(
        execution_report_status=status_code,
        lots_executed=lots_executed,
        executed_order_price=_Q(price_total) if price_total is not None else None,
        executed_commission=None,
    )
    if commission is not None:
        units = int(commission)
        nano = int(round((float(commission) - units) * 1e9))
        st.executed_commission = _Q(units, nano)
    return st


class FakeRM:
    def __init__(self, sl=95.0, tp=110.0):
        self.sl = sl
        self.tp = tp
        self.recorded = []

    def calculate_sl_tp(self, price, direction, df):
        return self.sl, self.tp

    async def calculate_position_size(self, figi, price, df):
        return 5

    def record_trade(self, figi):
        self.recorded.append(figi)

    def export_state(self):
        return {"fake": True}

    def import_state(self, state):
        pass


class FakeClient:
    """Fake-брокер: без сети, без заявок, без операций по счёту."""

    def __init__(self, positions=None):
        self.uncertain_state = False
        self.order_states = {}
        self.positions_value = positions or {}
        self.orders_list = []
        self.cancel_calls = []
        self.instrument_info = {"lot": 1, "ticker": TICKER}

    async def get_positions(self):
        return dict(self.positions_value)

    async def get_sandbox_order_state(self, order_id, order_id_type=None):
        return self.order_states.get(str(order_id))

    async def get_instrument_info(self, figi):
        return dict(self.instrument_info)

    async def get_last_prices(self, figi_list):
        return {}

    async def get_sandbox_orders(self):
        return list(self.orders_list)

    async def cancel_order(self, order_id, order_id_type=None):
        self.cancel_calls.append(order_id)
        return object()

    async def post_market_order(self, figi, quantity, direction, order_id=None):
        return SimpleNamespace(order_id=order_id, state=None,
                               error="no orders in audit", exchange_order_id=None)

    def is_uncertain(self):
        return self.uncertain_state


def make_ledger(tmp_path):
    led = OrderLedger(str(tmp_path / "order_ledger.jsonl"))
    led.load()
    return led


def make_monitor(client=None):
    return ExecutionMonitor(client or FakeClient())


@pytest.fixture()
def env_audit(tmp_path, monkeypatch):
    """Изоляция всех файловых побочных эффектов во временный каталог."""
    monkeypatch.setattr(main, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(main, "STATE_FILE_TMP", str(tmp_path / "state.json.tmp"))
    monkeypatch.setattr(research_logger, "EVENTS_FILE",
                        str(tmp_path / "research_events.jsonl"))
    monkeypatch.setattr(research_logger, "TRADES_FILE",
                        str(tmp_path / "research_trades.csv"))
    monkeypatch.setattr(main, "_external_close_candidates", {})
    monkeypatch.setattr(main, "reconcile_done", True)
    monkeypatch.setattr(main, "state_save_failed", False)
    monkeypatch.setattr(main, "ledger_ref", None)
    yield tmp_path


def read_trades_csv(tmp_path):
    path = Path(tmp_path) / "research_trades.csv"
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def make_closed_logged(tmp_path, *, figi=FIGI, trade_id="t-closed", oid="sell-o1",
                       lots=10, entry=100.0, exit=110.0, exit_commission=None,
                       entry_actual=None):
    """BUY-позиция, закрытая своей SELL (полное исполнение), CSV записан."""
    monitor = make_monitor()
    pos = main.TrackedPosition(
        figi=figi, ticker="TEST", direction="BUY", entry_price=entry,
        quantity=lots, sl_price=entry * 0.98, tp_price=entry * 1.04,
        lot_size=1, state=PositionState.OPEN, trade_id=trade_id,
        price_before_order=entry, close_price_before_order=entry,
        order_send_time=(datetime.now(timezone.utc)).isoformat(),
        entry_actual_commission=entry_actual,
    )
    monitor.positions[figi] = pos
    monitor.add_close_order(pos, oid, lots)
    pos.close_order_request_id = oid
    pos.close_requested_lots = lots
    assert monitor.apply_close_execution(
        pos, oid, lots, "CANCELLED", execution_price=exit,
        commission=exit_commission, requested_lots=lots) is True
    assert pos.state == PositionState.CLOSED and pos.quantity == 0
    client = FakeClient()
    client.order_states = {
        oid: fake_state(CANCELLED, lots,
                        price_total=(exit * lots if exit is not None else None),
                        commission=exit_commission),
    }
    run(main.process_closing(client, monitor, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1 and rows[0]["trade_id"] == trade_id
    assert pos.logged is True
    return monitor, pos


# ============================================================
# ТЗ-1: полный BUY — исполнение подтверждено, позиция зарегистрирована
# ============================================================
def test_tz01_full_buy_registers_open_position(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    ledger.record_sent(OID, trade_id="t1", figi=FIGI, ticker=TICKER, side="BUY",
                       requested_lots=10, executed_lots=10,
                       status_hint="FILL", source="post_response")
    client = FakeClient()
    monitor = make_monitor(client)
    rm = FakeRM(sl=95.0, tp=110.0)
    pos = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=10, executed_lots=10,
        exec_price=100.5, lot_size=1, entry_commission=1.2, partial=False,
        df=object(), source="audit", ledger_status="FILL"))
    assert pos is not None and pos.state == PositionState.OPEN
    assert pos.quantity == 10 and pos.entry_price == 100.5
    assert pos.entry_order_id == OID
    assert monitor.has_active_position(FIGI)
    # state.json сохранён, реестр подтверждает регистрацию
    assert os.path.isfile(tmp / "state.json")
    rec = ledger.latest(OID)
    assert rec is not None and "позиция зарегистрирована" in (rec.get("reason") or "")
    # rm.record_trade вызван ровно один раз (без дублей)
    assert rm.recorded == [FIGI]


# ============================================================
# ТЗ-2: повтор того же терминального отчёта — повторного учёта нет
# ============================================================
def test_tz02_repeated_terminal_report_no_reaccounting(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    ledger.record_sent(OID, trade_id="t1", figi=FIGI, ticker=TICKER, side="BUY",
                       requested_lots=10, executed_lots=10, status_hint="FILL",
                       avg_exec_price=100.5, source="post_response")
    client = FakeClient()
    monitor = make_monitor(client)
    rm = FakeRM()
    pos = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=10, executed_lots=10,
        exec_price=100.5, lot_size=1, entry_commission=None, partial=False,
        df=object(), source="audit", ledger_status="FILL"))
    assert pos.state == PositionState.OPEN and pos.quantity == 10
    # повтор того же отчёта
    pos2 = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=10, executed_lots=10,
        exec_price=100.5, lot_size=1, entry_commission=None, partial=False,
        df=object(), source="audit", ledger_status="FILL"))
    assert pos2 is pos
    assert pos.quantity == 10
    assert len(monitor.positions) == 1
    assert pos.entry_applied_lots == 10


# ============================================================
# ТЗ-3: частичный BUY — учтены только фактически исполненные лоты
# ============================================================
def test_tz03_partial_buy_counts_only_executed(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    ledger.record_sent(OID, trade_id="t1", figi=FIGI, ticker=TICKER, side="BUY",
                       requested_lots=10, executed_lots=3,
                       status_hint="PARTIALLYFILL", source="post_response")
    client = FakeClient()
    monitor = make_monitor(client)
    rm = FakeRM()
    pos = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=10, executed_lots=3,
        exec_price=100.0, lot_size=1, entry_commission=None, partial=True,
        df=None, source="audit", ledger_status="PARTIALLYFILL"))
    assert pos is not None
    assert pos.quantity == 3, "в позицию идут только исполненные лоты"
    assert pos.entry_requested_lots == 10
    rec = ledger.latest(OID)
    assert int(rec.get("executed_lots") or 0) == 3


# ============================================================
# ТЗ-4: несколько частичных исполнений — итоговое количество корректно
# ============================================================
def test_tz04_multiple_partials_final_quantity_correct(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    client = FakeClient()
    monitor = make_monitor(client)
    rm = FakeRM(sl=95.0, tp=110.0)
    # 1-е частичное исполнение: 3 лота (df есть -> OPEN)
    ledger.record_sent(OID, trade_id="t1", figi=FIGI, ticker=TICKER, side="BUY",
                       requested_lots=10, executed_lots=3,
                       status_hint="PARTIALLYFILL", source="post_response")
    pos = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=10, executed_lots=3,
        exec_price=100.0, lot_size=1, entry_commission=None, partial=True,
        df=object(), source="audit", ledger_status="PARTIALLYFILL"))
    assert pos.state == PositionState.OPEN and pos.quantity == 3
    # 2-е частичное исполнение: накопительно 7 лотов
    ledger.record_sent(OID, trade_id="t1", figi=FIGI, ticker=TICKER, side="BUY",
                       requested_lots=10, executed_lots=7,
                       status_hint="PARTIALLYFILL", source="audit")
    pos = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=10, executed_lots=7,
        exec_price=100.0, lot_size=1, entry_commission=None, partial=True,
        df=object(), source="audit", ledger_status="PARTIALLYFILL"))
    assert pos.quantity == 7, "новое исполнение учтено ровно один раз"
    assert pos.entry_applied_lots == 7
    # 3-й отчёт: тот же cumulative 7 — идемпотентно
    pos = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=10, executed_lots=7,
        exec_price=100.0, lot_size=1, entry_commission=None, partial=True,
        df=object(), source="audit", ledger_status="PARTIALLYFILL"))
    assert pos.quantity == 7, "повтор того же исполнения не увеличивает позицию"
    # 4-й отчёт: терминальный FILL 10 — добавляются только новые лоты
    ledger.record_status(OID, "FILL", executed_lots=10, requested_lots=10,
                         source="audit")
    pos = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=10, executed_lots=10,
        exec_price=100.0, lot_size=1, entry_commission=None, partial=False,
        df=object(), source="audit", ledger_status="FILL"))
    assert pos.quantity == 10, "итог = сумма частичных исполнений (3+4+3)"


# ============================================================
# ТЗ-5: перезапуск после исполнения до сохранения позиции —
#       позиция восстанавливается
# ============================================================
def test_tz05_restart_after_fill_before_position_saved(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    # Крах между record_sent и регистрацией: реестр знает FILL 10,
    # позиции нет, state.json не сохранён (нет в tmp).
    ledger.record_intent(OID, trade_id="t1", figi=FIGI, ticker=TICKER,
                         side="BUY", requested_lots=10)
    ledger.record_sent(OID, trade_id="t1", figi=FIGI, ticker=TICKER, side="BUY",
                       requested_lots=10, executed_lots=10, status_hint="FILL",
                       avg_exec_price=100.5, source="post_response")
    client = FakeClient()
    client.order_states[OID] = fake_state(FILL, 10, price_total=1005.0)
    monitor = make_monitor(client)
    rm = FakeRM()
    run(main.startup_recovery(client, monitor, rm, ledger))
    assert monitor.has_active_position(FIGI), "исполнение восстановлено"
    pos = monitor.get_position(FIGI)
    assert pos.quantity == 10 and pos.entry_order_id == OID


# ============================================================
# ТЗ-6: ledger сохранён, state отсутствует — безопасное восстановление
# ============================================================
def test_tz06_ledger_saved_state_missing_safe_recovery(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    ledger.record_intent(OID, trade_id="t1", figi=FIGI, ticker=TICKER,
                         side="BUY", requested_lots=5)
    ledger.record_sent(OID, trade_id="t1", figi=FIGI, ticker=TICKER, side="BUY",
                       requested_lots=5, executed_lots=5, status_hint="FILL",
                       avg_exec_price=200.0, source="post_response")
    assert not os.path.isfile(tmp / "state.json"), "state.json отсутствует"
    client = FakeClient()
    client.order_states[OID] = fake_state(FILL, 5, price_total=1000.0)
    monitor = make_monitor(client)
    rm = FakeRM()
    run(main.startup_recovery(client, monitor, rm, ledger))
    assert monitor.has_active_position(FIGI)
    assert monitor.get_position(FIGI).quantity == 5
    # состояние сохранено немедленно после восстановления
    assert os.path.isfile(tmp / "state.json")


# ============================================================
# ТЗ-7: state сохранён, ledger отсутствует — безопасное поведение
# ============================================================
def test_tz07_state_saved_ledger_missing_safe(env_audit):
    tmp = env_audit
    client = FakeClient()
    monitor = make_monitor(client)
    rm = FakeRM()
    pos = run(main.register_executed_buy(
        client, monitor, rm, None, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=5, executed_lots=5,
        exec_price=100.0, lot_size=1, entry_commission=None, partial=False,
        df=object(), source="audit", ledger_status="FILL"))
    assert pos.state == PositionState.OPEN and pos.quantity == 5
    assert os.path.isfile(tmp / "state.json"), "state сохранён без реестра"
    # перезапуск: новый монитор + загрузка state; реестра нет вовсе
    monitor2 = make_monitor(FakeClient())
    assert main._load_state(monitor2, FakeRM()) is True
    p2 = monitor2.get_position(FIGI)
    assert p2 is not None and p2.quantity == 5, "позиция не потеряна"
    # стартовая сверка без реестра не создаёт дублей и не падает
    ledger2 = OrderLedger(str(tmp / "absent_ledger.jsonl"))
    ledger2.load()
    client2 = FakeClient()
    run(main.startup_recovery(client2, monitor2, FakeRM(), ledger2))
    assert len(monitor2.positions) == 1 and monitor2.get_position(FIGI).quantity == 5


# ============================================================
# ТЗ-8: поздняя комиссия — обновляется существующая запись
# ============================================================
def test_tz08_late_commission_enriches_existing_entry(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    ledger.record_sent(OID, trade_id="t1", figi=FIGI, ticker=TICKER, side="BUY",
                       requested_lots=10, executed_lots=10, status_hint="FILL",
                       avg_exec_price=100.5, source="post_response")
    client = FakeClient()
    monitor = make_monitor(client)
    rm = FakeRM()
    pos = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=10, executed_lots=10,
        exec_price=100.5, lot_size=1, entry_commission=None, partial=False,
        df=object(), source="audit", ledger_status="FILL"))
    assert pos.entry_actual_commission is None, "первый отчёт без комиссии"
    qty_before = pos.quantity
    # поздний отчёт той же заявки с фактической комиссией
    pos2 = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=10, executed_lots=10,
        exec_price=100.5, lot_size=1, entry_commission=1.5, partial=False,
        df=object(), source="audit", ledger_status="FILL"))
    assert pos2 is pos and pos2.quantity == qty_before
    assert pos2.entry_actual_commission == 1.5, (
        "поздняя комиссия обогащает существующую запись, а не теряется")


# ============================================================
# ТЗ-9: нулевая комиссия не трактуется как отсутствие данных
# ============================================================
def test_tz09_zero_commission_distinguished_from_missing(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    ledger.record_sent(OID, trade_id="t1", figi=FIGI, ticker=TICKER, side="BUY",
                       requested_lots=10, executed_lots=10, status_hint="FILL",
                       avg_exec_price=100.5, source="post_response")
    client = FakeClient()
    monitor = make_monitor(client)
    rm = FakeRM()
    state = fake_state(FILL, 10, price_total=1005.0, commission=0.0)
    exec_price = ExecutionMonitor._extract_price(state, 10, 1)
    commission = ExecutionMonitor._extract_commission(state)
    assert exec_price is not None
    assert commission == 0.0, (
        "commission=0 в отчёте — ДОСТОВЕРНОЕ значение, а не отсутствие данных")
    pos = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=10, executed_lots=10,
        exec_price=exec_price, lot_size=1, entry_commission=commission,
        partial=False, df=object(), source="audit", ledger_status="FILL"))
    assert pos.entry_actual_commission == 0.0, (
        "нулевая комиссия сохраняется как ноль (не None, не модельная)")
    # закрытие: commission_source отражает фактический ноль, а не модель
    monitor.add_close_order(pos, "sell-o9", 10)
    pos.close_order_request_id = "sell-o9"
    pos.close_requested_lots = 10
    assert monitor.apply_close_execution(
        pos, "sell-o9", 10, "CANCELLED", execution_price=110.0,
        commission=None, requested_lots=10) is True
    sell_state = fake_state(CANCELLED, 10, price_total=1100.0)
    client.order_states["sell-o9"] = sell_state
    run(main.process_closing(client, monitor, None))
    rows = read_trades_csv(tmp)
    assert rows, "CSV-строка записана"
    assert rows[0]["commission_source"] == "mixed", (
        "entry-комиссия фактическая (0.0), exit — модельная: source=mixed")
    assert rows[0]["entry_commission_rub"] == "0.00"


# ============================================================
# ТЗ-10: поздняя цена исполнения — обновляется существующая запись
# ============================================================
def test_tz10_late_execution_price_enriches_recovery(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    ledger.record_sent(OID, trade_id="t1", figi=FIGI, ticker=TICKER, side="BUY",
                       requested_lots=5, executed_lots=5, status_hint="FILL",
                       source="post_response")
    client = FakeClient()
    monitor = make_monitor(client)
    rm = FakeRM()
    # первый отчёт без цены -> RECOVERY с неизвестной ценой входа
    pos = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=5, executed_lots=5,
        exec_price=None, lot_size=1, entry_commission=None, partial=False,
        df=None, source="audit", ledger_status="FILL"))
    assert pos.state == PositionState.RECOVERY
    assert pos.execution_price is None
    # поздний отчёт той же заявки с ценой исполнения
    pos2 = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=5, executed_lots=5,
        exec_price=205.25, lot_size=1, entry_commission=None, partial=False,
        df=None, source="audit", ledger_status="FILL"))
    assert pos2 is pos
    assert pos2.execution_price == 205.25, (
        "поздняя цена исполнения обогащает существующую RECOVERY-запись")
    assert pos2.quantity == 5, "лоты не применяются повторно"


# ============================================================
# ТЗ-11: повторный отчёт с противоречивыми данными — fail-closed
# ============================================================
def test_tz11_contradictory_repeat_fail_closed(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    ledger.record_sent(OID, trade_id="t1", figi=FIGI, ticker=TICKER, side="BUY",
                       requested_lots=10, executed_lots=10, status_hint="FILL",
                       avg_exec_price=100.5, source="post_response")
    client = FakeClient()
    monitor = make_monitor(client)
    rm = FakeRM()
    pos = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=10, executed_lots=10,
        exec_price=100.5, lot_size=1, entry_commission=1.0, partial=False,
        df=object(), source="audit", ledger_status="FILL"))
    saved_comm = pos.entry_actual_commission
    # противоречивый повтор: та же заявка, ДРУГАЯ комиссия
    run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=10, executed_lots=10,
        exec_price=100.5, lot_size=1, entry_commission=9.9, partial=False,
        df=object(), source="audit", ledger_status="FILL"))
    assert pos.entry_actual_commission == saved_comm, (
        "подтверждённое значение не перезаписывается противоречивым")
    assert client.uncertain_state is True, (
        "противоречие фиксируется как неопределённость (fail-closed)")
    rec = ledger.latest(OID)
    assert rec is not None and rec.get("status") == "UNCERTAIN", (
        "противоречивый повтор не подтверждается реестром как учёт")


# ============================================================
# ТЗ-12: две заявки одного FIGI — учёт не смешивается
# ============================================================
def test_tz12_two_orders_same_figi_not_mixed(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    client = FakeClient()
    monitor = make_monitor(client)
    rm = FakeRM()
    # позиция по заявке A
    ledger.record_sent(OID, trade_id="t1", figi=FIGI, ticker=TICKER, side="BUY",
                       requested_lots=10, executed_lots=10, status_hint="FILL",
                       avg_exec_price=100.0, source="post_response")
    pos = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=10, executed_lots=10,
        exec_price=100.0, lot_size=1, entry_commission=None, partial=False,
        df=object(), source="audit", ledger_status="FILL"))
    # отчёт ДРУГОЙ заявки B по тому же FIGI
    ledger.record_sent(OID_B, trade_id="t2", figi=FIGI, ticker=TICKER,
                       side="BUY", requested_lots=5, executed_lots=5,
                       status_hint="FILL", avg_exec_price=101.0,
                       source="post_response")
    run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID_B,
        trade_id="t2", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=5, executed_lots=5,
        exec_price=101.0, lot_size=1, entry_commission=None, partial=False,
        df=object(), source="audit", ledger_status="FILL"))
    assert pos.quantity == 10, "исполнение чужой заявки не применено к позиции"
    assert len(monitor.positions) == 1, "дубль позиции не создан"
    assert client.uncertain_state is True, (
        "смешение заявок одного FIGI — неопределённость (fail-closed)")


# ============================================================
# ТЗ-13: два разных FIGI — позиции не смешиваются
# ============================================================
def test_tz13_two_different_figis_not_mixed(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    client = FakeClient()
    monitor = make_monitor(client)
    rm = FakeRM()
    for figi, oid, lots, price in ((FIGI, OID, 5, 100.0),
                                   (FIGI2, OID_B, 3, 50.0)):
        ledger.record_sent(oid, trade_id=f"t-{figi}", figi=figi, ticker="X",
                           side="BUY", requested_lots=lots, executed_lots=lots,
                           status_hint="FILL", avg_exec_price=price,
                           source="post_response")
        run(main.register_executed_buy(
            client, monitor, rm, ledger, figi=figi, ticker="X", order_id=oid,
            trade_id=f"t-{figi}", reason="unit", signal_time="",
            price_before_order=price, order_send_time="", requested_lots=lots,
            executed_lots=lots, exec_price=price, lot_size=1,
            entry_commission=None, partial=False, df=object(),
            source="audit", ledger_status="FILL"))
    assert len(monitor.positions) == 2
    assert monitor.get_position(FIGI).quantity == 5
    assert monitor.get_position(FIGI2).quantity == 3
    assert monitor.get_position(FIGI).entry_order_id == OID
    assert monitor.get_position(FIGI2).entry_order_id == OID_B


# ============================================================
# ТЗ-14: BUY исполнен брокером, локальной позиции нет — восстановление
#        без двойного учёта
# ============================================================
def test_tz14_broker_filled_no_local_position_recovery_no_double(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    ledger.record_intent(OID, trade_id="t1", figi=FIGI, ticker=TICKER,
                         side="BUY", requested_lots=10)
    ledger.record_sent(OID, trade_id="t1", figi=FIGI, ticker=TICKER, side="BUY",
                       requested_lots=10, executed_lots=10, status_hint="FILL",
                       avg_exec_price=100.5, source="post_response")
    client = FakeClient()
    client.order_states[OID] = fake_state(FILL, 10, price_total=1005.0)
    # брокер показывает позицию 10 лотов; локального учёта нет
    client.positions_value = {
        FIGI: PositionData(lots=10, direction="LONG", raw_shares=Decimal(10))}
    monitor = make_monitor(client)
    rm = FakeRM()
    run(main.startup_recovery(client, monitor, rm, ledger))
    assert len(monitor.positions) == 1, "ровно одна позиция"
    pos = monitor.get_position(FIGI)
    assert pos.quantity == 10 and pos.entry_order_id == OID
    # повторная сверка (reconcile) не создаёт дубль
    client2 = FakeClient(positions={
        FIGI: PositionData(lots=10, direction="LONG", raw_shares=Decimal(10))})
    run(main.reconcile(client2, monitor, ledger, rm))
    assert len(monitor.positions) == 1, "сверка не дублирует позицию"
    assert monitor.get_position(FIGI).quantity == 10


# ============================================================
# ТЗ-15: RECOVERY-позиция уже существует — повторная сверка не создаёт
#        дубль
# ============================================================
def test_tz15_existing_recovery_not_duplicated_by_reconcile(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    client = FakeClient(positions={
        FIGI: PositionData(lots=5, direction="LONG", raw_shares=Decimal(5))})
    monitor = make_monitor(client)
    rm = FakeRM()
    monitor.register_recovery(figi=FIGI, ticker=TICKER, direction="BUY",
                              quantity=5, lot_size=1,
                              recovery_source="adopted")
    run(main.reconcile(client, monitor, ledger, rm))
    assert len(monitor.positions) == 1
    assert monitor.get_position(FIGI).state == PositionState.RECOVERY
    assert monitor.get_position(FIGI).quantity == 5
    # вторая и третья сверки — по-прежнему ровно одна позиция
    for _ in range(2):
        run(main.reconcile(client, monitor, ledger, rm))
        assert len(monitor.positions) == 1, "дубль RECOVERY не создаётся"
        assert monitor.get_position(FIGI).quantity == 5


# ============================================================
# ТЗ-16: ошибка записи state — нет ложного подтверждения регистрации
# ============================================================
def test_tz16_state_write_error_no_false_registration_confirmation(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    ledger.record_sent(OID, trade_id="t1", figi=FIGI, ticker=TICKER, side="BUY",
                       requested_lots=5, executed_lots=5, status_hint="FILL",
                       avg_exec_price=100.0, source="post_response")
    client = FakeClient()
    monitor = make_monitor(client)
    rm = FakeRM()
    # STATE_FILE в несуществующем каталоге — запись state.json невозможна
    bad_state = Path(tmp) / "no_such_dir" / "state.json"
    main.STATE_FILE = str(bad_state)
    main.STATE_FILE_TMP = str(Path(tmp) / "no_such_dir" / "state.json.tmp")
    pos = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=5, executed_lots=5,
        exec_price=100.0, lot_size=1, entry_commission=None, partial=False,
        df=object(), source="audit", ledger_status="FILL"))
    assert pos is not None, "позиция создана в памяти (не потеряна)"
    rec = ledger.latest(OID)
    assert rec is not None
    assert "позиция зарегистрирована" not in (rec.get("reason") or ""), (
        "подтверждение регистрации НЕ пишется при несохранённом state.json")
    assert main.state_save_failed is True, (
        "ошибка сохранения зафиксирована (новые входы блокированы)")


# ============================================================
# ТЗ-17: ошибка записи ledger — нет ложного подтверждения учёта
# ============================================================
def test_tz17_ledger_write_error_no_false_confirmation(env_audit):
    tmp = env_audit
    # реестр заблокирован для записи: путь указывает на СУЩЕСТВУЮЩИЙ
    # каталог — open(path, "ab") поднимает IsADirectoryError, каждый append
    # возвращает False (симуляция ошибки записи ledger, без падений процесса)
    blocked_dir = Path(tmp) / "ledger_blocked"
    blocked_dir.mkdir()
    ledger = OrderLedger(str(blocked_dir))
    ledger.load()
    assert ledger.record_status(OID, "FILL", executed_lots=5) is False
    client = FakeClient()
    monitor = make_monitor(client)
    rm = FakeRM()
    pos = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=5, executed_lots=5,
        exec_price=100.0, lot_size=1, entry_commission=None, partial=False,
        df=object(), source="audit", ledger_status="FILL"))
    assert pos is not None, "регистрация позиции не теряется из-за реестра"
    assert pos.state == PositionState.OPEN and pos.quantity == 5
    assert ledger.latest(OID) is None, (
        "реестр НЕ содержит подтверждений (ничего не записано — "
        "ложного подтверждения учёта нет)")
    assert os.path.isfile(tmp / "state.json"), (
        "state.json (источник истины позиции) сохранён")


# ============================================================
# ТЗ-18: поздний отчёт после перезапуска — идемпотентная обработка
# ============================================================
def test_tz18_late_report_after_restart_idempotent(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    ledger.record_intent(OID, trade_id="t1", figi=FIGI, ticker=TICKER,
                         side="BUY", requested_lots=10)
    ledger.record_sent(OID, trade_id="t1", figi=FIGI, ticker=TICKER, side="BUY",
                       requested_lots=10, executed_lots=10, status_hint="FILL",
                       avg_exec_price=100.0, source="post_response")
    client = FakeClient()
    monitor = make_monitor(client)
    rm = FakeRM()
    pos = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t1", reason="unit", signal_time="", price_before_order=100.0,
        order_send_time="", requested_lots=10, executed_lots=10,
        exec_price=100.0, lot_size=1, entry_commission=None, partial=False,
        df=object(), source="audit", ledger_status="FILL"))
    assert pos.state == PositionState.OPEN
    # --- перезапуск: новые monitor/ledger из файлов ---
    monitor2 = make_monitor(FakeClient())
    assert main._load_state(monitor2, FakeRM()) is True
    ledger2 = make_ledger(tmp)
    assert ledger2.latest(OID) is not None
    # поздний отчёт той же заявки (повтор терминального)
    client2 = FakeClient()
    pos2 = run(main.register_executed_buy(
        client2, monitor2, FakeRM(), ledger2, figi=FIGI, ticker=TICKER,
        order_id=OID, trade_id="t1", reason="unit", signal_time="",
        price_before_order=100.0, order_send_time="", requested_lots=10,
        executed_lots=10, exec_price=100.0, lot_size=1, entry_commission=None,
        partial=False, df=object(), source="audit", ledger_status="FILL"))
    assert pos2 is not None and pos2.quantity == 10
    assert len(monitor2.positions) == 1
    assert pos2.entry_applied_lots == 10, "двойного применения нет"


# ============================================================
# ТЗ-19: повторное обновление CSV — нет дубликатов строк и потери
#        истории
# ============================================================
def test_tz19_csv_reupdate_no_duplicates_no_history_loss(env_audit):
    tmp = env_audit
    monitor, pos = make_closed_logged(tmp, trade_id="t-r19", exit=110.0,
                                      exit_commission=None)
    rows_before = read_trades_csv(tmp)
    assert len(rows_before) == 1
    raw_before = (Path(tmp) / "research_trades.csv").read_bytes()
    late_client = FakeClient()
    late_client.order_states["sell-o1"] = fake_state(
        CANCELLED, 10, price_total=1100.0, commission=1.5)
    run(main.process_closing(late_client, monitor, None))
    rows1 = read_trades_csv(tmp)
    assert len(rows1) == 1, "обновление не создаёт новую строку"
    assert rows1[0]["actual_commission_rub"] == "1.50"
    raw_after_first = (Path(tmp) / "research_trades.csv").read_bytes()
    # идемпотентный повтор восстановления
    run(main.process_closing(late_client, monitor, None))
    rows2 = read_trades_csv(tmp)
    raw_after_second = (Path(tmp) / "research_trades.csv").read_bytes()
    assert len(rows2) == 1
    assert raw_after_second == raw_after_first, (
        "повтор восстановления не меняет файл (идемпотентность)")
    assert rows2[0]["trade_id"] == "t-r19", "история (trade_id) сохранена"
    assert rows2[0]["executed_lots"] == rows_before[0]["executed_lots"], (
        "количество лотов не изменено")


# ============================================================
# ТЗ-20: пересчёт накопительного P&L после уточнения BUY-данных
# ============================================================
def test_tz20_cumulative_recomputed_after_buy_metadata_update(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    client = FakeClient()
    monitor = make_monitor(client)
    rm = FakeRM()
    # сделка 1: BUY 10 с поздней комиссией, затем закрытие с ценой
    ledger.record_sent(OID, trade_id="t-n1", figi=FIGI, ticker=TICKER,
                       side="BUY", requested_lots=10, executed_lots=10,
                       status_hint="FILL", avg_exec_price=100.0,
                       source="post_response")
    pos1 = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t-n1", reason="unit", signal_time="",
        price_before_order=100.0, order_send_time="", requested_lots=10,
        executed_lots=10, exec_price=100.0, lot_size=1, entry_commission=None,
        partial=False, df=object(), source="audit", ledger_status="FILL"))
    monitor.add_close_order(pos1, "sell-n1", 10)
    pos1.close_order_request_id = "sell-n1"
    pos1.close_requested_lots = 10
    assert monitor.apply_close_execution(
        pos1, "sell-n1", 10, "CANCELLED", execution_price=110.0,
        commission=None, requested_lots=10) is True
    # сделка 2 (другой FIGI): полная, чтобы был «последующий» cumulative
    ledger.record_sent(OID_B, trade_id="t-n2", figi=FIGI2, ticker="X",
                       side="BUY", requested_lots=5, executed_lots=5,
                       status_hint="FILL", avg_exec_price=50.0,
                       source="post_response")
    pos2 = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI2, ticker="X", order_id=OID_B,
        trade_id="t-n2", reason="unit", signal_time="",
        price_before_order=50.0, order_send_time="", requested_lots=5,
        executed_lots=5, exec_price=50.0, lot_size=1, entry_commission=None,
        partial=False, df=object(), source="audit", ledger_status="FILL"))
    monitor.add_close_order(pos2, "sell-n2", 5)
    pos2.close_order_request_id = "sell-n2"
    pos2.close_requested_lots = 5
    assert monitor.apply_close_execution(
        pos2, "sell-n2", 5, "CANCELLED", execution_price=55.0,
        commission=None, requested_lots=5) is True
    # закрываем обе: две CSV-строки с накопительным P&L
    close_client = FakeClient()
    close_client.order_states["sell-n1"] = fake_state(CANCELLED, 10,
                                                      price_total=1100.0)
    close_client.order_states["sell-n2"] = fake_state(CANCELLED, 5,
                                                      price_total=275.0)
    run(main.process_closing(close_client, monitor, None))
    rows = read_trades_csv(tmp)
    assert len(rows) == 2
    cum2_before = rows[1]["cumulative_net_pnl_rub"]
    assert rows[0]["entry_commission_rub"] != "", "entry-комиссия модельная"
    assert rows[0]["actual_commission_rub"] == ""
    # --- поздний отчёт BUY-заявки сделки 1 с фактической комиссией ---
    run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t-n1", reason="unit", signal_time="",
        price_before_order=100.0, order_send_time="", requested_lots=10,
        executed_lots=10, exec_price=100.0, lot_size=1, entry_commission=2.0,
        partial=False, df=object(), source="audit", ledger_status="FILL"))
    # recovery-цикл обновляет существующую строку и пересчитывает последующие
    run(main.process_closing(close_client, monitor, None))
    rows = read_trades_csv(tmp)
    assert len(rows) == 2, "новых строк нет — обновляется существующая"
    assert rows[0]["entry_commission_rub"] == "2.00", (
        "entry-комиссия уточнена в существующей строке")
    assert rows[0]["commission_source"] == "mixed"
    assert rows[0]["trade_id"] == "t-n1"
    assert rows[1]["cumulative_net_pnl_rub"] != cum2_before, (
        "накопительный P&L последующей сделки пересчитан")
    assert rows[1]["trade_id"] == "t-n2", "история второй сделки сохранена"


# ============================================================
# WUSH (СИНТЕТИЧЕСКИЙ): BUY 495 исполнен брокером, локальная позиция
# отсутствует, ledger и state в разных состояниях. Восстановление без
# двойного учёта; повторная сверка не создаёт дубль.
# Реальные логи инцидента недоступны — сценарий полностью синтетический.
# ============================================================
def test_wush_synthetic_buy495_recovery(env_audit):
    tmp = env_audit
    WUSH_LOTS = 495
    ledger = make_ledger(tmp)
    # 1) робот отправил BUY 495: INTENT до отправки (fail-closed контракт)
    assert ledger.record_intent(OID, trade_id="t-wush", figi=FIGI,
                                ticker=TICKER, side="BUY",
                                requested_lots=WUSH_LOTS) is True
    # 2) брокер исполнил 495; робот успел записать только SENT/FILL-отчёт
    #    и упал ДО регистрации позиции и ДО сохранения state.json
    assert ledger.record_sent(OID, trade_id="t-wush", figi=FIGI,
                              ticker=TICKER, side="BUY",
                              requested_lots=WUSH_LOTS,
                              executed_lots=WUSH_LOTS, status_hint="FILL",
                              avg_exec_price=None,  # цена не успела попасть
                              source="post_response") is True
    assert not os.path.isfile(tmp / "state.json"), "state.json не сохранён"
    # 3) перезапуск: реестр загружен, позиций нет, брокер показывает 495
    ledger.load()
    client = FakeClient()
    client.order_states[OID] = fake_state(FILL, WUSH_LOTS, price_total=None)
    client.positions_value = {
        FIGI: PositionData(lots=WUSH_LOTS, direction="LONG",
                           raw_shares=Decimal(WUSH_LOTS))}
    monitor = make_monitor(client)
    rm = FakeRM()
    run(main.startup_recovery(client, monitor, rm, ledger))
    assert monitor.has_active_position(FIGI), (
        "исполнение брокера восстановлено в учёт")
    assert len(monitor.positions) == 1, "ровно одна позиция (без дубля)"
    pos = monitor.get_position(FIGI)
    assert pos.quantity == WUSH_LOTS
    assert pos.entry_order_id == OID
    assert pos.state == PositionState.RECOVERY, (
        "цена неизвестна -> RECOVERY (без фиктивной цены входа)")
    assert pos.entry_applied_lots == WUSH_LOTS
    # 4) повторная сверка с брокером не создаёт дубль и не меняет счётчики
    client2 = FakeClient(positions={
        FIGI: PositionData(lots=WUSH_LOTS, direction="LONG",
                           raw_shares=Decimal(WUSH_LOTS))})
    run(main.reconcile(client2, monitor, ledger, rm))
    assert len(monitor.positions) == 1, "RECOVERY не дублируется сверкой"
    assert monitor.get_position(FIGI).quantity == WUSH_LOTS
    # 5) поздний повтор отчёта той же заявки после восстановления —
    #    идемпотентно, лоты не удваиваются
    client3 = FakeClient()
    run(main.register_executed_buy(
        client3, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t-wush", reason="unit", signal_time="",
        price_before_order=0.0, order_send_time="", requested_lots=WUSH_LOTS,
        executed_lots=WUSH_LOTS, exec_price=None, lot_size=1,
        entry_commission=None, partial=False, df=None, source="audit",
        ledger_status="FILL"))
    assert len(monitor.positions) == 1
    assert monitor.get_position(FIGI).quantity == WUSH_LOTS, (
        "повтор отчёта не удваивает позицию")


# ============================================================
# Доп. ТЗ-B: реестр — противоречивый FIGI в повторном отчёте той же
# заявки не перезаписывает идентичность молча (fail-closed)
# ============================================================
def test_ledger_identity_conflict_figi_change_fail_closed(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    assert ledger.record_intent(OID, trade_id="t1", figi=FIGI, ticker=TICKER,
                                side="BUY", requested_lots=5) is True
    # повторный отчёт той же заявки с ДРУГИМ FIGI
    ok = ledger.record_status(OID, "FILL", figi=FIGI2, ticker=TICKER,
                              side="BUY", requested_lots=5, executed_lots=5,
                              source="audit")
    rec = ledger.latest(OID)
    assert rec is not None
    assert rec.get("figi") == FIGI, (
        "подлинный FIGI заявки не перезаписан противоречивым отчётом")
    assert rec.get("status") == "UNCERTAIN", (
        "противоречие идентичности -> UNCERTAIN (fail-closed), "
        "а не молчаливое подтверждение")


# ============================================================
# Доп. ТЗ-E: поздний отчёт без цены не стирает ранее подтверждённую
# цену исполнения в реестре (обогащение, а не потеря метаданных)
# ============================================================
def test_ledger_price_not_wiped_by_later_record(env_audit):
    tmp = env_audit
    ledger = make_ledger(tmp)
    ledger.record_sent(OID, trade_id="t1", figi=FIGI, ticker=TICKER, side="BUY",
                       requested_lots=5, executed_lots=5, status_hint="FILL",
                       avg_exec_price=123.45, source="post_response")
    # поздний отчёт того же исполнения БЕЗ цены (статус/наблюдение)
    ledger.record_status(OID, "FILL", executed_lots=5, requested_lots=5,
                         source="poll")
    rec = ledger.latest(OID)
    assert rec.get("avg_exec_price") == 123.45, (
        "цена, подтверждённая ранее, не затирается отсутствием данных "
        "в повторном отчёте")
