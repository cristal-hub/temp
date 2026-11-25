# test_corrective_audit_v3.py
# Tsclp_v2.1_volatile_Samsung — CORRECTIVE AUDIT V3
# (Samsung Accounting Integrity Audit & Corrective V3).
#
# РЕЖИМ: RESEARCH ONLY. NO LIVE ORDERS. NO SANDBOX ORDERS.
# Все брокерские объекты — fake/stub, все файлы — во временных каталогах.
# Реальные state.json / order_ledger.jsonl / research_trades.csv /
# research_events.jsonl не затрагиваются (изоляция через monkeypatch/tmp_path).
#
# Покрываемые дефекты V3 (ТЗ §5.1, §5.3, §5.4, §5.5, §5.6, §5.8):
#
#   FIX-ZERO-PRICE (цена исполнения 0.0 против None, ТЗ §5.1):
#     1  test_v3_price_extract_zero_reported_price_is_none
#     2  test_v3_price_extract_negative_nonfinite_is_none
#     3  test_v3_ledger_missing_price_then_real_price_enriched
#     4  test_v3_ledger_legacy_zero_price_enriched_no_uncertain
#     5  test_v3_ledger_real_price_contradiction_still_fail_closed
#     6  test_v3_ledger_new_zero_price_does_not_overwrite_confirmed
#     7  test_v3_ledger_p0_scenario_partial_cancel_late_lots_no_uncertain
#     8  test_v3_ledger_repeat_terminal_report_idempotent
#   SELL/B2 совместимость (ТЗ §5.3):
#     9  test_v3_sell_zero_price_then_real_price_no_uncertain
#     10 test_v3_sell_cursor_zero_price_not_stored_b2_semantics
#   Нулевая комиссия (ТЗ §5.5 — 0.0 остаётся подтверждённым значением):
#     11 test_v3_ledger_commission_zero_is_confirmed_contradiction_fail_closed
#     12 test_v3_ledger_commission_none_keeps_old_zero
#   NaN / Infinity (ТЗ §5.4):
#     13 test_v3_enrich_inf_commission_rejected_no_mutation
#     14 test_v3_enrich_nan_price_rejected_no_mutation
#     15 test_v3_enrich_inf_price_rejected_no_mutation
#     16 test_v3_enrich_nonfinite_does_not_break_next_valid_call
#     17 test_v3_extract_commission_nonfinite_is_none_zero_kept
#
# Интеграционное воспроизведение дефекта §5.14 — корневой тест
# test_p0_batch2_late_execution.py::test_integration_trading_cycle_
# partial_cancel_recovery_open_late_lots (на baseline падал с
# «UNCERTAIN вместо CANCELLED», после V3-исправлений проходит).
#
# Запуск из корня каталога кандидата:
#   PYTHONPATH=. pytest test_corrective_audit_v3.py -v

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main
from execution import ExecutionMonitor, PositionState, TrackedPosition
from order_ledger import OrderLedger, STATUS_CANCELLED, STATUS_UNCERTAIN

# Проверенная инфраструктура предыдущих итераций (fake-брокер, отчёты).
from test_b2_v4_accounting_consistency import (  # noqa: E402
    FakeState,
    _MV,
)

FIGI = "BBG00CORRECTV3"
TICKER = "TESTV3"
OID = "v3-oid-1"

FILL, REJECTED, CANCELLED, NEW, PARTIALLYFILL, EXPIRED = 1, 2, 3, 4, 5, 6


# ===========================================================================
# Общая изоляция
# ===========================================================================

@pytest.fixture()
def env_v3(tmp_path, monkeypatch):
    """Изоляция всех файловых побочных эффектов во временный каталог."""
    import logger as research_logger
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


def make_ledger(tmp_path):
    ledger = OrderLedger(str(tmp_path / "order_ledger.jsonl"))
    ledger.load()
    return ledger


def make_intent(ledger, oid=OID, side="BUY", lots=10):
    assert ledger.record_intent(oid, trade_id="t-v3", figi=FIGI,
                                ticker=TICKER, side=side,
                                requested_lots=lots)


# ===========================================================================
# FIX-ZERO-PRICE: _extract_price (ТЗ §5.1 — источник дефекта)
# ===========================================================================

def test_v3_price_extract_zero_reported_price_is_none():
    """Нулевая сообщённая цена (executed_order_price=0 при lots_executed>0)
    — это ОТСУТСТВИЕ цены (None), а не подтверждённая стоимость 0.0.
    Прежнее поведение возвращало 0.0: реестр закреплял «подтверждённую
    нулевую цену», и поздняя реальная цена вызывала ложный UNCERTAIN
    (воспроизведено трассировкой V3 на baseline)."""
    st = FakeState(status_code=CANCELLED, lots_executed=2, price_units=0.0)
    assert ExecutionMonitor._extract_price(st, 2, 1) is None
    # присутствующая реальная цена по-прежнему извлекается
    st2 = FakeState(status_code=CANCELLED, lots_executed=2, price_units=200.0)
    assert ExecutionMonitor._extract_price(st2, 2, 1) == pytest.approx(100.0)


def test_v3_price_extract_negative_nonfinite_is_none():
    """Отрицательная и неконечная расчётная цена — не цена исполнения."""
    st = FakeState(status_code=CANCELLED, lots_executed=2, price_units=-100.0)
    assert ExecutionMonitor._extract_price(st, 2, 1) is None
    st2 = FakeState(status_code=CANCELLED, lots_executed=2, price_units=None)
    st2.executed_order_price = _MV(float("inf"))
    assert ExecutionMonitor._extract_price(st2, 2, 1) is None
    st3 = FakeState(status_code=CANCELLED, lots_executed=2, price_units=None)
    st3.executed_order_price = _MV(float("nan"))
    assert ExecutionMonitor._extract_price(st3, 2, 1) is None


# ===========================================================================
# FIX-ZERO-PRICE: metadata-guard реестра (ТЗ §5.1, §5.8)
# ===========================================================================

def test_v3_ledger_missing_price_then_real_price_enriched(env_v3):
    """Отчёт без цены (avg=None) не закрепляет 0.0; поздний терминальный
    отчёт с реальной ценой обогащает запись — статус остаётся CANCELLED,
    ложного UNCERTAIN нет (ТЗ §5.1: «поздняя реальная цена должна
    обогащать существующую запись»)."""
    ledger = make_ledger(env_v3)
    make_intent(ledger, lots=10)
    assert ledger.record_status(OID, STATUS_CANCELLED, executed_lots=2,
                                avg_exec_price=None) is True
    rec1 = ledger.latest(OID)
    assert rec1["status"] == STATUS_CANCELLED
    assert rec1.get("avg_exec_price") is None
    assert ledger.record_status(OID, STATUS_CANCELLED, executed_lots=2,
                                avg_exec_price=100.0) is True
    rec2 = ledger.latest(OID)
    assert rec2["status"] == STATUS_CANCELLED, (
        "поздняя реальная цена не должна вызывать UNCERTAIN")
    assert rec2["avg_exec_price"] == pytest.approx(100.0)


def test_v3_ledger_legacy_zero_price_enriched_no_uncertain(env_v3):
    """Legacy-запись с avg_exec_price=0.0 (записанная прежней версией кода)
    НЕ является подтверждённой ценой: поздняя реальная цена обогащает
    запись без ложного конфликта. Защита от настоящих противоречий
    (два РАЗНЫХ достоверных значения) не ослабляется — см. тест 5."""
    ledger = make_ledger(env_v3)
    make_intent(ledger, lots=10)
    # имитация legacy-записи прежней версии (0.0 записан как «цена»)
    assert ledger.record_status(OID, STATUS_CANCELLED, executed_lots=2,
                                avg_exec_price=0.0) is True
    assert ledger.record_status(OID, STATUS_CANCELLED, executed_lots=5,
                                avg_exec_price=100.0) is True
    rec = ledger.latest(OID)
    assert rec["status"] == STATUS_CANCELLED, (
        "переход legacy 0.0 -> реальная цена не является противоречием")
    assert rec["avg_exec_price"] == pytest.approx(100.0)
    assert rec["executed_lots"] == 5


def test_v3_ledger_real_price_contradiction_still_fail_closed(env_v3):
    """Настоящее противоречие двух ДОСТОВЕРНЫХ цен на терминальной заявке
    (100.0 -> 200.0) по-прежнему fail-closed: UNCERTAIN, прежнее значение
    сохранено, блокировка действует. Защита реестра НЕ ослаблена."""
    ledger = make_ledger(env_v3)
    make_intent(ledger, lots=10)
    assert ledger.record_status(OID, STATUS_CANCELLED, executed_lots=5,
                                avg_exec_price=100.0) is True
    assert ledger.record_status(OID, STATUS_CANCELLED, executed_lots=5,
                                avg_exec_price=200.0) is True
    rec = ledger.latest(OID)
    assert rec["status"] == STATUS_UNCERTAIN
    assert rec["avg_exec_price"] == pytest.approx(100.0), (
        "при конфликте сохраняется прежнее достоверное значение")
    assert ledger.figi_blocks_buy(FIGI)


def test_v3_ledger_new_zero_price_does_not_overwrite_confirmed(env_v3):
    """Повторный отчёт с нулевой ценой не затирает подтверждённую 100.0
    и не является противоречием (0.0 — не цена, а отсутствие данных)."""
    ledger = make_ledger(env_v3)
    make_intent(ledger, lots=10)
    assert ledger.record_status(OID, STATUS_CANCELLED, executed_lots=5,
                                avg_exec_price=100.0) is True
    assert ledger.record_status(OID, STATUS_CANCELLED, executed_lots=5,
                                avg_exec_price=0.0) is True
    rec = ledger.latest(OID)
    assert rec["status"] == STATUS_CANCELLED
    assert rec["avg_exec_price"] == pytest.approx(100.0)


def test_v3_ledger_p0_scenario_partial_cancel_late_lots_no_uncertain(env_v3):
    """Сценарий ТЗ §5.14 на уровне реестра: частичное исполнение 2 лота ->
    CANCELLED без цены -> поздний рост до 5 лотов со средней ценой 100 ->
    все 5 лотов учтены ровно один раз, статус CANCELLED (не UNCERTAIN),
    повторный отчёт идемпотентен."""
    ledger = make_ledger(env_v3)
    make_intent(ledger, lots=5)
    # частичное исполнение при отправке (цены нет)
    assert ledger.record_status(OID, "PARTIALLYFILL", executed_lots=2,
                                avg_exec_price=None) is True
    # терминальный CANCELLED, цена отсутствует (брокер вернул 0)
    assert ledger.record_status(OID, STATUS_CANCELLED, executed_lots=2,
                                avg_exec_price=None) is True
    # поздний отчёт: cumulative 5 лотов, средняя цена 100
    assert ledger.record_status(OID, STATUS_CANCELLED, executed_lots=5,
                                avg_exec_price=100.0) is True
    rec = ledger.latest(OID)
    assert rec["status"] == STATUS_CANCELLED
    assert rec["executed_lots"] == 5
    assert rec["avg_exec_price"] == pytest.approx(100.0)
    # повторная сверка / повторный отчёт — дубликатов и смен статуса нет
    assert ledger.record_status(OID, STATUS_CANCELLED, executed_lots=5,
                                avg_exec_price=100.0) is True
    rec2 = ledger.latest(OID)
    assert rec2["status"] == STATUS_CANCELLED
    assert rec2["executed_lots"] == 5
    assert rec2["avg_exec_price"] == pytest.approx(100.0)


def test_v3_ledger_repeat_terminal_report_idempotent(env_v3):
    """Повтор одинакового терминального отчёта (FILL) не меняет итоговый
    учёт (ТЗ §5.6: идемпотентность повторного FILLED/CANCELLED)."""
    ledger = make_ledger(env_v3)
    make_intent(ledger, lots=5)
    assert ledger.record_status(OID, "FILL", executed_lots=5,
                                avg_exec_price=100.0,
                                commission=1.5) is True
    assert ledger.record_status(OID, "FILL", executed_lots=5,
                                avg_exec_price=100.0,
                                commission=1.5) is True
    rec = ledger.latest(OID)
    assert rec["status"] == "FILL"
    assert rec["avg_exec_price"] == pytest.approx(100.0)
    assert rec["commission"] == pytest.approx(1.5)


# ===========================================================================
# SELL/B2 совместимость (ТЗ §5.3)
# ===========================================================================

def test_v3_sell_zero_price_then_real_price_no_uncertain(env_v3):
    """Зеркальный SELL-сценарий: legacy 0.0 в avg_exec_price SELL-записи
    не вызывает ложный UNCERTAIN при поздней реальной цене."""
    ledger = make_ledger(env_v3)
    make_intent(ledger, side="SELL", lots=5)
    assert ledger.record_status(OID, STATUS_CANCELLED, executed_lots=2,
                                avg_exec_price=0.0) is True
    assert ledger.record_status(OID, STATUS_CANCELLED, executed_lots=5,
                                avg_exec_price=110.0) is True
    rec = ledger.latest(OID)
    assert rec["status"] == STATUS_CANCELLED
    assert rec["avg_exec_price"] == pytest.approx(110.0)


def test_v3_sell_cursor_zero_price_not_stored_b2_semantics():
    """B2 apply_close_execution: нулевая цена НЕ сохраняется в per-order
    cursor (семантика B2 не изменялась V3: цена > 0 — единственное
    условие записи в курсор; отсутствие цены не подменяется нулём)."""
    from execution import ExecutionMonitor as EM

    class C:
        async def get_sandbox_order_state(self, oid, order_id_type=None):
            return None

    m = EM(C())
    p = m.register(
        figi="FIGISELL", ticker="SELLT", direction="BUY", entry_price=100.0,
        quantity=10, sl_price=95.0, tp_price=110.0, lot_size=1,
        trade_id="T1", entry_order_id="BUY1", entry_requested_lots=10,
        entry_applied_lots=10, executed_lots=10,
    )
    m.add_close_order(p, "SELL1", 10)
    p.close_order_id = "SELL1"
    p.close_requested_lots = 10
    p.state = PositionState.CLOSING
    # терминальный отчёт SELL с нулевой ценой: лоты применяются,
    # цена в cursor НЕ попадает (0.0 не является ценой)
    assert m.apply_close_execution(p, "SELL1", 10, "FILL",
                                   execution_price=0.0,
                                   commission=None, requested_lots=10) is True
    cur = p.close_orders["SELL1"]
    assert cur["avg_exec_price"] in (None,) or cur["avg_exec_price"] > 0, (
        "B2 cursor не должен хранить 0.0 как подтверждённую цену")
    assert p.quantity == 0


# ===========================================================================
# Нулевая комиссия (ТЗ §5.5 — 0.0 остаётся подтверждённым значением)
# ===========================================================================

def test_v3_ledger_commission_zero_is_confirmed_contradiction_fail_closed(env_v3):
    """0.0-комиссия — ДОСТОВЕРНОЕ значение: конфликт 0.0 -> 5.0 на
    терминальной заявке остаётся fail-closed (семантика BUY AUDIT v1
    FIX-3 не ослаблена V3)."""
    ledger = make_ledger(env_v3)
    make_intent(ledger, lots=5)
    assert ledger.record_status(OID, STATUS_CANCELLED, executed_lots=5,
                                avg_exec_price=100.0, commission=0.0) is True
    assert ledger.record_status(OID, STATUS_CANCELLED, executed_lots=5,
                                avg_exec_price=100.0, commission=5.0) is True
    rec = ledger.latest(OID)
    assert rec["status"] == STATUS_UNCERTAIN
    assert rec["commission"] == pytest.approx(0.0), (
        "при конфликте сохраняется прежнее достоверное значение (0.0)")


def test_v3_ledger_commission_none_keeps_old_zero(env_v3):
    """Отсутствие комиссии в повторном отчёте не затирает подтверждённый
    ноль 0.0 и не создаёт конфликт."""
    ledger = make_ledger(env_v3)
    make_intent(ledger, lots=5)
    assert ledger.record_status(OID, STATUS_CANCELLED, executed_lots=5,
                                avg_exec_price=100.0, commission=0.0) is True
    assert ledger.record_status(OID, STATUS_CANCELLED, executed_lots=5,
                                avg_exec_price=100.0, commission=None) is True
    rec = ledger.latest(OID)
    assert rec["status"] == STATUS_CANCELLED
    assert rec["commission"] == pytest.approx(0.0)


# ===========================================================================
# NaN / Infinity (ТЗ §5.4)
# ===========================================================================

class _FakeRMV3:
    def export_state(self):
        return {"fake": True}

    def import_state(self, state):
        pass


def _make_buy_pos(figi=FIGI, entry=100.0, lots=10):
    from datetime import datetime, timezone
    return TrackedPosition(
        figi=figi, ticker=TICKER, direction="BUY", entry_price=entry,
        quantity=lots, sl_price=entry * 0.98, tp_price=entry * 1.04,
        lot_size=1, state=PositionState.OPEN, trade_id="t-v3",
        price_before_order=entry, close_price_before_order=entry,
        order_send_time=datetime.now(timezone.utc).isoformat(),
    )


def _enrich_rejects(env_v3, monkeypatch, *, entry_commission, exec_price):
    """Общий сценарий: невалидное значение -> False без мутации объекта."""
    from execution import ExecutionMonitor as EM

    class C:
        async def get_sandbox_order_state(self, oid, order_id_type=None):
            return None

    pos = _make_buy_pos()
    monitor = EM(C())
    monitor.positions[pos.figi] = pos
    monkeypatch.setattr(main, "_save_state", lambda m, r: True)
    ok = main._enrich_buy_entry_metadata(
        monitor, _FakeRMV3(), pos, entry_commission=entry_commission,
        exec_price=exec_price, order_id=OID, source="v3")
    assert ok is False
    assert pos.entry_actual_commission is None, "частичная мутация запрещена"
    assert pos.execution_price is None, "частичная мутация запрещена"


def test_v3_enrich_inf_commission_rejected_no_mutation(env_v3, monkeypatch):
    """+Infinity в комиссии: операция ЦЕЛИКОМ неудачна, объект не изменён,
    невалидное значение не попадает в State (ТЗ §5.4)."""
    _enrich_rejects(env_v3, monkeypatch,
                    entry_commission=float("inf"), exec_price=100.5)


def test_v3_enrich_nan_price_rejected_no_mutation(env_v3, monkeypatch):
    """NaN в цене исполнения: операция ЦЕЛИКОМ неудачна, объект не изменён."""
    _enrich_rejects(env_v3, monkeypatch,
                    entry_commission=1.5, exec_price=float("nan"))


def test_v3_enrich_inf_price_rejected_no_mutation(env_v3, monkeypatch):
    """+Infinity в цене исполнения: операция ЦЕЛИКОМ неудачна, объект
    не изменён (прежде inf проходил проверку > 0)."""
    _enrich_rejects(env_v3, monkeypatch,
                    entry_commission=None, exec_price=float("inf"))


def test_v3_enrich_nonfinite_does_not_break_next_valid_call(env_v3, monkeypatch):
    """После невалидного вызова штатный вызов с корректными значениями
    работает и сохраняет данные (функция stateless, отката мусора нет)."""
    from execution import ExecutionMonitor as EM

    class C:
        async def get_sandbox_order_state(self, oid, order_id_type=None):
            return None

    pos = _make_buy_pos()
    monitor = EM(C())
    monitor.positions[pos.figi] = pos
    monkeypatch.setattr(main, "_save_state", lambda m, r: True)
    assert main._enrich_buy_entry_metadata(
        monitor, _FakeRMV3(), pos, entry_commission=float("inf"),
        exec_price=100.5, order_id=OID, source="v3") is False
    assert main._enrich_buy_entry_metadata(
        monitor, _FakeRMV3(), pos, entry_commission=1.5,
        exec_price=100.5, order_id=OID, source="v3") is True
    assert pos.entry_actual_commission == pytest.approx(1.5)
    assert pos.execution_price == pytest.approx(100.5)


def test_v3_extract_commission_nonfinite_is_none_zero_kept():
    """_extract_commission: NaN/±Inf -> None (отсутствие подтверждённого
    значения); 0.0 — подтверждённый ноль, None не подменяет его."""
    st = FakeState(status_code=FILL, lots_executed=5, price_units=500.0,
                   commission=0.0)
    assert ExecutionMonitor._extract_commission(st) == 0.0
    st2 = FakeState(status_code=FILL, lots_executed=5, price_units=500.0)
    st2.executed_commission = _MV(float("inf"))
    assert ExecutionMonitor._extract_commission(st2) is None
    st3 = FakeState(status_code=FILL, lots_executed=5, price_units=500.0)
    st3.executed_commission = _MV(float("nan"))
    assert ExecutionMonitor._extract_commission(st3) is None
    st4 = FakeState(status_code=FILL, lots_executed=5, price_units=500.0,
                    commission=None)
    assert ExecutionMonitor._extract_commission(st4) is None
