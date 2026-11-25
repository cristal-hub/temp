# test_b2_v7_cursor_version_and_alt_timestamp.py
# Tsclp_v2.2_volatile — тесты v2.3.10-stage1 (B2 V7):
#   Defect A — НЕКОРРЕКТНАЯ ВЕРСИЯ cursor'а БОЛЬШЕ НЕ ПРЕВРАЩАЕТСЯ В LEGACY:
#     _cursor_identity_state() — строгая трихотомия маркера
#     identity_version: ключ отсутствует -> LEGACY (существующая
#     legacy-политика, проверка доступных идентификаторов); маркер равен
#     поддерживаемой CURSOR_IDENTITY_VERSION -> НОВЫЙ формат (строгая
#     проверка обязательных полей trade_id/FIGI/side/order_id); маркер
#     присутствует, но пуст (None/""), нулевой (0/"0"), нечисловой
#     ("abc"), неизвестный (1, 999) или не поддерживается -> INVALID/
#     UNKNOWN: fail-closed (cursor_invalid_identity_version), НЕ legacy,
#     брокер не опрашивается, CSV не обновляется, recovery-задача не
#     удаляется и сохраняется с диагностической причиной конфликта;
#     автоматическое повышение версии и молчаливое преобразование
#     формата исключены. add_close_order() пишет прежний поддерживаемый
#     маркер версии (изменений нет).
#   Defect B — АЛЬТЕРНАТИВНЫЙ CURSOR НЕ МОЖЕТ ПРЕДОСТАВИТЬ ЧУЖОЙ
#     TIMESTAMP: _restore_close_requested_at() перед использованием
#     requested_at записи, найденной через ДРУГОЙ сохранённый
#     идентификатор (close_order_request_id / close_order_id),
#     ПОДТВЕРЖДАЕТ идентичность (_alt_cursor_identity_conflict:
#     trade_id, FIGI, side, order_id == ключу, связь с собственной
#     close-заявкой, корректная версия маркера; для нового формата —
#     строгая обязательность полей; для legacy — все ДОСТУПНЫЕ
#     идентификаторы + положительная привязка trade_id и order_id).
#     Совпадение ключа — НЕ доказательство идентичности: чужой
#     trade_id/FIGI, неправильный side/order_id, неизвестная/некорректная
#     версия или непредтверждённая идентичность — timestamp НЕ
#     используется (никакого чужого времени; datetime.now() внутрь
#     восстановления не подставляется; срабатывает приоритет 4 — None и
#     явно обозначенная legacy-политика записи CSV). Правильный приоритет
#     времени сохранён: 1) валидный pos.close_requested_at; 2) свой
#     валидный per-order cursor; 3) подтверждённый альтернативный cursor
#     той же заявки; 4) None + legacy-политика. Новых типов закрытия нет,
#     семантика CSV не менялась.
#
# Соответствие сценариям ТЗ V7:
#   V7-A test_v7_a_legacy_cursor_without_marker_uses_legacy_policy
#   V7-B test_v7_b_supported_version_strict_check_passes
#   V7-C test_v7_c_corrupt_version_string_blocked_not_legacy
#   V7-D test_v7_d_unknown_numeric_version_blocked
#   V7-E test_v7_e_present_but_invalid_marker_blocked
#   V7-F test_v7_f_invalid_version_task_survives_restart_no_side_effects
#   V7-G test_v7_g_confirmed_alt_cursor_timestamp_restored
#   V7-H test_v7_h_alt_cursor_foreign_trade_id_rejected
#   V7-I test_v7_i_alt_cursor_foreign_figi_rejected
#   V7-J test_v7_j_alt_cursor_wrong_side_or_order_id_rejected
#   V7-K test_v7_k_alt_cursor_bad_version_rejected
#   V7-L test_v7_l_alt_cursor_conflict_safe_none_legacy_policy
#   V7-M test_v7_m_two_trades_same_figi_no_timestamp_mixing
#
# Инварианты:
#   - отсутствие ключа identity_version, None, пустая строка, ноль,
#     нечисловая строка и неизвестная числовая версия — РАЗНЫЕ состояния;
#     legacy — ТОЛЬКО отсутствие ключа;
#   - некорректная/неизвестная версия не ослабляет проверку идентичности
#     и не превращает cursor в legacy (fail-closed);
#   - альтернативный timestamp используется ТОЛЬКО при подтверждённой
#     идентичности; смешивание сделок одного FIGI невозможно;
#   - при конфликте результат — None и существующая legacy-политика
#     записи CSV (datetime.now() не подставляется);
#   - конфликтная задача после перезапуска не разблокируется, не
#     опрашивает брокера, не изменяет CSV и не удаляется.
#
# Запуск из корня репозитория: pytest test_b2_v7_cursor_version_and_alt_timestamp.py -v
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

import logger as research_logger
import order_ledger as order_ledger_mod
from order_ledger import OrderLedger
from execution import ExecutionMonitor, PositionState, TrackedPosition

_IMPORT_ERROR = None


def _install_sdk_stubs():
    """Минимальные заглушки t_tech.invest / telegram_bot (как в
    test_b2_v6_timestamp_identity_close_reason.py) — нужны только для
    import main."""
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
# Инфраструктура (fake-клиент/отчёты — как в
# test_b2_v6_timestamp_identity_close_reason)
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
# Единые конструкторы сценариев (как в
# test_b2_v6_timestamp_identity_close_reason)
# ===========================================================================

ENTRY = 100.0
LOTS = 10

# Фиксированные времена (детерминированные):
T_0900 = "2026-11-20T09:00:00+00:00"
T_0905 = "2026-11-20T09:05:00+00:00"   # время ЗАПРОСА SELL (сделка 1)
T_1000 = "2026-11-20T10:00:00+00:00"
T_1005 = "2026-11-20T10:05:00+00:00"   # время ЗАПРОСА SELL (сделка 2)
T_1010 = "2026-11-20T10:10:00+00:00"
T_1015 = "2026-11-20T10:15:00+00:00"   # момент ЗАПИСИ строки CSV (legacy)
T_1020 = "2026-11-20T10:20:00+00:00"   # время ПОЗДНЕГО восстановления
T_1021 = "2026-11-20T10:21:00+00:00"


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
    process_closing (logged=True)."""
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
        signal_reason="v7-test", signal_time=T_0900,
    )


def restart(tmp_path, monitor):
    """Имитация перезапуска: _save_state -> state.json -> _load_state."""
    rm = main.RiskManager(FakeClient())
    assert main._save_state(monitor, rm) is True
    monitor2 = ExecutionMonitor(FakeClient())
    rm2 = main.RiskManager(FakeClient())
    assert main._load_state(monitor2, rm2) is True
    return monitor2


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


def make_alt_cursor_case(monitor, figi, trade_id, *, primary_oid,
                         alt_oid, alt_cursor=None):
    """Позиция с ДВУМЯ сохранёнными ссылками на close-заявку:
    close_order_request_id = primary_oid (свой cursor есть, но без
    requested_at), close_order_id = alt_oid (альтернативная запись
    close_orders). alt_cursor — словарь альтернативного cursor'а или None
    (не создаётся). Возвращает pos."""
    pos = make_open_position(monitor, figi, trade_id)
    monitor.add_close_order(pos, primary_oid, LOTS)
    pos.close_orders[primary_oid]["requested_at"] = None
    pos.close_order_request_id = primary_oid
    pos.close_order_id = alt_oid
    pos.close_requested_lots = LOTS
    pos.close_requested_at = None
    if alt_cursor is not None:
        pos.close_orders[alt_oid] = alt_cursor
    return pos


def full_alt_cursor(trade_id, figi, alt_oid, requested_at, *, side="SELL",
                    identity_version=2):
    """Альтернативный cursor с ПОЛНЫМ набором идентификаторов."""
    cur = {
        "order_id": alt_oid, "trade_id": trade_id, "figi": figi,
        "side": side, "requested_lots": LOTS,
        "confirmed_executed_lots": LOTS, "applied_lots": LOTS,
        "status": "CANCELLED", "requested_at": requested_at,
        "avg_exec_price": None, "commission": None,
    }
    if identity_version is not ...:
        cur["identity_version"] = identity_version
    return cur


# ===========================================================================
# ДЕФЕКТ 1 (V7-A..F): некорректная версия cursor'а не превращается в LEGACY
# ===========================================================================

# ТЕСТ V7-A. Cursor БЕЗ ключа identity_version — LEGACY: проходит
# существующую legacy-проверку (все ДОСТУПНЫЕ идентификаторы), режим
# проверки явно legacy_limited, восстановление завершается штатно.

def test_v7_a_legacy_cursor_without_marker_uses_legacy_policy(isolated_paths,
                                                              clock):
    """Отсутствие ключа identity_version — ЕДИНСТВЕННОЕ основание legacy:
    согласованный legacy cursor не блокируется (обратная совместимость),
    проверка помечается как ОГРАНИЧЕННАЯ (legacy_limited), recovery
    завершается штатно."""
    tmp_path = isolated_paths
    monitor, task = make_recovery_case(tmp_path, "t-v7a", "sell-a7")
    snap_cursor = task["position"]["close_orders"]["sell-a7"]
    del snap_cursor["identity_version"]  # ключа НЕТ -> legacy

    # Трихотомия: отсутствие ключа — ровно legacy (не invalid):
    assert ExecutionMonitor._cursor_identity_state(snap_cursor) == "legacy"
    assert ExecutionMonitor._cursor_is_new_format(snap_cursor) is False
    # Существующая legacy-проверка проходит:
    assert ExecutionMonitor.validate_recovery_identity(task) is None, \
        "согласованный legacy cursor не блокируется (обратная совместимость)"

    monitor2 = restart(tmp_path, monitor)
    tasks = monitor2.pending_csv_recoveries
    assert len(tasks) == 1
    assert tasks[0].get("conflict") is None
    # Неполная проверка зафиксирована ЯВНО (НЕ выдаётся за полную):
    assert tasks[0].get("cursor_validation") == "legacy_limited"

    clock.set(T_1020)
    run(main.process_closing(
        FakeClient(order_states={"sell-a7": terminal_report()}), monitor2, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    assert rows[0]["exit_price"] == f"{110.0:.4f}"
    assert rows[0]["actual_commission_rub"] == "1.50"
    assert monitor2.pending_csv_recoveries == [], \
        "legacy-задача штатно завершается по существующей legacy-политике"


# ТЕСТ V7-B. Cursor с ПОДДЕРЖИВАЕМОЙ версией — строгая проверка проходит.

def test_v7_b_supported_version_strict_check_passes(isolated_paths, clock):
    """identity_version == CURSOR_IDENTITY_VERSION (2; число и строковое
    представление эквивалентны в JSON-окружении) — НОВЫЙ формат: строгая
    проверка обязательных полей проходит на полном наборе, режим full,
    восстановление завершается штатно."""
    tmp_path = isolated_paths
    monitor, task = make_recovery_case(tmp_path, "t-v7b", "sell-b7")
    snap_cursor = task["position"]["close_orders"]["sell-b7"]
    assert snap_cursor["identity_version"] == \
        ExecutionMonitor.CURSOR_IDENTITY_VERSION

    assert ExecutionMonitor._cursor_identity_state(snap_cursor) == "new"
    assert ExecutionMonitor._cursor_is_new_format(snap_cursor) is True
    # Строковое представление поддерживаемой версии — тоже "new":
    str_cursor = copy.deepcopy(snap_cursor)
    str_cursor["identity_version"] = str(
        ExecutionMonitor.CURSOR_IDENTITY_VERSION)
    assert ExecutionMonitor._cursor_identity_state(str_cursor) == "new"
    assert ExecutionMonitor.validate_recovery_identity(task) is None

    monitor2 = restart(tmp_path, monitor)
    tasks = monitor2.pending_csv_recoveries
    assert len(tasks) == 1
    assert tasks[0].get("conflict") is None
    assert tasks[0].get("cursor_validation") == "full"

    clock.set(T_1020)
    run(main.process_closing(
        FakeClient(order_states={"sell-b7": terminal_report()}), monitor2, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    assert rows[0]["exit_price"] == f"{110.0:.4f}"
    assert monitor2.pending_csv_recoveries == []


# ТЕСТ V7-C. identity_version="abc" — БЛОКИРУЕТСЯ, НЕ становится legacy.

def test_v7_c_corrupt_version_string_blocked_not_legacy(isolated_paths, clock):
    """Маркер присутствует, но нечисловой ("abc") — состояние invalid:
    fail-closed (cursor_invalid_identity_version), режим проверки
    invalid_version (НЕ legacy_limited), задача остаётся с конфликтом;
    брокер не опрашивается, CSV не изменяется."""
    tmp_path = isolated_paths
    monitor, task = make_recovery_case(tmp_path, "t-v7c", "sell-c7")
    snap_cursor = task["position"]["close_orders"]["sell-c7"]
    snap_cursor["identity_version"] = "abc"

    # НЕ legacy: состояние invalid, fail-closed:
    assert ExecutionMonitor._cursor_identity_state(snap_cursor) == "invalid"
    assert ExecutionMonitor.validate_recovery_identity(task) == \
        "cursor_invalid_identity_version", \
        "некорректный маркер версии не ослабляет проверку идентичности"
    assert ExecutionMonitor.cursor_validation_mode(task) == "invalid_version", \
        "режим проверки НЕ является legacy (неполная проверка не выдаётся)"

    monitor2 = restart(tmp_path, monitor)
    tasks = monitor2.pending_csv_recoveries
    assert len(tasks) == 1, "задача не удалена и не «завершена» при импорте"
    assert tasks[0].get("conflict") == "cursor_invalid_identity_version"
    assert tasks[0].get("cursor_validation") == "invalid_version"

    bytes_before = read_trades_bytes(tmp_path)
    clock.set(T_1021)
    client = FakeClient(order_states={"sell-c7": terminal_report()})
    run(main.process_closing(client, monitor2, None))
    assert client.state_calls == [], \
        "задача с некорректной версией cursor'а не опрашивает брокера"
    assert read_trades_bytes(tmp_path) == bytes_before, "CSV не изменён"
    assert len(monitor2.pending_csv_recoveries) == 1
    # Маркер НЕ «повышен» и НЕ преобразован молчаливо:
    stored = monitor2.pending_csv_recoveries[0]["position"]["close_orders"]["sell-c7"]
    assert stored["identity_version"] == "abc"


# ТЕСТ V7-D. Неизвестные ЧИСЛОВЫЕ версии (1, 999) — блокируются.

def test_v7_d_unknown_numeric_version_blocked(isolated_paths, clock):
    """identity_version=1 (устаревшая/неизвестная) и 999 (будущая/
    неизвестная) — состояние invalid: fail-closed, НЕ legacy. Никакого
    автоматического повышения до поддерживаемой версии."""
    tmp_path = isolated_paths
    for bad_version, tid, oid in ((1, "t-v7d1", "sell-d71"),
                                  (999, "t-v7d2", "sell-d72")):
        monitor, task = make_recovery_case(tmp_path, tid, oid)
        snap_cursor = task["position"]["close_orders"][oid]
        snap_cursor["identity_version"] = bad_version
        assert ExecutionMonitor._cursor_identity_state(snap_cursor) == \
            "invalid", f"identity_version={bad_version} — НЕ legacy"
        assert ExecutionMonitor.validate_recovery_identity(task) == \
            "cursor_invalid_identity_version"
        assert ExecutionMonitor.cursor_validation_mode(task) == \
            "invalid_version"

        monitor2 = restart(tmp_path, monitor)
        tasks = monitor2.pending_csv_recoveries
        assert len(tasks) == 1
        assert tasks[0].get("conflict") == "cursor_invalid_identity_version"
        assert tasks[0].get("cursor_validation") == "invalid_version"
        # Маркер сохранён как есть — автоматического повышения нет:
        stored = tasks[0]["position"]["close_orders"][oid]
        assert stored["identity_version"] == bad_version


# ТЕСТ V7-E. Присутствующий, но ПУСТОЙ/НУЛЕВОЙ/НЕКОРРЕКТНЫЙ маркер —
# блокируется (отсутствие ключа, None, пустая строка, ноль, неверная
# строка — РАЗНЫЕ значения; legacy — только отсутствие ключа).

@pytest.mark.parametrize("bad_marker", [None, "", 0, "0", False, "2.0", "  "])
def test_v7_e_present_but_invalid_marker_blocked(isolated_paths, clock,
                                                 bad_marker):
    """Маркер ПРИСУТСТВУЕТ, но пуст (None/""/"  "), нулевой (0/"0"),
    логический False или не разбирается как поддерживаемая версия
    ("2.0") — состояние invalid: fail-closed, НЕ legacy_limited, НЕ full."""
    tmp_path = isolated_paths
    tid = f"t-v7e-{repr(bad_marker)}"
    monitor, task = make_recovery_case(tmp_path, tid, "sell-e7")
    snap_cursor = task["position"]["close_orders"]["sell-e7"]
    snap_cursor["identity_version"] = bad_marker  # ключ ПРИСУТСТВУЕТ

    assert ExecutionMonitor._cursor_identity_state(snap_cursor) == "invalid", \
        f"маркер {bad_marker!r} при ПРИСУТСТВУЮЩЕМ ключе — НЕ legacy"
    assert ExecutionMonitor.validate_recovery_identity(task) == \
        "cursor_invalid_identity_version"
    mode = ExecutionMonitor.cursor_validation_mode(task)
    assert mode == "invalid_version"
    assert mode != "legacy_limited" and mode != "full"

    monitor2 = restart(tmp_path, monitor)
    tasks = monitor2.pending_csv_recoveries
    assert len(tasks) == 1
    assert tasks[0].get("conflict") == "cursor_invalid_identity_version"
    assert tasks[0].get("cursor_validation") == "invalid_version"


# ТЕСТ V7-F. Интеграция: некорректная версия ПОСЛЕ import/restart
# сохраняет конфликтную recovery-задачу; опрос брокера, обновление CSV и
# удаление задачи НЕ происходят.

def test_v7_f_invalid_version_task_survives_restart_no_side_effects(
        isolated_paths, clock):
    """Задача с identity_version=999: конфликт при импорте, переживает
    повторный перезапуск с тем же маркером, не разблокируется, не
    опрашивает брокера, не изменяет CSV, не удаляется; диагностическое
    событие CSV_RECOVERY_TASK_CONFLICT записано; маркер версии не
    «повышен»."""
    tmp_path = isolated_paths
    monitor, task = make_recovery_case(tmp_path, "t-v7f", "sell-f7")
    task["position"]["close_orders"]["sell-f7"]["identity_version"] = 999

    # --- первый перезапуск (import_state): конфликт зафиксирован ---
    monitor2 = restart(tmp_path, monitor)
    assert len(monitor2.pending_csv_recoveries) == 1
    assert monitor2.pending_csv_recoveries[0].get("conflict") == \
        "cursor_invalid_identity_version"

    # --- второй перезапуск: конфликт и режим персистентны ---
    monitor3 = restart(tmp_path, monitor2)
    tasks = monitor3.pending_csv_recoveries
    assert len(tasks) == 1, "задача не удалена и не «завершена» при импорте"
    assert tasks[0].get("conflict") == "cursor_invalid_identity_version", \
        "маркер конфликта персистентен (state.json)"
    assert tasks[0].get("cursor_validation") == "invalid_version"
    stored = tasks[0]["position"]["close_orders"]["sell-f7"]
    assert stored["identity_version"] == 999, \
        "автоматическое повышение версии / молчаливое преобразование исключены"

    bytes_before = read_trades_bytes(tmp_path)
    clock.set(T_1021)
    client = FakeClient(order_states={"sell-f7": terminal_report()})
    run(main.process_closing(client, monitor3, None))
    assert client.state_calls == [], \
        "задача с некорректной версией не опрашивает брокера после рестартов"
    assert read_trades_bytes(tmp_path) == bytes_before, "CSV не обновляется"
    assert len(monitor3.pending_csv_recoveries) == 1, "задача не удалена"

    events = events_of(tmp_path)
    conflicts = [e for e in events
                 if (e.get("event") == "CSV_RECOVERY_TASK_CONFLICT"
                     or e.get("type") == "CSV_RECOVERY_TASK_CONFLICT")
                 and e.get("reason") == "cursor_invalid_identity_version"]
    assert conflicts, "диагностическая причина конфликта записана"


# ===========================================================================
# ДЕФЕКТ 2 (V7-G..L): альтернативный cursor не предоставляет чужой
# timestamp
# ===========================================================================

# ТЕСТ V7-G. Альтернативный cursor с теми же trade_id, FIGI, side и
# order_id ПРИНИМАЕТСЯ; timestamp восстанавливается (приоритет 3).

def test_v7_g_confirmed_alt_cursor_timestamp_restored(isolated_paths, clock):
    """СВОЙ cursor (по primary-ссылке) без requested_at; подтверждённый
    альтернативный cursor (вторая ссылка той же заявки: те же trade_id,
    FIGI, side, order_id == ключу) — timestamp используется.
    Интеграция: полный B2 reconcile восстанавливает 09:05; CSV exit_time
    = 09:05."""
    tmp_path = isolated_paths
    monitor = ExecutionMonitor(FakeClient())
    pos = make_alt_cursor_case(
        monitor, "F1", "t-v7g", primary_oid="sell-g1", alt_oid="sell-g0")
    pos.close_orders["sell-g0"] = full_alt_cursor(
        "t-v7g", "F1", "sell-g0", T_0905)
    # Прямая проверка приоритета 3:
    assert main._restore_close_requested_at(pos, "sell-g1") == T_0905, \
        "подтверждённый альтернативный cursor той же заявки принимается"

    # --- Интеграция: полный B2 reconcile ---
    pos.close_requested_at = None  # время позиции отсутствует
    ledger = make_b2_ledger_case(
        tmp_path, clock, pos, "sell-g1", requested=LOTS,
        reason="close:STOP_LOSS", intent_at=T_0905, late_status="NEW",
        late_at=T_1020)
    clock.set(T_1020)
    client = FakeClient(order_state=terminal_report())
    action = run(main._try_resolve_absent_position(client, ledger, pos, monitor))
    assert action == "ledger_close"
    assert pos.state == PositionState.CLOSED
    # Восстановлено из подтверждённого альтернативного cursor'а:
    assert pos.close_requested_at == T_0905
    assert pos.close_requested_at != T_1020

    run(main.process_closing(FakeClient(), monitor, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    assert rows[0]["exit_time"] == T_0905
    assert rows[0]["timestamp_utc"] == T_0905


# ТЕСТ V7-H. Альтернативный cursor с ЧУЖИМ trade_id ОТВЕРГАЕТСЯ.

def test_v7_h_alt_cursor_foreign_trade_id_rejected(isolated_paths):
    """Cursor под второй ссылкой той же заявки, но с trade_id другой
    сделки (FIGI совпадает) — timestamp НЕ используется (время другой
    сделки не попадает в close_requested_at)."""
    monitor = ExecutionMonitor(FakeClient())
    pos = make_alt_cursor_case(
        monitor, "F1", "t-v7h", primary_oid="sell-h1", alt_oid="sell-h0",
        alt_cursor=full_alt_cursor("t-v7h-OTHER", "F1", "sell-h0", T_1005))
    assert main._alt_cursor_identity_conflict(
        pos, "sell-h0", pos.close_orders["sell-h0"]) == "cursor_trade_id_mismatch"
    assert main._restore_close_requested_at(pos, "sell-h1") is None, \
        "чужой trade_id — timestamp не используется"
    assert pos.close_requested_at is None


# ТЕСТ V7-I. Альтернативный cursor с ЧУЖИМ FIGI ОТВЕРГАЕТСЯ.

def test_v7_i_alt_cursor_foreign_figi_rejected(isolated_paths):
    """Чужой FIGI в альтернативном cursor'е — timestamp НЕ используется,
    даже если trade_id совпадает (идентичность не подтверждена)."""
    monitor = ExecutionMonitor(FakeClient())
    pos = make_alt_cursor_case(
        monitor, "F1", "t-v7i", primary_oid="sell-i1", alt_oid="sell-i0",
        alt_cursor=full_alt_cursor("t-v7i", "F9", "sell-i0", T_1005))
    assert main._alt_cursor_identity_conflict(
        pos, "sell-i0", pos.close_orders["sell-i0"]) == "cursor_figi_mismatch"
    assert main._restore_close_requested_at(pos, "sell-i1") is None
    assert pos.close_requested_at is None


# ТЕСТ V7-J. Неправильный side ИЛИ несовпадающий order_id — ОТВЕРГАЕТСЯ.

def test_v7_j_alt_cursor_wrong_side_or_order_id_rejected(isolated_paths):
    """side, противоречащий направлению закрытия (BUY при SELL), и
    order_id, не совпадающий с ключом поиска (подмена типа
    идентификатора), — в обоих случаях timestamp НЕ используется."""
    monitor = ExecutionMonitor(FakeClient())
    # --- вариант 1: неправильный side ---
    pos = make_alt_cursor_case(
        monitor, "F1", "t-v7j1", primary_oid="sell-j1", alt_oid="sell-j0",
        alt_cursor=full_alt_cursor("t-v7j1", "F1", "sell-j0", T_1005,
                                   side="BUY"))
    assert main._alt_cursor_identity_conflict(
        pos, "sell-j0", pos.close_orders["sell-j0"]) == "cursor_side_mismatch"
    assert main._restore_close_requested_at(pos, "sell-j1") is None
    assert pos.close_requested_at is None

    # --- вариант 2: order_id не совпадает с ключом ---
    monitor2 = ExecutionMonitor(FakeClient())
    pos2 = make_alt_cursor_case(
        monitor2, "F1", "t-v7j2", primary_oid="sell-j2", alt_oid="sell-j0b",
        alt_cursor=full_alt_cursor("t-v7j2", "F1", "sell-FOREIGN", T_1005))
    assert main._alt_cursor_identity_conflict(
        pos2, "sell-j0b", pos2.close_orders["sell-j0b"]) == \
        "cursor_order_id_mismatch"
    assert main._restore_close_requested_at(pos2, "sell-j2") is None
    assert pos2.close_requested_at is None

    # --- вариант 3 (положительная привязка): идентификаторов нет вовсе —
    #     идентичность нельзя подтвердить — timestamp НЕ используется ---
    monitor3 = ExecutionMonitor(FakeClient())
    pos3 = make_alt_cursor_case(
        monitor3, "F1", "t-v7j3", primary_oid="sell-j3", alt_oid="sell-j0c",
        alt_cursor={"requested_at": T_1005})  # НЕТ идентификаторов
    assert main._alt_cursor_identity_conflict(
        pos3, "sell-j0c", pos3.close_orders["sell-j0c"]) == \
        "cursor_unconfirmed_identity"
    assert main._restore_close_requested_at(pos3, "sell-j3") is None
    assert pos3.close_requested_at is None


# ТЕСТ V7-K. Неизвестная/некорректная identity_version альтернативного
# cursor'а — ОТВЕРГАЕТСЯ (даже при совпадающих идентификаторах).

def test_v7_k_alt_cursor_bad_version_rejected(isolated_paths):
    """Альтернативный cursor с identity_version="abc" (и 999): все
    идентификаторы совпадают, но версия некорректна — timestamp НЕ
    используется (некорректная версия не ослабляет проверку)."""
    monitor = ExecutionMonitor(FakeClient())
    pos = make_alt_cursor_case(
        monitor, "F1", "t-v7k", primary_oid="sell-k1", alt_oid="sell-k0",
        alt_cursor=full_alt_cursor("t-v7k", "F1", "sell-k0", T_0905,
                                   identity_version="abc"))
    assert main._alt_cursor_identity_conflict(
        pos, "sell-k0", pos.close_orders["sell-k0"]) == \
        "cursor_invalid_identity_version"
    assert main._restore_close_requested_at(pos, "sell-k1") is None
    assert pos.close_requested_at is None

    monitor2 = ExecutionMonitor(FakeClient())
    pos2 = make_alt_cursor_case(
        monitor2, "F1", "t-v7k2", primary_oid="sell-k2", alt_oid="sell-k0b",
        alt_cursor=full_alt_cursor("t-v7k2", "F1", "sell-k0b", T_0905,
                                   identity_version=999))
    assert main._restore_close_requested_at(pos2, "sell-k2") is None
    assert pos2.close_requested_at is None


# ТЕСТ V7-L. При конфликте альтернативного cursor'а: чужое время НЕ
# подставляется, datetime.now() НЕ используется — безопасная политика
# None/legacy (полный B2 reconcile).

def test_v7_l_alt_cursor_conflict_safe_none_legacy_policy(isolated_paths,
                                                         clock):
    """Интеграция: позиция с двумя ссылками; под альтернативной ссылкой —
    cursor ЧУЖОЙ сделки того же FIGI (requested_at=10:05). B2 reconcile в
    10:20 закрывает учёт по отчёту брокера, но close_requested_at
    ОСТАЁТСЯ None: чужое время (10:05), время восстановления (10:20) и
    время запуска НЕ подставляются; legacy-политика применяется ТОЛЬКО на
    записи CSV (exit_time = момент записи 10:15, timestamp_utc пуст)."""
    tmp_path = isolated_paths
    monitor = ExecutionMonitor(FakeClient())
    pos = make_alt_cursor_case(
        monitor, "F1", "t-v7l", primary_oid="sell-l1", alt_oid="sell-l0",
        alt_cursor=full_alt_cursor("t-v7l-OTHER", "F1", "sell-l0", T_1005))
    pos.close_reason = "STOP_LOSS"

    ledger = make_b2_ledger_case(
        tmp_path, clock, pos, "sell-l1", requested=LOTS,
        reason="close:STOP_LOSS", intent_at=T_0905, late_status="NEW",
        late_at=T_1020)
    clock.set(T_1020)
    client = FakeClient(order_state=terminal_report())
    action = run(main._try_resolve_absent_position(client, ledger, pos, monitor))
    assert action == "ledger_close"
    assert pos.state == PositionState.CLOSED

    # Безопасная политика None: чужой timestamp и время восстановления не
    # подставлены; datetime.now() внутрь восстановления не попал:
    assert pos.close_requested_at is None, \
        "конфликтный альтернативный cursor — close_requested_at остаётся None"
    assert pos.close_requested_at != T_1005 and pos.close_requested_at != T_1020

    # Явно обозначенная legacy-политика: на записи CSV (в 10:15):
    clock.set(T_1015)
    run(main.process_closing(FakeClient(), monitor, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["exit_time"] == T_1015
    assert row["exit_time"] != T_1005 and row["exit_time"] != T_1020
    assert row["timestamp_utc"] == "", \
        "подстановка не выдаётся за сохранённое время"


# ===========================================================================
# ДОПОЛНИТЕЛЬНЫЙ СЦЕНАРИЙ ТЗ V7: две сделки ОДНОГО FIGI — смешивание их
# timestamp невозможно
# ===========================================================================

# ТЕСТ V7-M. Две сделки одного FIGI: timestamp второй сделки не попадает в
# первую и наоборот; подтверждённый альтернативный cursor СВОЕЙ сделки —
# используется (различение именно по идентичности).

def test_v7_m_two_trades_same_figi_no_timestamp_mixing(isolated_paths):
    """Сделка 1 (t-v7m1, SELL sell-m1, запрос 09:05) и сделка 2
    (t-v7m2, SELL sell-m2, запрос 10:05) — ОДИН FIGI. Контаминация обеих
    сторон: под альтернативной ссылкой каждой позиции лежит cursor
    ДРУГОЙ сделки того же FIGI. Ни 09:05, ни 10:05 не перетекают между
    сделками (cursor_trade_id_mismatch -> None). Положительный контроль:
    альтернативный cursor СОБСТВЕННОЙ сделки той же позиции (те же
    trade_id/order_id) принимается."""
    monitor = ExecutionMonitor(FakeClient())
    # Сделка 1: свой cursor есть (без requested_at), альтернативная ссылка
    # указывает на заявку СДЕЛКИ 2 (чужой cursor, 10:05):
    pos1 = make_alt_cursor_case(
        monitor, "F1", "t-v7m1", primary_oid="sell-m1", alt_oid="sell-m2")
    pos1.close_orders["sell-m2"] = full_alt_cursor(
        "t-v7m2", "F1", "sell-m2", T_1005)
    # Сделка 2: свой cursor есть (без requested_at), альтернативная ссылка
    # указывает на заявку СДЕЛКИ 1 (чужой cursor, 09:05):
    pos2 = make_open_position(monitor, "F1", "t-v7m2")
    monitor.add_close_order(pos2, "sell-m2", LOTS)
    pos2.close_orders["sell-m2"]["requested_at"] = None
    pos2.close_order_request_id = "sell-m2"
    pos2.close_order_id = "sell-m1"
    pos2.close_requested_lots = LOTS
    pos2.close_requested_at = None
    pos2.close_orders["sell-m1"] = full_alt_cursor(
        "t-v7m1", "F1", "sell-m1", T_0905)

    # Чужой timestamp НЕ перетекает ни в одну из сделок:
    assert main._restore_close_requested_at(pos1, "sell-m1") is None, \
        "timestamp сделки 2 (10:05) не используется сделкой 1"
    assert main._restore_close_requested_at(pos2, "sell-m2") is None, \
        "timestamp сделки 1 (09:05) не используется сделкой 2"
    assert pos1.close_requested_at is None
    assert pos2.close_requested_at is None

    # Положительный контроль: подтверждённый альтернативный cursor СОБСТВЕННОЙ
    # сделки (те же trade_id/order_id, другая ссылка) принимается:
    monitor2 = ExecutionMonitor(FakeClient())
    pos1b = make_alt_cursor_case(
        monitor2, "F1", "t-v7m1", primary_oid="sell-m1", alt_oid="sell-m1b")
    pos1b.close_orders["sell-m1b"] = full_alt_cursor(
        "t-v7m1", "F1", "sell-m1b", T_0905)
    assert main._restore_close_requested_at(pos1b, "sell-m1") == T_0905, \
        "альтернативный cursor СВОЕЙ сделки принимается (идентичность " \
        "подтверждена), чужой — нет"
