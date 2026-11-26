# test_v4_order_ledger_first_append.py
# V4 (ТЗ §2): P1 — валидация финансовых значений при ПЕРВОЙ записи реестра.
#
# Дефект V3: проверки _valid_execution_price/_valid_commission выполнялись
# только внутри ветки `if prev is not None:` в OrderLedger.append(). Первая
# запись ордера (prev is None) обходила их: avg_exec_price=0.0/отрицательная/
# NaN/±Inf и отрицательная/NaN/±Inf комиссия попадали в журнал как
# «подтверждённые».
#
# Исправление V4: валидация выполняется ДО ветвления по prev и действует
# единообразно для всех входных путей (record_sent/record_status/
# record_uncertain/record_observation + повторная загрузка/восстановление).
#
# Каждый тест проверяет не только возвращаемое значение, но и ФАКТИЧЕСКОЕ
# содержимое сохранённого журнала (JSONL) и/или состояние после load().
# Все runtime-файлы — только в tmp_path (изоляция, ТЗ §5).

import json
import math
import os

import pytest

from order_ledger import OrderLedger


def _read_status_records(path):
    """Все ORDER_STATUS-записи сохранённого журнала (в порядке записи)."""
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()
                and json.loads(line).get("record_type") == "ORDER_STATUS"]


def _first_record(path):
    recs = _read_status_records(path)
    assert recs, "журнал пуст: первая запись не сохранена"
    return recs[0]


def _last_record(path):
    recs = _read_status_records(path)
    assert recs, "журнал пуст"
    return recs[-1]


def _mk(tmp_path):
    return OrderLedger(str(tmp_path / "order_ledger.jsonl"))


def _first_append(ledger, **overrides):
    """Первая запись ордера штатным production-путём record_status()."""
    params = dict(
        trade_id="t-1", figi="BBG000000000", ticker="TEST", side="BUY",
        requested_lots=5, executed_lots=2,
        avg_exec_price=None, commission=None, source="test",
    )
    params.update(overrides)
    oid = "order-first-1"
    return oid, ledger.record_status(oid, params.pop("status", "PARTIALLYFILL"), **params)


# ---------------------------------------------------------------------
# 1-5. Цена исполнения: невалидные значения при первой записи
# ---------------------------------------------------------------------

def test_first_append_zero_price_not_recorded_as_confirmed(tmp_path):
    """(1) avg_exec_price=0.0 при первой записи: 0.0 не «подтверждённая цена»."""
    ledger = _mk(tmp_path)
    path = ledger.path
    oid, ok = _first_append(ledger, avg_exec_price=0.0)
    assert ok is True
    rec = ledger.latest(oid)
    assert rec["avg_exec_price"] is None
    saved = _first_record(path)
    assert saved["avg_exec_price"] is None


def test_first_append_negative_price_rejected(tmp_path):
    """(2) отрицательная цена при первой записи не записывается."""
    ledger = _mk(tmp_path)
    oid, ok = _first_append(ledger, avg_exec_price=-100.0)
    assert ok is True
    assert ledger.latest(oid)["avg_exec_price"] is None
    assert _first_record(ledger.path)["avg_exec_price"] is None


def test_first_append_nan_price_rejected(tmp_path):
    """(3) NaN-цена при первой записи не записывается."""
    ledger = _mk(tmp_path)
    oid, ok = _first_append(ledger, avg_exec_price=float("nan"))
    assert ok is True
    assert ledger.latest(oid)["avg_exec_price"] is None
    saved = _first_record(ledger.path)
    assert saved["avg_exec_price"] is None
    # NaN не должен присутствовать в журнале даже как литерал NaN
    raw = open(ledger.path, "r", encoding="utf-8").read()
    assert "NaN" not in raw


def test_first_append_plus_inf_price_rejected(tmp_path):
    """(4) +Infinity-цена при первой записи не записывается."""
    ledger = _mk(tmp_path)
    oid, ok = _first_append(ledger, avg_exec_price=float("inf"))
    assert ok is True
    assert ledger.latest(oid)["avg_exec_price"] is None
    assert _first_record(ledger.path)["avg_exec_price"] is None


def test_first_append_minus_inf_price_rejected(tmp_path):
    """(5) -Infinity-цена при первой записи не записывается."""
    ledger = _mk(tmp_path)
    oid, ok = _first_append(ledger, avg_exec_price=float("-inf"))
    assert ok is True
    assert ledger.latest(oid)["avg_exec_price"] is None
    assert _first_record(ledger.path)["avg_exec_price"] is None


# ---------------------------------------------------------------------
# 6-8. Комиссия: невалидные значения при первой записи
# ---------------------------------------------------------------------

def test_first_append_negative_commission_rejected(tmp_path):
    """(6) отрицательная комиссия при первой записи не записывается."""
    ledger = _mk(tmp_path)
    oid, ok = _first_append(ledger, commission=-0.01)
    assert ok is True
    assert ledger.latest(oid)["commission"] is None
    assert _first_record(ledger.path)["commission"] is None


def test_first_append_nan_commission_rejected(tmp_path):
    """(7) NaN-комиссия при первой записи не записывается."""
    ledger = _mk(tmp_path)
    oid, ok = _first_append(ledger, commission=float("nan"))
    assert ok is True
    assert ledger.latest(oid)["commission"] is None
    raw = open(ledger.path, "r", encoding="utf-8").read()
    assert "NaN" not in raw


def test_first_append_inf_commission_rejected(tmp_path):
    """(8) бесконечная комиссия (+Inf и -Inf) при первой записи не записывается."""
    ledger = _mk(tmp_path)
    oid1, ok1 = _first_append(ledger, commission=float("inf"))
    oid2 = "order-first-2"
    ok2 = ledger.record_status(oid2, "PARTIALLYFILL", trade_id="t-2",
                               figi="BBG000000000", ticker="TEST", side="BUY",
                               requested_lots=5, executed_lots=2,
                               commission=float("-inf"), source="test")
    assert ok1 is True and ok2 is True
    assert ledger.latest(oid1)["commission"] is None
    assert ledger.latest(oid2)["commission"] is None
    raw = open(ledger.path, "r", encoding="utf-8").read()
    assert "Infinity" not in raw


# ---------------------------------------------------------------------
# 9-11. Валидные значения при первой записи сохраняются как есть
# ---------------------------------------------------------------------

def test_first_append_zero_commission_is_valid_and_persisted(tmp_path):
    """(9) commission=0.0 при первой записи — ДОСТОВЕРНЫЙ ноль, не пустота."""
    ledger = _mk(tmp_path)
    oid, ok = _first_append(ledger, commission=0.0)
    assert ok is True
    rec = ledger.latest(oid)
    assert rec["commission"] == 0.0
    saved = _first_record(ledger.path)
    assert saved["commission"] == 0.0
    # 0.0 не превращается в отсутствие значения
    assert saved["commission"] is not None


def test_first_append_price_none_is_legitimate_absence(tmp_path):
    """(10) avg_exec_price=None при первой записи — легитимное отсутствие."""
    ledger = _mk(tmp_path)
    oid, ok = _first_append(ledger, avg_exec_price=None)
    assert ok is True
    rec = ledger.latest(oid)
    assert rec["avg_exec_price"] is None
    assert rec["status"] == "PARTIALLYFILL"
    assert rec["executed_lots"] == 2
    assert _first_record(ledger.path)["avg_exec_price"] is None


def test_first_append_valid_price_and_commission_persisted(tmp_path):
    """(11) корректные положительные цена и комиссия сохраняются."""
    ledger = _mk(tmp_path)
    oid, ok = _first_append(ledger, avg_exec_price=100.0, commission=0.5)
    assert ok is True
    rec = ledger.latest(oid)
    assert rec["avg_exec_price"] == 100.0
    assert rec["commission"] == 0.5
    saved = _first_record(ledger.path)
    assert saved["avg_exec_price"] == 100.0
    assert saved["commission"] == 0.5


# ---------------------------------------------------------------------
# 12. Повторное обновление записи: валидация и guard не ослаблены
# ---------------------------------------------------------------------

def test_repeat_update_validation_preserved(tmp_path):
    """(12) повторная запись: NaN/0.0-цена не затирает подтверждённую;
    кумулятивное уточнение на нетерминальной заявке легитимно."""
    ledger = _mk(tmp_path)
    oid = "order-repeat-1"
    # первая запись: достоверная цена
    ok1 = ledger.record_status(oid, "PARTIALLYFILL", trade_id="t-1",
                               figi="BBG000000000", ticker="TEST", side="BUY",
                               requested_lots=5, executed_lots=2,
                               avg_exec_price=100.0, commission=0.0, source="test")
    assert ok1 is True
    # повторный отчёт с NaN-ценой: подтверждённая цена сохраняется
    ok2 = ledger.record_status(oid, "PARTIALLYFILL", trade_id="t-1",
                               figi="BBG000000000", ticker="TEST", side="BUY",
                               requested_lots=5, executed_lots=2,
                               avg_exec_price=float("nan"), source="test")
    assert ok2 is True
    rec = ledger.latest(oid)
    assert rec["status"] != "UNCERTAIN"
    assert rec["avg_exec_price"] == 100.0
    # повторный 0.0-«отчёт» (CANCELLED-остаток) не затирает подтверждённую
    ok3 = ledger.record_status(oid, "PARTIALLYFILL", trade_id="t-1",
                               figi="BBG000000000", ticker="TEST", side="BUY",
                               requested_lots=5, executed_lots=2,
                               avg_exec_price=0.0, source="test")
    assert ok3 is True
    assert ledger.latest(oid)["avg_exec_price"] == 100.0
    # нетерминальное кумулятивное уточнение принимается
    ok4 = ledger.record_status(oid, "PARTIALLYFILL", trade_id="t-1",
                               figi="BBG000000000", ticker="TEST", side="BUY",
                               requested_lots=5, executed_lots=4,
                               avg_exec_price=101.5, source="test")
    assert ok4 is True
    rec4 = ledger.latest(oid)
    assert rec4["status"] != "UNCERTAIN"
    assert rec4["avg_exec_price"] == 101.5
    # NaN так и не попал в журнал
    raw = open(ledger.path, "r", encoding="utf-8").read()
    assert "NaN" not in raw


# ---------------------------------------------------------------------
# 13. Обогащение неизвестной цены поздним подтверждением (P0-сценарий)
# ---------------------------------------------------------------------

def test_late_confirmation_enriches_unknown_price(tmp_path):
    """(13) неизвестная цена (включая репорт 0.0) обогащается поздним
    подтверждением без ложного UNCERTAIN — контракт ТЗ §3.3."""
    ledger = _mk(tmp_path)
    oid = "order-late-1"
    # частичное исполнение без цены
    ok1 = ledger.record_status(oid, "PARTIALLYFILL", trade_id="t-1",
                               figi="BBG000000000", ticker="TEST", side="BUY",
                               requested_lots=5, executed_lots=2,
                               avg_exec_price=None, commission=None, source="test")
    assert ok1 is True
    # терминальный CANCELLED-отчёт с 0.0-ценой: 0.0 не записывается
    ok2 = ledger.record_status(oid, "CANCELLED", trade_id="t-1",
                               figi="BBG000000000", ticker="TEST", side="BUY",
                               requested_lots=5, executed_lots=2,
                               avg_exec_price=0.0, commission=0.0, source="test")
    assert ok2 is True
    rec2 = ledger.latest(oid)
    assert rec2["status"] == "CANCELLED"
    assert rec2["avg_exec_price"] is None
    assert rec2["commission"] == 0.0  # нулевая комиссия — достоверное значение
    # позднее подтверждение полного исполнения с реальной ценой;
    # комиссия в позднем отчёте отсутствует — достоверный 0.0 сохраняется
    ok3 = ledger.record_status(oid, "FILL", trade_id="t-1",
                               figi="BBG000000000", ticker="TEST", side="BUY",
                               requested_lots=5, executed_lots=5,
                               avg_exec_price=100.0, commission=None, source="late")
    assert ok3 is True
    rec3 = ledger.latest(oid)
    assert rec3["status"] == "FILL"  # ложного UNCERTAIN нет
    assert rec3["avg_exec_price"] == 100.0
    assert rec3["commission"] == 0.0  # 0.0 не затёрт и не превращён в None
    assert rec3["executed_lots"] == 5  # лоты не потеряны и не задвоены
    last = _last_record(ledger.path)
    assert last["avg_exec_price"] == 100.0


# ---------------------------------------------------------------------
# 14. Сохранение и повторная загрузка журнала
# ---------------------------------------------------------------------

def test_persistence_roundtrip_preserves_validation_semantics(tmp_path):
    """(14) сохранённый журнал после повторной загрузки отражает ту же
    семантику: отсутствие цены, достоверный 0.0-комиссии, обогащение."""
    path = str(tmp_path / "order_ledger.jsonl")
    ledger = OrderLedger(path)
    oid1 = "order-pers-1"
    ledger.record_status(oid1, "CANCELLED", trade_id="t-1",
                         figi="BBG000000000", ticker="TEST", side="BUY",
                         requested_lots=5, executed_lots=2,
                         avg_exec_price=0.0, commission=0.0, source="test")
    oid2 = "order-pers-2"
    ledger.record_status(oid2, "FILL", trade_id="t-2",
                         figi="BBG000000001", ticker="TEST2", side="SELL",
                         requested_lots=3, executed_lots=3,
                         avg_exec_price=50.0, commission=0.25, source="test")
    # повторная загрузка
    ledger2 = OrderLedger(path)
    ledger2.load()
    r1 = ledger2.latest(oid1)
    assert r1["avg_exec_price"] is None
    assert r1["commission"] == 0.0
    assert r1["status"] == "CANCELLED"
    r2 = ledger2.latest(oid2)
    assert r2["avg_exec_price"] == 50.0
    assert r2["commission"] == 0.25
    # в самом файле тоже
    recs = _read_status_records(path)
    assert recs[0]["avg_exec_price"] is None
    assert recs[0]["commission"] == 0.0
    assert recs[1]["avg_exec_price"] == 50.0


# ---------------------------------------------------------------------
# 15. Поведение после перезапуска
# ---------------------------------------------------------------------

def test_behavior_after_restart(tmp_path):
    """(15) после перезапуска (load): обогащение работает, противоречие
    достоверных цен по-прежнему fail-closed, 0.0-комиссия живёт."""
    path = str(tmp_path / "order_ledger.jsonl")
    ledger = OrderLedger(path)
    # заявка с неизвестной ценой и нулевой комиссией
    oid_a = "order-restart-a"
    ledger.record_status(oid_a, "CANCELLED", trade_id="t-a",
                         figi="BBG000000000", ticker="TEST", side="BUY",
                         requested_lots=5, executed_lots=2,
                         avg_exec_price=0.0, commission=0.0, source="test")
    # заявка с подтверждённой ценой 100.0 на терминальном статусе
    oid_b = "order-restart-b"
    ledger.record_status(oid_b, "FILL", trade_id="t-b",
                         figi="BBG000000001", ticker="TEST2", side="BUY",
                         requested_lots=5, executed_lots=5,
                         avg_exec_price=100.0, commission=0.5, source="test")
    ledger = None  # «перезапуск»

    ledger2 = OrderLedger(path)
    ledger2.load()
    # 1) позднее подтверждение после перезапуска обогащает неизвестную цену
    #    (комиссия в отчёте отсутствует — достоверный 0.0 сохраняется)
    ok = ledger2.record_status(oid_a, "FILL", trade_id="t-a",
                               figi="BBG000000000", ticker="TEST", side="BUY",
                               requested_lots=5, executed_lots=5,
                               avg_exec_price=100.0, commission=None, source="late")
    assert ok is True
    rec_a = ledger2.latest(oid_a)
    assert rec_a["status"] == "FILL"
    assert rec_a["avg_exec_price"] == 100.0
    assert rec_a["commission"] == 0.0
    # 2) настоящее противоречие двух достоверных цен — fail-closed
    ok2 = ledger2.record_status(oid_b, "FILL", trade_id="t-b",
                                figi="BBG000000001", ticker="TEST2", side="BUY",
                                requested_lots=5, executed_lots=5,
                                avg_exec_price=200.0, source="late")
    assert ok2 is True
    rec_b = ledger2.latest(oid_b)
    assert rec_b["status"] == "UNCERTAIN"  # защита не ослаблена
    assert rec_b["avg_exec_price"] == 100.0  # прежнее значение сохранено
    # 3) повторный достоверный 0.0-комиссии не затирается и не превращается
    #    в None; идентичное достоверное значение конфликтом не является
    ok3 = ledger2.record_status(oid_a, "FILL", trade_id="t-a",
                                figi="BBG000000000", ticker="TEST", side="BUY",
                                requested_lots=5, executed_lots=5,
                                commission=0.0, source="late2")
    assert ok3 is True
    assert ledger2.latest(oid_a)["commission"] == 0.0
    assert ledger2.latest(oid_a)["status"] == "FILL"


# ---------------------------------------------------------------------
# Дополнительно: единообразие по всем входным путям (ТЗ §2 «все входные пути»)
# ---------------------------------------------------------------------

def test_record_sent_path_first_append_validated(tmp_path):
    """Путь record_sent (post_response): первая запись с NaN-комиссией и
    -Inf-ценой не записывает недостоверные значения."""
    ledger = _mk(tmp_path)
    ok = ledger.record_sent("order-sent-1", trade_id="t-1",
                            figi="BBG000000000", ticker="TEST", side="BUY",
                            requested_lots=5, executed_lots=2,
                            avg_exec_price=float("-inf"),
                            commission=float("nan"), source="post_response")
    assert ok is True
    rec = ledger.latest("order-sent-1")
    assert rec["avg_exec_price"] is None
    assert rec["commission"] is None
    raw = open(ledger.path, "r", encoding="utf-8").read()
    assert "NaN" not in raw and "Infinity" not in raw


def test_record_observation_path_validated(tmp_path):
    """Путь record_observation (кумулятивные наблюдения): невалидная цена
    отклоняется, валидная — записывается."""
    ledger = _mk(tmp_path)
    oid = "order-obs-1"
    ok0 = ledger.record_status(oid, "NEW", trade_id="t-1",
                               figi="BBG000000000", ticker="TEST", side="BUY",
                               requested_lots=5, executed_lots=0,
                               source="test")
    assert ok0 is True
    ok1 = ledger.record_observation(oid, executed_lots=2, status="PARTIALLYFILL",
                                    avg_exec_price=float("inf"), source="broker")
    assert ok1 is True
    assert ledger.latest(oid)["avg_exec_price"] is None
    ok2 = ledger.record_observation(oid, executed_lots=4, status="PARTIALLYFILL",
                                    avg_exec_price=99.5, source="broker")
    assert ok2 is True
    assert ledger.latest(oid)["avg_exec_price"] == 99.5
