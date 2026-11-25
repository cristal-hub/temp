# test_b2_terminal_metadata_recovery.py
# Tsclp_v2.1_volatile_Samsung — тесты v2.3.5-stage1 (B2 TERMINAL REPEAT
# METADATA RECOVERY): безопасное обогащение уже учтённого терминального
# отчёта SELL новыми подтверждёнными метаданными брокера (цена исполнения,
# фактическая комиссия) в ExecutionMonitor.apply_close_execution().
#
# ДЕФЕКТ: при повторном терминальном отчёте по уже учтённой SELL-заявке
# apply_close_execution() возвращал False ДО обновления rec["avg_exec_price"],
# rec["commission"], pos.execution_price, pos.actual_commission — это
# правильно защищало от повторного списания количества, но теряло фактически
# предоставленные брокером цену/комиссию, если при первом отчёте они
# отсутствовали (None), а при повторном запросе были получены.
#
# Соответствие сценариям ТЗ:
#   A test_a_repeat_report_recovers_missing_commission
#   B test_b_repeat_report_recovers_missing_execution_price
#   C test_c_repeat_report_recovers_both_price_and_commission
#   D test_d_known_commission_is_not_overwritten
#   E test_e_conflicting_commission_is_fail_closed
#   F test_f_conflicting_price_is_fail_closed
#   G test_g_repeated_terminal_reports_are_fully_idempotent_with_csv
#   H test_h_safe_repeat_does_not_change_resolved_position_state
#
# Инварианты, проверяемые в КАЖДОМ тесте повтора:
#   - повтор возвращает False (контракт для B2 identity-проверки main.py);
#   - applied_lots / confirmed_executed_lots / pos.quantity не изменяются;
#   - close_applications не растёт (нет повторного применения лотов);
#   - статус позиции не меняется безопасным повтором;
#   - противоречие двух достоверных значений — fail-closed (UNCERTAIN);
#   - отсутствие значения в новом отчёте не затирает сохранённое.
#
# Запуск из корня репозитория: pytest test_b2_terminal_metadata_recovery.py -v
# ТОЛЬКО fake-объекты: без сети, токенов, реального брокера и заявок.

import asyncio
import csv
import os
import sys

from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logger as research_logger
from execution import ExecutionMonitor, PositionState, TrackedPosition

OID = "sell-meta"

_IMPORT_ERROR = None


def _install_sdk_stubs():
    """Минимальные заглушки t_tech.invest / telegram_bot (как в
    test_b2_close_accounting.py) — нужны только для import main (тест G)."""
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
# Инфраструктура прямых тестов execution.py (без main.py)
# ===========================================================================

class _SilentClient:
    """Минимальный клиент: apply_close_execution не обращается к брокеру."""

    def __init__(self):
        self.uncertain_state = False


def make_direct_setup(quantity=10, requested=10):
    """Позиция BUY quantity лотов + monitor + per-order cursor (INTENT)."""
    monitor = ExecutionMonitor(_SilentClient())
    pos = monitor.register(
        figi="F1", ticker="TEST", direction="BUY", entry_price=100.0,
        quantity=quantity, sl_price=98.0, tp_price=104.0, lot_size=1,
        trade_id="t-meta", entry_order_id="BUY1",
        entry_requested_lots=quantity, entry_applied_lots=quantity,
        executed_lots=quantity,
    )
    monitor.add_close_order(pos, OID, requested)
    return monitor, pos


def apply_first(monitor, pos, cumulative=3, requested=10,
                status="CANCELLED", price=110.0, commission=None):
    """Первое (штатное) применение терминального отчёта; возвращает результат."""
    return monitor.apply_close_execution(
        pos, OID, cumulative, status,
        execution_price=price, commission=commission,
        requested_lots=requested)


def repeat(monitor, pos, cumulative=3, status="CANCELLED",
           price=110.0, commission=None):
    """Повторный терминальный отчёт той же заявки."""
    return monitor.apply_close_execution(
        pos, OID, cumulative, status,
        execution_price=price, commission=commission)


def assert_no_reapplication(pos, applied=3, confirmed=3, quantity=7,
                            applications=1):
    """Инвариант «без повторного применения исполнения»."""
    cur = pos.close_orders[OID]
    assert cur["applied_lots"] == applied
    assert cur["confirmed_executed_lots"] == confirmed
    assert pos.quantity == quantity
    assert len(pos.close_applications) == applications
    assert pos.executed_lots == applied


# ===========================================================================
# Инфраструктура интеграционного теста G (B2-поток main.py, как в
# test_b2_close_accounting.py: fake-клиент, изолированные пути, CSV)
# ===========================================================================

class _MV:
    """MoneyValue/Quotation-заглушка (units + nano)."""

    def __init__(self, units, nano=0):
        self.units = units
        self.nano = nano


class FakeState:
    """Отчёт заявки брокера (CANCELLED=3). executed_order_price — денежная
    СУММА исполнения: цена за инструмент = price_units / (lots * lot)."""

    def __init__(self, status_code=3, lots_executed=3, price_units=330,
                 commission=None, lot=1):
        self.execution_report_status = status_code
        self.lots_executed = lots_executed
        self.executed_order_price = _MV(price_units)
        self.executed_commission = commission


class FakeClient:
    """Fake-клиент: фиксирует вызовы get_sandbox_order_state (без сети)."""

    def __init__(self, order_state=None, lot=1):
        self._order_state = order_state
        self._lot = lot
        self.state_calls = []
        self.uncertain_state = False

    async def get_sandbox_order_state(self, oid, order_id_type=None):
        self.state_calls.append((str(oid), order_id_type))
        return self._order_state

    async def get_instrument_info(self, figi):
        return {"lot": self._lot}

    async def get_last_prices(self, figis):
        return []

    async def get_positions(self):
        return {}


def run(coro):
    return asyncio.run(coro)


def read_trades_csv(tmp_path):
    path = tmp_path / "research_trades.csv"
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


# ===========================================================================
# Тест A. Повтор восстанавливает отсутствовавшую фактическую комиссию
# ===========================================================================

def test_a_repeat_report_recovers_missing_commission():
    """Первый терминальный отчёт применил 3/10 (цена известна, комиссия
    отсутствовала). Второй идентичный отчёт содержит фактическую комиссию —
    она восстанавливается без повторного применения исполнения."""
    monitor, pos = make_direct_setup(quantity=10, requested=10)
    assert apply_first(monitor, pos, price=110.0, commission=None) is True
    cur = pos.close_orders[OID]
    assert cur["commission"] is None
    assert pos.actual_commission is None
    assert cur["avg_exec_price"] == pytest.approx(110.0)
    state_before = pos.state

    # Повторный достоверный отчёт: та же заявка/исполнение/цена, комиссия 1.5.
    r = repeat(monitor, pos, price=110.0, commission=1.5)

    assert r is False  # контракт повтора сохранён (B2 identity-проверка)
    # Комиссия восстановлена в cursor и в позиции.
    assert cur["commission"] == pytest.approx(1.5)
    assert pos.actual_commission == pytest.approx(1.5)
    # Цена не искажена.
    assert cur["avg_exec_price"] == pytest.approx(110.0)
    assert pos.execution_price == pytest.approx(110.0)
    assert pos.exit_price_confirmed is True
    # Без повторного применения исполнения.
    assert_no_reapplication(pos, applied=3, confirmed=3, quantity=7,
                            applications=1)
    # Статус позиции не изменён безопасным повтором.
    assert pos.state == state_before


# ===========================================================================
# Тест B. Повтор восстанавливает отсутствовавшую цену исполнения
# ===========================================================================

def test_b_repeat_report_recovers_missing_execution_price():
    """Первый отчёт применил 3/10 (комиссия известна, цена отсутствовала).
    Второй идентичный отчёт содержит фактическую цену — она восстанавливается,
    комиссия сохраняется, повторного применения лотов нет."""
    monitor, pos = make_direct_setup(quantity=10, requested=10)
    assert apply_first(monitor, pos, price=None, commission=1.5) is True
    cur = pos.close_orders[OID]
    assert cur["avg_exec_price"] is None
    assert pos.execution_price is None
    assert pos.exit_price_confirmed is False
    assert cur["commission"] == pytest.approx(1.5)
    state_before = pos.state

    r = repeat(monitor, pos, price=110.0, commission=1.5)

    assert r is False
    # Цена восстановлена в cursor и в позиции, признак подтверждённости — по
    # инварианту ТЗ-5 (цена подтверждена только отчётом реального close-ордера).
    assert cur["avg_exec_price"] == pytest.approx(110.0)
    assert pos.execution_price == pytest.approx(110.0)
    assert pos.exit_price_confirmed is True
    # Комиссия сохранена.
    assert cur["commission"] == pytest.approx(1.5)
    assert pos.actual_commission == pytest.approx(1.5)
    # Повторного применения лотов нет.
    assert_no_reapplication(pos, applied=3, confirmed=3, quantity=7,
                            applications=1)
    assert pos.state == state_before


# ===========================================================================
# Тест C. Повтор восстанавливает ОБА отсутствовавших значения
# ===========================================================================

def test_c_repeat_report_recovers_both_price_and_commission():
    """Первый отчёт не содержал ни цены, ни комиссии; второй идентичный отчёт
    содержит оба значения — оба восстанавливаются без повторного применения."""
    monitor, pos = make_direct_setup(quantity=10, requested=10)
    assert apply_first(monitor, pos, price=None, commission=None) is True
    cur = pos.close_orders[OID]
    assert cur["avg_exec_price"] is None and cur["commission"] is None
    assert pos.execution_price is None and pos.actual_commission is None

    r = repeat(monitor, pos, price=110.0, commission=1.5)

    assert r is False
    assert cur["avg_exec_price"] == pytest.approx(110.0)
    assert cur["commission"] == pytest.approx(1.5)
    assert pos.execution_price == pytest.approx(110.0)
    assert pos.actual_commission == pytest.approx(1.5)
    assert pos.exit_price_confirmed is True
    assert_no_reapplication(pos, applied=3, confirmed=3, quantity=7,
                            applications=1)


# ===========================================================================
# Тест D. Уже известная комиссия НЕ перезаписывается
# ===========================================================================

def test_d_known_commission_is_not_overwritten():
    """Второй отчёт содержит ту же подтверждённую комиссию (подвариант 1) или
    не содержит комиссию вовсе (подвариант 2) — ранее известная комиссия
    сохраняется в cursor и в позиции."""
    # --- Подвариант 1: повтор с той же комиссией 1.5 ---
    monitor, pos = make_direct_setup(quantity=10, requested=10)
    assert apply_first(monitor, pos, price=110.0, commission=1.5) is True
    cur = pos.close_orders[OID]
    state_before = pos.state
    r = repeat(monitor, pos, price=110.0, commission=1.5)
    assert r is False
    assert cur["commission"] == pytest.approx(1.5)  # не «пересоздана»
    assert pos.actual_commission == pytest.approx(1.5)
    assert_no_reapplication(pos, applied=3, confirmed=3, quantity=7,
                            applications=1)
    assert pos.state == state_before  # совпадающий повтор — не противоречие

    # --- Подвариант 2: повтор БЕЗ комиссии (отсутствующее значение) ---
    monitor2, pos2 = make_direct_setup(quantity=10, requested=10)
    assert apply_first(monitor2, pos2, price=110.0, commission=1.5) is True
    cur2 = pos2.close_orders[OID]
    r2 = repeat(monitor2, pos2, price=110.0, commission=None)
    assert r2 is False
    # Отсутствие значения в новом отчёте НЕ затирает сохранённое.
    assert cur2["commission"] == pytest.approx(1.5)
    assert pos2.actual_commission == pytest.approx(1.5)
    assert_no_reapplication(pos2, applied=3, confirmed=3, quantity=7,
                            applications=1)


# ===========================================================================
# Тест E. Противоречие комиссии — fail-closed
# ===========================================================================

def test_e_conflicting_commission_is_fail_closed(caplog):
    """Первый отчёт учёл фактическую комиссию 1.5; второй достоверный отчёт
    содержит другую комиссию 2.0 — противоречие двух достоверных значений:
    UNCERTAIN, конфликт зарегистрирован в логе, исходная комиссия не
    перезаписана, повторного применения нет."""
    monitor, pos = make_direct_setup(quantity=10, requested=10)
    assert apply_first(monitor, pos, price=110.0, commission=1.5) is True
    cur = pos.close_orders[OID]
    # Позиция разрешена брокерским снимком (остаток 7 подтверждён) -> OPEN:
    # противоречие ОБЯЗАНО вернуть её в fail-closed UNCERTAIN.
    pos.state = PositionState.OPEN

    with caplog.at_level("ERROR"):
        r = repeat(monitor, pos, price=110.0, commission=2.0)

    assert r is False
    assert pos.state == PositionState.UNCERTAIN       # fail-closed
    # Исходная подтверждённая комиссия НЕ перезаписана.
    assert cur["commission"] == pytest.approx(1.5)
    assert pos.actual_commission == pytest.approx(1.5)
    assert cur["avg_exec_price"] == pytest.approx(110.0)
    # Конфликт зарегистрирован (лог execution.py).
    assert "противоречит учтённому" in caplog.text
    assert "fail-closed" in caplog.text
    # Повторного применения нет.
    assert_no_reapplication(pos, applied=3, confirmed=3, quantity=7,
                            applications=1)


# ===========================================================================
# Тест F. Противоречие цены — fail-closed
# ===========================================================================

def test_f_conflicting_price_is_fail_closed(caplog):
    """Аналогично тесту E для цены исполнения: 110 -> 120 при том же
    исполнении — UNCERTAIN, цена не перезаписана, применения нет."""
    monitor, pos = make_direct_setup(quantity=10, requested=10)
    assert apply_first(monitor, pos, price=110.0, commission=1.5) is True
    cur = pos.close_orders[OID]
    pos.state = PositionState.OPEN

    with caplog.at_level("ERROR"):
        r = repeat(monitor, pos, price=120.0, commission=1.5)

    assert r is False
    assert pos.state == PositionState.UNCERTAIN       # fail-closed
    # Подтверждённая цена НЕ перезаписана.
    assert cur["avg_exec_price"] == pytest.approx(110.0)
    assert pos.execution_price == pytest.approx(110.0)
    assert cur["commission"] == pytest.approx(1.5)    # комиссия не тронута
    assert "противоречит учтённому" in caplog.text
    assert_no_reapplication(pos, applied=3, confirmed=3, quantity=7,
                            applications=1)


# ===========================================================================
# Тест G. Идемпотентность нескольких повторов подряд (B2-поток + CSV)
# ===========================================================================

def test_g_repeated_terminal_reports_are_fully_idempotent_with_csv(isolated_paths):
    """Несколько идентичных терминальных отчётов подряд через штатный B2-поток
    main.py: количество, applied, confirmed, история применений и CSV не
    дублируются; комиссия, появившаяся во втором отчёте, восстанавливается и
    сохраняется на последующих повторах (без перезаписи и без искажения
    частичного результата первой обработки)."""
    from order_ledger import OrderLedger

    tmp_path = isolated_paths
    ledger = OrderLedger(str(tmp_path / "order_ledger.jsonl"))
    ledger.load()
    now = datetime.now(timezone.utc)
    pos = TrackedPosition(
        figi="F1", ticker="TEST", direction="BUY", entry_price=100.0,
        quantity=10, sl_price=98.0, tp_price=104.0, lot_size=1,
        state=PositionState.OPEN, trade_id="t-g",
        price_before_order=100.0,
        # Вход час назад: после первого прогона close_order_request_id
        # очищается штатным терминальным путём apply_close_execution, и
        # повторные прогоны ищут запись реестра по времени входа (как в
        # make_buy_pos из test_b2_close_accounting.py).
        order_send_time=(now - timedelta(hours=1)).isoformat(),
    )
    monitor = ExecutionMonitor(FakeClient())
    monitor.positions[pos.figi] = pos
    oid = "sell-g"
    assert ledger.record_intent(oid, trade_id=pos.trade_id, figi=pos.figi,
                                ticker=pos.ticker, side="SELL",
                                requested_lots=10, reason="close:SL")
    pos.close_order_request_id = oid
    pos.close_requested_lots = 10
    pos.state = PositionState.CLOSING
    monitor.add_close_order(pos, oid, 10)
    ledger.record_sent(oid, figi="F1", ticker="TEST", side="SELL",
                       requested_lots=10, executed_lots=0, status_hint="NEW")

    # --- Прогон 1: терминальный отчёт CANCELLED 3/10, цена 110, без комиссии.
    client1 = FakeClient(order_state=FakeState(
        status_code=3, lots_executed=3, price_units=330, commission=None))
    assert run(main._try_resolve_absent_position(client1, ledger, pos, monitor)) \
        == "ledger_close"
    run(main.process_closing(client1, monitor, None))
    assert len(read_trades_csv(tmp_path)) == 1
    cur = pos.close_orders[oid]
    assert cur["applied_lots"] == 3 and cur["confirmed_executed_lots"] == 3
    assert cur["commission"] is None
    assert pos.quantity == 0 and pos.partial is True
    history_1 = list(pos.close_applications)

    # --- Прогон 2: идентичный отчёт, БРОКЕР УЖЕ ПЕРЕДАЛ КОМИССИЮ 1.5.
    client2 = FakeClient(order_state=FakeState(
        status_code=3, lots_executed=3, price_units=330,
        commission=_MV(1, 500000000)))
    assert run(main._try_resolve_absent_position(client2, ledger, pos, monitor)) \
        == "ledger_close"   # безопасный повтор (не противоречие)
    # Комиссия восстановлена (дефект устранён).
    assert cur["commission"] == pytest.approx(1.5)
    assert pos.actual_commission == pytest.approx(1.5)
    # Без повторного списания количества и без дубля истории применений.
    assert pos.quantity == 0
    assert cur["applied_lots"] == 3 and cur["confirmed_executed_lots"] == 3
    assert len(pos.close_applications) == 1
    assert pos.close_applications == history_1
    # CSV не дублируется.
    run(main.process_closing(client2, monitor, None))
    assert len(read_trades_csv(tmp_path)) == 1

    # --- Прогон 3: ещё один идентичный повтор (с комиссией) — полный
    #     idempotent: ничего не меняется, дубликатов нет.
    client3 = FakeClient(order_state=FakeState(
        status_code=3, lots_executed=3, price_units=330,
        commission=_MV(1, 500000000)))
    assert run(main._try_resolve_absent_position(client3, ledger, pos, monitor)) \
        == "ledger_close"
    assert cur["commission"] == pytest.approx(1.5)
    assert pos.actual_commission == pytest.approx(1.5)
    assert pos.quantity == 0
    assert cur["applied_lots"] == 3 and cur["confirmed_executed_lots"] == 3
    assert len(pos.close_applications) == 1
    assert pos.close_applications == history_1
    assert client3.uncertain_state is False
    run(main.process_closing(client3, monitor, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    # Частичный результат первой обработки не искажён.
    assert rows[0]["execution_status"] == "FILL_PARTIAL"
    assert "частичное исполнение SELL (3/10" in rows[0]["error_note"]


# ===========================================================================
# Тест H. Безопасный повтор с новыми метаданными не меняет состояние позиции
# ===========================================================================

def test_h_safe_repeat_does_not_change_resolved_position_state():
    """Позиция, корректно разрешённая после частичного исполнения (остаток
    подтверждён брокерским снимком -> OPEN), и позиция, закрытая учётом
    (полный SELL -> CLOSED): безопасный повтор с новыми метаданными сохраняет
    их состояние, количество и ссылки заявки."""
    # --- Вариант 1: позиция разрешена в OPEN после частичного терминала ---
    monitor, pos = make_direct_setup(quantity=10, requested=10)
    assert apply_first(monitor, pos, price=110.0, commission=None) is True
    assert pos.state == PositionState.UNCERTAIN
    assert pos.quantity == 7
    assert pos.close_order_id is None          # завершённая заявка очищена
    # Разрешение брокерским снимком: остаток 7 подтверждён -> OPEN.
    pos.state = PositionState.OPEN

    r = repeat(monitor, pos, price=110.0, commission=1.5)

    assert r is False
    assert pos.state == PositionState.OPEN            # НЕ переведена в UNCERTAIN
    assert pos.quantity == 7                          # количество не изменено
    assert pos.close_order_id is None                 # ссылки не воскрешены
    assert pos.actual_commission == pytest.approx(1.5)  # метаданные восстановлены
    assert_no_reapplication(pos, applied=3, confirmed=3, quantity=7,
                            applications=1)

    # --- Вариант 2: позиция закрыта учётом (полный SELL 10/10) ---
    monitor2, pos2 = make_direct_setup(quantity=10, requested=10)
    assert monitor2.apply_close_execution(
        pos2, OID, 10, "CANCELLED",
        execution_price=110.0, commission=None, requested_lots=10) is True
    assert pos2.state == PositionState.CLOSED
    assert pos2.quantity == 0

    r2 = monitor2.apply_close_execution(
        pos2, OID, 10, "CANCELLED",
        execution_price=110.0, commission=1.5)

    assert r2 is False
    assert pos2.state == PositionState.CLOSED         # состояние сохранено
    assert pos2.quantity == 0
    assert pos2.actual_commission == pytest.approx(1.5)
    assert_no_reapplication(pos2, applied=10, confirmed=10, quantity=0,
                            applications=1)
