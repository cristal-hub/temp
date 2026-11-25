# test_corrective_audit_v2.py
# Tsclp_v2.1_volatile_Samsung — CORRECTIVE AUDIT V2 (исправления атомарности
# FIX-1, закрытие P0/SELL тестов, регрессия нулевой комиссии SELL).
#
# РЕЖИМ: RESEARCH ONLY. NO LIVE ORDERS. NO SANDBOX ORDERS.
# Все брокерские объекты — fake/stub, все файлы — во временных каталогах.
# Реальные state.json / order_ledger.jsonl / research_trades.csv /
# research_events.jsonl не затрагиваются (изоляция через monkeypatch).
#
# Состав:
#   FIX-1 (атомарность _enrich_buy_entry_metadata, validate→stage→commit):
#     A  test_fix1_a_save_failure_no_false_confirmation
#     B  test_fix1_b_invalid_exec_price_no_partial_mutation
#     C  test_fix1_c_invalid_commission_no_mutation
#     C2 test_fix1_c2_negative_commission_ignored_price_enriched
#     D  test_fix1_d_normal_enrichment_and_idempotent_repeat
#     E  test_fix1_e_zero_commission_is_confirmed_value
#     F  test_fix1_f_retry_after_save_failure_no_double_apply
#   FIX-3-tests (нулевая комиссия SELL после изменения _extract_commission):
#     1  test_sellzc_1_confirmed_zero_commission_stored
#     2  test_sellzc_2_positive_commission_stored
#     3  test_sellzc_3_missing_commission_stays_none
#     4  test_sellzc_4_repeat_zero_commission_report_idempotent
#     5  test_sellzc_5_late_zero_commission_after_absence_enriched_once
#     6  test_sellzc_6_zero_commission_no_infinite_repoll
#     7  test_sellzc_7_commission_not_applied_twice_pnl_stable
#     8  test_sellzc_8_extract_commission_zero_none_semantics
#   needs_poll (проверка `or ""` на числовых метаданных):
#     9  test_needspoll_zero_entry_commission_no_repoll
#     10 test_needspoll_pending_task_zero_commission_completes
#
# Запуск из корня каталога кандидата:
#   PYTHONPATH=. pytest test_corrective_audit_v2.py -v
# (PYTHONPATH обязателен: каталог кандидата содержит __init__.py, pytest
#  при importmode=prepend поднимает sys.path до родительского каталога.)

import asyncio
import csv
import json
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import logger as research_logger
import main
from execution import ExecutionMonitor, PositionState, TrackedPosition
from order_ledger import OrderLedger

# Переиспользуем проверенную инфраструктуру B2 v4 (fake-брокер, отчёты,
# CSV/events-ридеры, единая точка «позиция закрыта своей SELL, CSV записан»).
from test_b2_v4_accounting_consistency import (  # noqa: E402
    FakeClient as B2FakeClient,
    FakeState,
    ENTRY,
    LOTS,
    T_1000,
    make_closed_logged_at,
    model_commission,
    read_events as b2_read_events,
    read_trades_csv as b2_read_trades_csv,
    register_new_position,
    run,
)
# Полный FakeRM для интеграционных тестов register_executed_buy
# (calculate_sl_tp / record_trade / export_state — как в test_buy_accounting_audit).
from test_buy_accounting_audit import FakeRM as AuditFakeRM  # noqa: E402

FIGI = "BBG00CORRECTV1"
TICKER = "TEST"
OID = "fix1-oid-1"

FILL, REJECTED, CANCELLED, NEW, PARTIALLYFILL, EXPIRED = 1, 2, 3, 4, 5, 6


# ===========================================================================
# Общая изоляция
# ===========================================================================

@pytest.fixture()
def env_v2(tmp_path, monkeypatch):
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
    return b2_read_trades_csv(tmp_path)


def read_events(tmp_path):
    """Список разобранных событий research_events.jsonl."""
    out = []
    for line in b2_read_events(tmp_path):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def count_events(tmp_path, event_type):
    return sum(1 for e in read_events(tmp_path) if e.get("event") == event_type)


# ===========================================================================
# FIX-1: атомарность _enrich_buy_entry_metadata
#   (validate → stage → commit → checked save, fail-closed при ошибке)
# ===========================================================================

def make_buy_pos(figi=FIGI, state=PositionState.OPEN, trade_id="t-fix1",
                 entry=100.0, lots=10):
    """BUY-позиция без entry-метаданных (оба поля None)."""
    return TrackedPosition(
        figi=figi, ticker=TICKER, direction="BUY", entry_price=entry,
        quantity=lots, sl_price=entry * 0.98, tp_price=entry * 1.04,
        lot_size=1, state=state, trade_id=trade_id,
        price_before_order=entry, close_price_before_order=entry,
        order_send_time=datetime.now(timezone.utc).isoformat(),
    )


def make_env_with_pos(tmp_path, pos):
    """Monitor с зарегистрированной позицией (для _save_state_checked)."""
    monitor = ExecutionMonitor(B2FakeClient())
    monitor.positions[pos.figi] = pos
    return monitor


def load_state_positions(tmp_path):
    with open(tmp_path / "state.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("positions", {})


class FakeRMV2:
    def export_state(self):
        return {"fake": True}

    def import_state(self, state):
        pass


def test_fix1_a_save_failure_no_false_confirmation(env_v2, monkeypatch):
    """FIX-1/A. _save_state_checked() возвращает False:
    функция НЕ сообщает об успешном обогащении (False), значения откатены
    (память == несохранённому state.json), событие BUY_ENTRY_METADATA_
    ENRICHED не пишется (ложного подтверждения в журнале нет), реестр
    заявок не изменяется — рассинхронизации state/ledger нет."""
    tmp = env_v2
    pos = make_buy_pos()
    monitor = make_env_with_pos(tmp, pos)
    rm = FakeRMV2()
    # реестр с ранее записанным отчётом заявки — обогащение его не трогает
    ledger = OrderLedger(str(tmp / "order_ledger.jsonl"))
    ledger.load()
    assert ledger.record_sent(OID, trade_id="t-fix1", figi=FIGI, ticker=TICKER,
                              side="BUY", requested_lots=10, executed_lots=10,
                              status_hint="FILL", avg_exec_price=100.5,
                              source="post_response") is True
    monkeypatch.setattr(main, "ledger_ref", ledger)
    real_save = main._save_state
    monkeypatch.setattr(main, "_save_state", lambda m, r: False)

    ok = main._enrich_buy_entry_metadata(
        monitor, rm, pos, entry_commission=1.5, exec_price=100.5,
        order_id=OID, source="fix1-a")

    assert ok is False, "при ошибке сохранения успех сообщать запрещено"
    assert pos.entry_actual_commission is None, (
        "значение не должно оставаться применённым в памяти после "
        "неудачного сохранения (атомарность: откат)")
    assert pos.execution_price is None, "откат применённого значения"
    assert count_events(tmp, "BUY_ENTRY_METADATA_ENRICHED") == 0, (
        "событие-подтверждение обогащения при несохранённом state запрещено")
    assert count_events(tmp, "BUY_ENTRY_METADATA_SAVE_FAILED") == 1, (
        "неуспешное обогащение фиксируется диагностическим событием")
    rec = ledger.latest(OID)
    assert rec is not None and rec["status"] == "FILL", (
        "реестр заявок не изменён обогащением")
    # восстановленное хранилище подтверждает: память соответствует диску
    monkeypatch.setattr(main, "_save_state", real_save)
    assert main._save_state_checked(monitor, rm) is True
    saved = load_state_positions(tmp).get(FIGI, {})
    assert saved.get("entry_actual_commission") is None
    assert saved.get("execution_price") is None


def test_fix1_b_invalid_exec_price_no_partial_mutation(env_v2, monkeypatch):
    """FIX-1/B. Комиссия корректна, exec_price некорректен:
    частичной мутации нет — комиссия НЕ остаётся в объекте позиции,
    цена НЕ записывается, функция возвращает False."""
    tmp = env_v2
    pos = make_buy_pos()
    monitor = make_env_with_pos(tmp, pos)
    rm = FakeRMV2()

    ok = main._enrich_buy_entry_metadata(
        monitor, rm, pos, entry_commission=1.5, exec_price="не-число",
        order_id=OID, source="fix1-b")

    assert ok is False
    assert pos.entry_actual_commission is None, (
        "частичная мутация: комиссия осталась при невалидной цене")
    assert pos.execution_price is None
    # и второй вариант некорректного типа (TypeError-путь)
    ok2 = main._enrich_buy_entry_metadata(
        monitor, rm, pos, entry_commission=1.5, exec_price=object(),
        order_id=OID, source="fix1-b")
    assert ok2 is False
    assert pos.entry_actual_commission is None and pos.execution_price is None
    assert count_events(tmp, "BUY_ENTRY_METADATA_ENRICHED") == 0


def test_fix1_c_invalid_commission_no_mutation(env_v2, monkeypatch):
    """FIX-1/C. entry_commission некорректен (не интерпретируется как
    число): поля позиции не изменяются, возвращается False — включая
    случай, когда exec_price корректен (операция целиком отклонена)."""
    tmp = env_v2
    pos = make_buy_pos()
    monitor = make_env_with_pos(tmp, pos)
    rm = FakeRMV2()

    ok = main._enrich_buy_entry_metadata(
        monitor, rm, pos, entry_commission="мусор", exec_price=None,
        order_id=OID, source="fix1-c")
    assert ok is False
    assert pos.entry_actual_commission is None and pos.execution_price is None

    ok2 = main._enrich_buy_entry_metadata(
        monitor, rm, pos, entry_commission=object(), exec_price=100.5,
        order_id=OID, source="fix1-c")
    assert ok2 is False, "невалидная комиссия отклоняет операцию целиком"
    assert pos.entry_actual_commission is None, (
        "частичная мутация: цена записана при невалидной комиссии")
    assert pos.execution_price is None
    assert count_events(tmp, "BUY_ENTRY_METADATA_ENRICHED") == 0


def test_fix1_c2_negative_commission_ignored_price_enriched(env_v2):
    """FIX-1/C2 (фиксация сохранённой семантики). Отрицательная комиссия
    не является валидным значением: она игнорируется (не записывается,
    не превращается в 0/None-подмену), при этом корректная цена исполнения
    по-прежнему обогащается — прежнее поведение не изменено."""
    tmp = env_v2
    pos = make_buy_pos()
    monitor = make_env_with_pos(tmp, pos)
    rm = FakeRMV2()

    ok = main._enrich_buy_entry_metadata(
        monitor, rm, pos, entry_commission=-1.0, exec_price=100.5,
        order_id=OID, source="fix1-c2")

    assert ok is True, "корректная цена обогащается"
    assert pos.entry_actual_commission is None, (
        "отрицательная комиссия не записывается")
    assert pos.execution_price == 100.5


def test_fix1_d_normal_enrichment_and_idempotent_repeat(env_v2):
    """FIX-1/D. Корректные комиссия и цена: оба поля сохраняются,
    state.json подтверждённо записан, повторный вызов не создаёт
    дубликатов и не перезаписывает существующие значения."""
    tmp = env_v2
    pos = make_buy_pos()
    monitor = make_env_with_pos(tmp, pos)
    rm = FakeRMV2()

    ok = main._enrich_buy_entry_metadata(
        monitor, rm, pos, entry_commission=1.5, exec_price=100.5,
        order_id=OID, source="fix1-d")

    assert ok is True
    assert pos.entry_actual_commission == 1.5
    assert pos.execution_price == 100.5
    saved = load_state_positions(tmp).get(FIGI, {})
    assert saved.get("entry_actual_commission") == 1.5, (
        "значение подтверждённо сохранено в state.json")
    assert saved.get("execution_price") == 100.5
    assert count_events(tmp, "BUY_ENTRY_METADATA_ENRICHED") == 1

    # повторный вызов с теми же значениями: без изменений, без дублей
    ok2 = main._enrich_buy_entry_metadata(
        monitor, rm, pos, entry_commission=1.5, exec_price=100.5,
        order_id=OID, source="fix1-d")
    assert ok2 is False, "повтор не сообщает об обогащении"
    assert pos.entry_actual_commission == 1.5 and pos.execution_price == 100.5
    assert count_events(tmp, "BUY_ENTRY_METADATA_ENRICHED") == 1, (
        "повторное событие-дубль запрещено")
    # повторный вызов с ДРУГИМИ значениями: уже известные данные
    # не перезаписываются противоречивыми
    ok3 = main._enrich_buy_entry_metadata(
        monitor, rm, pos, entry_commission=9.9, exec_price=200.0,
        order_id=OID, source="fix1-d")
    assert ok3 is False
    assert pos.entry_actual_commission == 1.5 and pos.execution_price == 100.5


def test_fix1_e_zero_commission_is_confirmed_value(env_v2):
    """FIX-1/E. entry_commission = 0.0 — ДОСТОВЕРНОЕ реальное значение:
    сохраняется именно как подтверждённый ноль (не None, не модельная);
    повторная обработка не трактует его как отсутствие комиссии."""
    tmp = env_v2
    pos = make_buy_pos()
    monitor = make_env_with_pos(tmp, pos)
    rm = FakeRMV2()

    ok = main._enrich_buy_entry_metadata(
        monitor, rm, pos, entry_commission=0.0, exec_price=100.5,
        order_id=OID, source="fix1-e")

    assert ok is True
    assert pos.entry_actual_commission == 0.0, (
        "нулевая комиссия сохраняется как 0.0")
    assert pos.entry_actual_commission is not None
    saved = load_state_positions(tmp).get(FIGI, {})
    assert saved.get("entry_actual_commission") == 0.0, (
        "в state.json именно подтверждённый ноль")
    assert saved.get("entry_actual_commission") is not None
    events = [e for e in read_events(tmp)
              if e.get("event") == "BUY_ENTRY_METADATA_ENRICHED"]
    assert len(events) == 1 and events[0]["entry_commission"] == 0.0

    # повторная обработка: подтверждённый ноль НЕ считается отсутствием
    ok2 = main._enrich_buy_entry_metadata(
        monitor, rm, pos, entry_commission=0.0, exec_price=100.5,
        order_id=OID, source="fix1-e")
    assert ok2 is False
    assert pos.entry_actual_commission == 0.0
    # None не затирает подтверждённый ноль
    ok3 = main._enrich_buy_entry_metadata(
        monitor, rm, pos, entry_commission=None, exec_price=None,
        order_id=OID, source="fix1-e")
    assert ok3 is False
    assert pos.entry_actual_commission == 0.0


def test_fix1_f_retry_after_save_failure_no_double_apply(env_v2, monkeypatch):
    """FIX-1/F. Первая попытка сохранения завершается ошибкой (False,
    значения откатены, подтверждения нет); вторая попытка после
    восстановления хранилища применяется ровно один раз и подтверждённо
    сохраняется. Двойного применения и ложного подтверждения первой
    операции нет."""
    tmp = env_v2
    pos = make_buy_pos()
    monitor = make_env_with_pos(tmp, pos)
    rm = FakeRMV2()
    real_save = main._save_state

    monkeypatch.setattr(main, "_save_state", lambda m, r: False)
    ok1 = main._enrich_buy_entry_metadata(
        monitor, rm, pos, entry_commission=2.0, exec_price=101.0,
        order_id=OID, source="fix1-f")
    assert ok1 is False
    assert pos.entry_actual_commission is None and pos.execution_price is None, (
        "после неудачи значения откатены — повтор не задвоит применение")
    assert count_events(tmp, "BUY_ENTRY_METADATA_ENRICHED") == 0
    assert count_events(tmp, "BUY_ENTRY_METADATA_SAVE_FAILED") == 1

    # «восстановление тестового хранилища»
    monkeypatch.setattr(main, "_save_state", real_save)
    ok2 = main._enrich_buy_entry_metadata(
        monitor, rm, pos, entry_commission=2.0, exec_price=101.0,
        order_id=OID, source="fix1-f")
    assert ok2 is True
    assert pos.entry_actual_commission == 2.0 and pos.execution_price == 101.0
    saved = load_state_positions(tmp).get(FIGI, {})
    assert saved.get("entry_actual_commission") == 2.0
    assert saved.get("execution_price") == 101.0
    assert count_events(tmp, "BUY_ENTRY_METADATA_ENRICHED") == 1, (
        "подтверждение ровно одно (первая операция не «успешна» задним числом)")
    # идемпотентный третий вызов
    ok3 = main._enrich_buy_entry_metadata(
        monitor, rm, pos, entry_commission=2.0, exec_price=101.0,
        order_id=OID, source="fix1-f")
    assert ok3 is False
    assert pos.entry_actual_commission == 2.0 and pos.execution_price == 101.0
    assert count_events(tmp, "BUY_ENTRY_METADATA_ENRICHED") == 1


def test_fix1_g_caller_chain_register_return_uses_checked_save(env_v2):
    """FIX-1/G (интеграция по цепочке вызовов). Поздний отчёт той же
    BUY-заявки обогащает комиссию активной позиции через
    register_executed_buy → _enrich_buy_entry_metadata: при работающем
    хранилище обогащение подтверждено и сохранено."""
    tmp = env_v2
    ledger = OrderLedger(str(tmp / "order_ledger.jsonl"))
    ledger.load()
    client = B2FakeClient()
    monitor = ExecutionMonitor(client)
    rm = AuditFakeRM(sl=95.0, tp=110.0)
    pos = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t-fix1g", reason="unit", signal_time="",
        price_before_order=100.0, order_send_time="", requested_lots=10,
        executed_lots=10, exec_price=100.5, lot_size=1, entry_commission=None,
        partial=False, df=object(), source="audit", ledger_status="FILL"))
    assert pos.entry_actual_commission is None
    pos2 = run(main.register_executed_buy(
        client, monitor, rm, ledger, figi=FIGI, ticker=TICKER, order_id=OID,
        trade_id="t-fix1g", reason="unit", signal_time="",
        price_before_order=100.0, order_send_time="", requested_lots=10,
        executed_lots=10, exec_price=100.5, lot_size=1, entry_commission=1.5,
        partial=False, df=object(), source="audit", ledger_status="FILL"))
    assert pos2 is pos and pos2.quantity == 10, "лоты не применяются повторно"
    assert pos2.entry_actual_commission == 1.5, (
        "поздняя комиссия обогащает запись и подтверждённо сохраняется")
    saved = load_state_positions(tmp).get(FIGI, {})
    assert saved.get("entry_actual_commission") == 1.5, (
        "state.json содержит обогащённое значение")


# ===========================================================================
# FIX-3-tests: нулевая комиссия SELL (_extract_commission изменена на
# «0.0 — достоверное значение»); проверяем согласованность BUY/SELL,
# идемпотентность B2 и отсутствие повторного применения/P&L.
# ===========================================================================

def test_sellzc_1_confirmed_zero_commission_stored(env_v2):
    """SELL с подтверждённой комиссией 0.0: ноль хранится в cursor'е и
    позиции как ДОСТОВЕРНОЕ значение, в CSV пишется «0.00» (а не пустая
    строка «отсутствие данных»), commission_source отражает фактический
    ноль; net P&L рассчитан с фактическим нулём, а не модельной комиссией."""
    tmp = env_v2
    monitor, pos, client = make_closed_logged_at(
        tmp, trade_id="t-zc1", figi=FIGI, oid="sell-zc1",
        close_at=T_1000, price=110.0, commission=0.0)
    rec = pos.close_orders["sell-zc1"]
    assert rec["commission"] == 0.0 and rec["commission"] is not None, (
        "нулевая комиссия отчёта хранится как 0.0 (не None)")
    assert pos.actual_commission == 0.0 and pos.actual_commission is not None
    rows = read_trades_csv(tmp)
    assert rows[0]["actual_commission_rub"] == "0.00", (
        "подтверждённый ноль пишется как «0.00», а не как пустая строка")
    assert rows[0]["exit_commission_rub"] == "0.00"
    assert rows[0]["commission_source"] == "mixed", (
        "вход модельный, выход фактический ноль -> mixed")
    expected_net = (110.0 - ENTRY) * LOTS - (model_commission(110.0) / 2 + 0.0)
    assert rows[0]["net_pnl_rub"] == f"{expected_net:.2f}", (
        "net P&L с фактической нулевой выходной комиссией")


def test_sellzc_2_positive_commission_stored(env_v2):
    """SELL с положительной комиссией: значение сохраняется, CSV содержит
    фактическую величину, net P&L уменьшается на неё."""
    tmp = env_v2
    monitor, pos, client = make_closed_logged_at(
        tmp, trade_id="t-zc2", figi=FIGI, oid="sell-zc2",
        close_at=T_1000, price=110.0, commission=2.5)
    rec = pos.close_orders["sell-zc2"]
    assert rec["commission"] == 2.5 and pos.actual_commission == 2.5
    rows = read_trades_csv(tmp)
    assert rows[0]["actual_commission_rub"] == "2.50"
    expected_net = (110.0 - ENTRY) * LOTS - (model_commission(110.0) / 2 + 2.5)
    assert rows[0]["net_pnl_rub"] == f"{expected_net:.2f}"


def test_sellzc_3_missing_commission_stays_none(env_v2):
    """SELL с ОТСУТСТВУЮЩЕЙ комиссией (None в отчёте): None не превращается
    автоматически в ноль — cursor/позиция хранят None, CSV-строка содержит
    пустую actual_commission_rub, выходная комиссия модельная."""
    tmp = env_v2
    monitor, pos, client = make_closed_logged_at(
        tmp, trade_id="t-zc3", figi=FIGI, oid="sell-zc3",
        close_at=T_1000, price=110.0, commission=None)
    rec = pos.close_orders["sell-zc3"]
    assert rec.get("commission") is None, (
        "отсутствие данных не подменяется нулём")
    assert pos.actual_commission is None
    rows = read_trades_csv(tmp)
    assert rows[0]["actual_commission_rub"] == "", (
        "отсутствие комиссии — пустая строка (отличима от нуля «0.00»)")
    assert rows[0]["exit_commission_rub"] == f"{model_commission(110.0) / 2:.2f}"


def test_sellzc_4_repeat_zero_commission_report_idempotent(env_v2):
    """Повторное получение отчёта с нулевой комиссией: повтор ТОГО ЖЕ
    терминального отчёта (0.0 vs сохранённый 0.0) — НЕ конфликт,
    без повторного применения лотов и без изменения учтённых значений
    (идемпотентность B2 close accounting)."""
    tmp = env_v2
    monitor, pos, client = make_closed_logged_at(
        tmp, trade_id="t-zc4", figi=FIGI, oid="sell-zc4",
        close_at=T_1000, price=110.0, commission=0.0)
    rec_before = dict(pos.close_orders["sell-zc4"])
    qty_before = pos.quantity
    # повтор того же терминального отчёта
    applied = monitor.apply_close_execution(
        pos, "sell-zc4", LOTS, "CANCELLED",
        execution_price=110.0, commission=0.0, requested_lots=LOTS)
    assert applied is False, "повтор терминального отчёта не применяется"
    assert pos.quantity == qty_before, "лоты применены повторно (дефект)"
    rec = pos.close_orders["sell-zc4"]
    assert rec["commission"] == 0.0, "учтённая комиссия изменилась повтором"
    assert rec["applied_lots"] == rec_before["applied_lots"]
    assert rec["confirmed_executed_lots"] == rec_before["confirmed_executed_lots"]
    assert pos.state == PositionState.CLOSED
    assert count_events(tmp, "CSV_TRADE_ROW_UPDATED") == 0


def test_sellzc_5_late_zero_commission_after_absence_enriched_once(env_v2):
    """Позднее получение комиссии (0.0) после первоначального отсутствия:
    повторный терминальный отчёт обогащает ТОЛЬКО отсутствующее значение
    (None -> 0.0), CSV-строка обновляется атомарно (без дублирования),
    накопительный P&L пересчитывается; значения не применяются дважды."""
    tmp = env_v2
    monitor, pos, client = make_closed_logged_at(
        tmp, trade_id="t-zc5", figi=FIGI, oid="sell-zc5",
        close_at=T_1000, price=110.0, commission=None)
    rows = read_trades_csv(tmp)
    assert rows[0]["actual_commission_rub"] == ""
    net_before = rows[0]["net_pnl_rub"]
    cum_before = rows[0]["cumulative_net_pnl_rub"]

    # поздний отчёт той же заявки: комиссия стала известна (0.0)
    client._order_states["sell-zc5"] = FakeState(
        status_code=3, lots_executed=LOTS,
        price_units=110.0 * LOTS, commission=0.0)
    run(main.process_closing(client, monitor, None))

    rows = read_trades_csv(tmp)
    assert len(rows) == 1, "новых строк нет — обновляется существующая"
    assert rows[0]["actual_commission_rub"] == "0.00", (
        "поздний подтверждённый ноль записан как «0.00»")
    assert rows[0]["net_pnl_rub"] != net_before, (
        "net P&L пересчитан (фактический ноль вместо модельной)")
    expected_net = (110.0 - ENTRY) * LOTS - (model_commission(110.0) / 2 + 0.0)
    assert rows[0]["net_pnl_rub"] == f"{expected_net:.2f}"
    assert pos.actual_commission == 0.0 and pos.actual_commission is not None
    assert pos.close_orders["sell-zc5"]["commission"] == 0.0
    # идемпотентность: повторный проход с тем же отчётом ничего не меняет
    bytes_before = (tmp / "research_trades.csv").read_bytes()
    run(main.process_closing(client, monitor, None))
    assert (tmp / "research_trades.csv").read_bytes() == bytes_before, (
        "повторный отчёт не изменяет учтённые данные")


def test_sellzc_6_zero_commission_no_infinite_repoll(env_v2):
    """Нулевая комиссия не вызывает бесконечный повторный polling:
    пока фактическая комиссия неизвестна, строка опрашивается (poll #1);
    после получения подтверждённого нуля («0.00» записан в CSV) опросы
    ПРЕКРАЩАЮТСЯ — ноль трактуется как полное подтверждённое значение,
    а не как «отсутствие данных»."""
    tmp = env_v2
    monitor, pos, client = make_closed_logged_at(
        tmp, trade_id="t-zc6", figi=FIGI, oid="sell-zc6",
        close_at=T_1000, price=110.0, commission=None)
    rows = read_trades_csv(tmp)
    assert rows[0]["actual_commission_rub"] == "", (
        "исходная строка без комиссии неполна (ожидается poll)")
    calls_initial = len(client.state_calls)
    assert calls_initial >= 1, "неполная строка опрашивается"
    # поздний отчёт: комиссия стала известна — подтверждённый ноль
    client._order_states["sell-zc6"] = FakeState(
        status_code=3, lots_executed=LOTS,
        price_units=110.0 * LOTS, commission=0.0)
    run(main.process_closing(client, monitor, None))
    rows = read_trades_csv(tmp)
    assert rows[0]["actual_commission_rub"] == "0.00", (
        "подтверждённый ноль записан как «0.00»")
    calls_after_enrich = len(client.state_calls)
    assert calls_after_enrich > calls_initial, (
        "ноль получен через poll (однократно)")
    # повторные циклы: строка полна («0.00») — опросов БОЛЬШЕ НЕТ
    # (ноль не вызывает бесконечный polling)
    run(main.process_closing(client, monitor, None))
    run(main.process_closing(client, monitor, None))
    run(main.process_closing(client, monitor, None))
    assert len(client.state_calls) == calls_after_enrich, (
        "после записи «0.00» повторный polling прекращается")


def test_sellzc_7_commission_not_applied_twice_pnl_stable(env_v2):
    """Комиссия не применяется дважды: повторные отчёты/циклы восстановления
    не изменяют net P&L и накопительный P&L (значения применяются ровно
    один раз, повтор — идемпотентен)."""
    tmp = env_v2
    monitor, pos, client = make_closed_logged_at(
        tmp, trade_id="t-zc7", figi=FIGI, oid="sell-zc7",
        close_at=T_1000, price=110.0, commission=1.0)
    cum1 = research_logger.get_cumulative_net_pnl()
    rows1 = read_trades_csv(tmp)
    # повторные терминальные отчёты (тот же отчёт) и повторные циклы
    for _ in range(3):
        monitor.apply_close_execution(
            pos, "sell-zc7", LOTS, "CANCELLED",
            execution_price=110.0, commission=1.0, requested_lots=LOTS)
        run(main.process_closing(client, monitor, None))
    rows2 = read_trades_csv(tmp)
    assert len(rows2) == 1, "повторные отчёты не создают строк"
    assert rows2[0]["net_pnl_rub"] == rows1[0]["net_pnl_rub"], (
        "net P&L изменился повторами (двойное применение комиссии)")
    assert rows2[0]["exit_commission_rub"] == "1.00"
    cum2 = research_logger.get_cumulative_net_pnl()
    assert f"{cum2:.2f}" == f"{cum1:.2f}", (
        "накопительный P&L изменился без нового факта")


def test_sellzc_8_extract_commission_zero_none_semantics(env_v2):
    """Согласованная семантика _extract_commission (единая для BUY и SELL):
    0.0 — достоверное значение; отсутствие поля — None; None не превращается
    в 0.0."""
    st_zero = FakeState(status_code=3, lots_executed=10,
                        price_units=1100.0, commission=0.0)
    st_none = FakeState(status_code=3, lots_executed=10, price_units=1100.0,
                        commission=None)
    st_absent = FakeState(status_code=3, lots_executed=10,
                          price_units=1100.0, commission=None)
    st_absent.executed_commission = None
    assert ExecutionMonitor._extract_commission(st_zero) == 0.0, (
        "0.0 — подтверждённый ноль брокера")
    assert ExecutionMonitor._extract_commission(st_zero) is not None
    assert ExecutionMonitor._extract_commission(st_none) is None, (
        "None — отсутствие данных (не 0.0)")
    assert ExecutionMonitor._extract_commission(st_absent) is None
    st_pos = FakeState(status_code=3, lots_executed=10,
                       price_units=1100.0, commission=2.5)
    assert ExecutionMonitor._extract_commission(st_pos) == 2.5
    # BUY и SELL используют ОДНУ функцию (согласованность семантики)
    assert main.ExecutionMonitor._extract_commission \
        is ExecutionMonitor._extract_commission


# ===========================================================================
# needs_poll / `or ""` на числовых метаданных (ТЗ corrective audit §6):
# ноль в CSV «0.00» — truthy-строка; отсутствие — «». Проверяем отсутствие
# лишнего polling при корректно сохранённой нулевой комиссии.
# ===========================================================================

def test_needspoll_zero_entry_commission_no_repoll(env_v2):
    """BUY-позиция с ПОДТВЕРЖДЁННОЙ нулевой комиссией входа (0.0) закрыта,
    CSV-строка содержит entry_commission_rub=«0.00» и полные данные выхода:
    восстановление НЕ опрашивает брокера (ноль не превращается в пустую
    строку, лишний poll не выполняется)."""
    tmp = env_v2
    monitor = ExecutionMonitor(B2FakeClient())
    pos = TrackedPosition(
        figi=FIGI, ticker=TICKER, direction="BUY", entry_price=ENTRY,
        quantity=LOTS, sl_price=ENTRY * 0.98, tp_price=ENTRY * 1.04,
        lot_size=1, state=PositionState.OPEN, trade_id="t-np1",
        price_before_order=ENTRY, close_price_before_order=ENTRY,
        order_send_time=datetime.now(timezone.utc).isoformat(),
        entry_actual_commission=0.0,  # подтверждённый ноль входа
    )
    monitor.positions[FIGI] = pos
    monitor.add_close_order(pos, "sell-np1", LOTS)
    pos.close_order_request_id = "sell-np1"
    pos.close_requested_lots = LOTS
    assert monitor.apply_close_execution(
        pos, "sell-np1", LOTS, "CANCELLED", execution_price=110.0,
        commission=1.0, requested_lots=LOTS) is True
    client = B2FakeClient(order_states={
        "sell-np1": FakeState(status_code=3, lots_executed=LOTS,
                              price_units=110.0 * LOTS, commission=1.0)})
    run(main.process_closing(client, monitor, None))
    rows = read_trades_csv(tmp)
    assert len(rows) == 1
    assert rows[0]["entry_commission_rub"] == "0.00", (
        "подтверждённый ноль входа в CSV как «0.00»")
    calls_after_write = len(client.state_calls)
    # повторные циклы: строка полна — опросов нет (и по entry-комиссии тоже)
    run(main.process_closing(client, monitor, None))
    run(main.process_closing(client, monitor, None))
    assert len(client.state_calls) == calls_after_write, (
        "нулевая entry-комиссия не должна вызывать повторный poll "
        "(строка уже содержит «0.00»)")


def test_needspoll_pending_task_zero_commission_completes(env_v2):
    """Критерий завершения recovery-задачи (цена И фактическая комиссия
    подтверждены в строке) выполняется и для нулевой комиссии: строка с
    actual_commission_rub=«0.00» завершает задачу (ноль — не «отсутствие»)."""
    tmp = env_v2
    monitor, pos, client = make_closed_logged_at(
        tmp, trade_id="t-np2", figi=FIGI, oid="sell-np2",
        close_at=T_1000, price=110.0, commission=0.0)
    rows = read_trades_csv(tmp)
    assert rows[0]["actual_commission_rub"] == "0.00"
    # новая позиция по тому же FIGI вытесняет закрытую -> задача архивируется
    pos2 = register_new_position(monitor, FIGI, "t-np2-new")
    assert len(monitor.pending_csv_recoveries) == 1, (
        "задача архивирована при вытеснении закрытой позиции")
    # цикл восстановления: строка УЖЕ полна (0.00) — задача завершается
    # БЕЗ опроса брокера
    client2 = B2FakeClient()  # пустой: любой опрос был бы виден в state_calls
    run(main.process_closing(client2, monitor, None))
    assert monitor.pending_csv_recoveries == [], (
        "нулевая комиссия завершает задачу (не трактуется как отсутствие)")
    assert client2.state_calls == [], (
        "полная строка не опрашивается")
    assert count_events(tmp, "CSV_RECOVERY_TASK_COMPLETED") == 1
