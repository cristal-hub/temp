# test_b2_v4_accounting_consistency.py
# Tsclp_v2.1_volatile_Samsung — тесты v2.3.7-stage1 (B2 V4):
#   Проблема №1 — ХРОНОЛОГИЧЕСКИЙ cumulative P&L:
#     накопительный cumulative_net_pnl_rub должен рассчитываться в
#     гарантированном хронологическом порядке ЗАКРЫТИЯ сделок
#     (авторитетное время — exit_time, детерминированный fallback,
#     tie-breaker — trade_id), а не в порядке строк файла/регистрации
#     позиций; позднее изменение net P&L старой сделки пересчитывает
#     cumulative всех последующих сделок.
#   Проблема №2 — ПЕРСИСТЕНТНЫЙ LATE CSV RECOVERY:
#     незавершённое восстановление поздних фактических данных (цена/комиссия)
#     переживает регистрацию новой позиции по тому же FIGI
#     (monitor.register() заменяет объект в monitor.positions[figi]) и
#     перезапуск программы (state.json), не смешивает сделки и заявки.
#
# Соответствие сценариям ТЗ:
#   V4-A test_v4_a_cumulative_follows_close_chronology_not_file_order
#   V4-B test_v4_b_late_commission_change_recomputes_subsequent_cumulative
#   V4-C test_v4_c_identical_exit_times_stable_tiebreaker
#   V4-D test_v4_d_missing_or_garbage_timestamps_deterministic
#   V4-E test_v4_e_new_position_same_figi_keeps_recovery_task
#   V4-F test_v4_f_two_trades_same_figi_reports_not_mixed
#   V4-G test_v4_g_recovery_task_survives_restart
#   V4-H test_v4_h_identity_conflict_fail_closed
#   V4-I test_v4_i_csv_error_keeps_task_and_file_intact
#
# Инварианты:
#   - строки CSV не переставляются; net_pnl_rub меняется только по логике
#     v3 (подтверждённые фактические данные);
#   - результат канонизации детерминирован (повтор = тот же файл);
#   - системное время не участвует в пересчёте/сортировке;
#   - recovery-задача привязана к СВОЕЙ сделке и СВОЕЙ заявке (по снимку),
#     новая позиция того же FIGI и её заявки не опрашиваются и не
#     затрагиваются; лоты не применяются повторно; дублей строк нет;
#   - сбой записи CSV сохраняет исходный файл и незавершённую задачу.
#
# Запуск из корня репозитория: pytest test_b2_v4_accounting_consistency.py -v
# ТОЛЬКО fake-объекты: без сети, токенов, реального брокера и заявок.
# RESEARCH ONLY / NO LIVE ORDERS / SANDBOX.

import asyncio
import csv
import json
import os
import sys
import time

from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import logger as research_logger
from execution import ExecutionMonitor, PositionState, TrackedPosition

_IMPORT_ERROR = None


def _install_sdk_stubs():
    """Минимальные заглушки t_tech.invest / telegram_bot (как в
    test_b2_csv_recovery.py) — нужны только для import main."""
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
# Инфраструктура (fake-клиент/отчёты — как в test_b2_csv_recovery.py)
# ===========================================================================

class _MV:
    """MoneyValue/Quotation-заглушка (units + nano)."""

    def __init__(self, units, nano=0):
        self.units = units
        self.nano = nano


class FakeState:
    """Отчёт заявки брокера (CANCELLED=3). executed_order_price — денежная
    СУММА исполнения: цена за инструмент = price_units / (lots * lot).
    price_units=None — отчёт БЕЗ цены исполнения. commission — float или
    _MV (конвертируется в units+nano, как в отчётах брокера)."""

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
    order_id (dict order_states) либо один и тот же отчёт для всех заявок.
    Без сети; фиксирует вызовы."""

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


# ===========================================================================
# Единая точка создания «позиция закрыта своей SELL, CSV записан»
# (как make_closed_logged в test_b2_csv_recovery.py + управляемое
#  авторитетное время закрытия close_requested_at -> exit_time)
# ===========================================================================

ENTRY = 100.0
LOTS = 10

# Фиксированные времена ЗАКРЫТИЯ (детерминированные, без привязки к now()).
T_0900 = "2026-11-20T09:00:00+00:00"
T_1000 = "2026-11-20T10:00:00+00:00"
T_1005 = "2026-11-20T10:05:00+00:00"
T_1010 = "2026-11-20T10:10:00+00:00"


def make_closed_logged_at(subdir, *, trade_id, figi, oid,
                          close_at, price, commission,
                          entry_price=ENTRY, close_before=ENTRY,
                          entry_actual=None, lots=LOTS):
    """Позиция BUY, закрытая ПОЛНЫМ исполнением своей SELL-заявки
    (cumulative == requested -> CLOSED), CSV-строка записана штатным
    process_closing (logged=True). close_at — авторитетное время закрытия
    (close_requested_at), попадает в exit_time CSV-строки.

    price/commission — значения первого (уже учтённого) терминального
    отчёта. price=None -> строка PRICE_UNKNOWN (пустые финансовые поля);
    commission=None -> фактическая комиссия неизвестна (модельная в CSV
    при подтверждённой цене).
    """
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
    # Полное исполнение 10/10: учёт закрыт штатным per-order механизмом.
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
        signal_reason="v4-test", signal_time=T_0900,
    )


def model_commission(exit_price, entry_price=ENTRY, lots=LOTS):
    """Модельная (расчётная) СУММАРНАЯ комиссия сделки — формула штатной
    записи CSV (process_closing, v2.3.1)."""
    turnover = (exit_price + entry_price) * lots
    return abs(turnover * config.COMMISSION_PER_SIDE)


# ===========================================================================
# ТЕСТ V4-A. Закрытие НЕ в порядке регистрации:
# cumulative следует хронологии закрытий, а не порядку строк файла
# ===========================================================================

def test_v4_a_cumulative_follows_close_chronology_not_file_order(isolated_paths):
    """Сделка A зарегистрирована первой (F1), но закрыта ПОЗЖЕ (10:05);
    сделка B зарегистрирована второй (F2), но закрыта РАНЬШЕ (10:00).
    Обе залогированы в одном цикле: порядок СТРОК файла [A, B] отличается
    от хронологии [B, A]. Строки не переставляются, но cumulative
    соответствует фактической временной последовательности закрытий:
    B закрылась первой — её cumulative = net_B; A — второй = net_B + net_A."""
    tmp_path = isolated_paths
    monitor = ExecutionMonitor(FakeClient())

    def add_closed(trade_id, figi, oid, close_at, exit_price, commission):
        pos = TrackedPosition(
            figi=figi, ticker=figi, direction="BUY", entry_price=ENTRY,
            quantity=LOTS, sl_price=ENTRY * 0.98, tp_price=ENTRY * 1.04,
            lot_size=1, state=PositionState.OPEN, trade_id=trade_id,
            price_before_order=ENTRY, close_price_before_order=ENTRY,
            order_send_time=T_0900,
        )
        monitor.positions[figi] = pos
        monitor.add_close_order(pos, oid, LOTS)
        pos.close_order_request_id = oid
        pos.close_requested_lots = LOTS
        pos.close_requested_at = close_at
        assert monitor.apply_close_execution(
            pos, oid, LOTS, "CANCELLED", execution_price=exit_price,
            commission=commission, requested_lots=LOTS) is True
        return pos

    # РЕГИСТРАЦИОННЫЙ порядок в monitor.positions: A (F1) первой, B (F2) второй.
    add_closed("t-va", "F1", "sell-a", T_1005, 110.0, 2.0)   # закрылась ПОЗЖЕ
    add_closed("t-vb", "F2", "sell-b", T_1000, 105.0, 2.0)   # закрылась РАНЬШЕ

    client = FakeClient(order_states={
        "sell-a": FakeState(status_code=3, lots_executed=LOTS,
                            price_units=110.0 * LOTS, commission=2.0),
        "sell-b": FakeState(status_code=3, lots_executed=LOTS,
                            price_units=105.0 * LOTS, commission=2.0),
    })
    run(main.process_closing(client, monitor, None))

    rows = read_trades_csv(tmp_path)
    assert len(rows) == 2
    # Порядок СТРОК файла = порядок записи (регистрации): [A, B].
    assert [r["trade_id"] for r in rows] == ["t-va", "t-vb"], \
        "строки файла не переставляются"
    # Авторитетные времена закрытия в строках различаются и НЕ равны порядку строк.
    assert rows[0]["exit_time"] == T_1005
    assert rows[1]["exit_time"] == T_1000
    net_a = rows[0]["net_pnl_rub"]
    net_b = rows[1]["net_pnl_rub"]
    assert net_a and net_b
    # Хронология: B (10:00) закрылась первой, A (10:05) — второй.
    assert rows[1]["cumulative_net_pnl_rub"] == cum_of(net_b), \
        "первая по времени сделка B: cumulative = её собственный net"
    assert rows[0]["cumulative_net_pnl_rub"] == cum_of(net_b, net_a), \
        "вторая по времени сделка A: cumulative включает net B"
    # Финансовые поля сделок не искажены канонизацией.
    assert rows[0]["exit_price"] == f"{110.0:.4f}"
    assert rows[1]["exit_price"] == f"{105.0:.4f}"
    # Повторный цикл не меняет файл (идемпотентность).
    bytes_before = read_trades_bytes(tmp_path)
    run(main.process_closing(FakeClient(order_states=client._order_states),
                             monitor, None))
    assert read_trades_bytes(tmp_path) == bytes_before


# ===========================================================================
# ТЕСТ V4-B. Позднее изменение старой сделки: пересчёт cumulative
# всех последующих сделок (логирование в порядке, ОТЛИЧНОМ от хронологии)
# ===========================================================================

def test_v4_b_late_commission_change_recomputes_subsequent_cumulative(isolated_paths):
    """Три сделки; хронология закрытий t1 (10:00) < t2 (10:05) < t3 (10:10),
    но залогированы в ОБРАТНОМ порядке (регистрация t3, t2, t1 -> порядок
    строк файла [t3, t2, t1]). У t1 позднее восстанавливается фактическая
    комиссия: net P&L t1 меняется корректно, cumulative t1, t2 и t3
    пересчитан в ХРОНОЛОГИЧЕСКОМ порядке; net t2/t3 не изменился."""
    tmp_path = isolated_paths
    monitor = ExecutionMonitor(FakeClient())

    def add_closed(trade_id, figi, oid, close_at, exit_price, commission):
        pos = TrackedPosition(
            figi=figi, ticker=figi, direction="BUY", entry_price=ENTRY,
            quantity=LOTS, sl_price=ENTRY * 0.98, tp_price=ENTRY * 1.04,
            lot_size=1, state=PositionState.OPEN, trade_id=trade_id,
            price_before_order=ENTRY, close_price_before_order=ENTRY,
            order_send_time=T_0900,
        )
        monitor.positions[figi] = pos
        monitor.add_close_order(pos, oid, LOTS)
        pos.close_order_request_id = oid
        pos.close_requested_lots = LOTS
        pos.close_requested_at = close_at
        assert monitor.apply_close_execution(
            pos, oid, LOTS, "CANCELLED", execution_price=exit_price,
            commission=commission, requested_lots=LOTS) is True
        return pos

    # Регистрация В ОБРАТНОМ хронологии порядке: t3, t2, t1.
    add_closed("t-vb3", "F3", "sell-3", T_1010, 108.0, 3.0)
    add_closed("t-vb2", "F2", "sell-2", T_1005, 105.0, 2.0)
    add_closed("t-vb1", "F1", "sell-1", T_1000, 110.0, None)  # комиссия t1 неизвестна

    client_states = {
        "sell-1": FakeState(status_code=3, lots_executed=LOTS,
                            price_units=110.0 * LOTS, commission=None),
        "sell-2": FakeState(status_code=3, lots_executed=LOTS,
                            price_units=105.0 * LOTS, commission=2.0),
        "sell-3": FakeState(status_code=3, lots_executed=LOTS,
                            price_units=108.0 * LOTS, commission=3.0),
    }
    run(main.process_closing(FakeClient(order_states=client_states), monitor, None))

    rows = read_trades_csv(tmp_path)
    assert [r["trade_id"] for r in rows] == ["t-vb3", "t-vb2", "t-vb1"], \
        "порядок строк файла = порядок записи, не переставляется"
    net3, net2, net1 = (rows[0]["net_pnl_rub"], rows[1]["net_pnl_rub"],
                        rows[2]["net_pnl_rub"])
    assert all(net and float(net) for net in (net1, net2, net3))
    # Хронологический порядок: t1 -> t2 -> t3.
    assert rows[2]["cumulative_net_pnl_rub"] == cum_of(net1), \
        "t1 закрылась первой: cumulative = только её net"
    assert rows[1]["cumulative_net_pnl_rub"] == cum_of(net1, net2)
    assert rows[0]["cumulative_net_pnl_rub"] == cum_of(net1, net2, net3)

    # --- Поздняя фактическая комиссия 1.5 для t1 (закрылась ПЕРВОЙ) ---
    client_states["sell-1"] = FakeState(
        status_code=3, lots_executed=LOTS,
        price_units=110.0 * LOTS, commission=1.5)
    run(main.process_closing(FakeClient(order_states=client_states), monitor, None))

    rows = read_trades_csv(tmp_path)
    assert len(rows) == 3, "обновление одной сделки не создаёт новых строк"
    assert [r["trade_id"] for r in rows] == ["t-vb3", "t-vb2", "t-vb1"]
    net1_new = rows[2]["net_pnl_rub"]
    # net t1 изменился корректно (фактическая комиссия вместо модельной
    # половины): изменение строго в сторону увеличения комиссии.
    model_total = model_commission(110.0)
    expected_net1 = (110.0 - ENTRY) * LOTS - (model_total / 2 + 1.5)
    assert net1_new == f"{expected_net1:.2f}"
    assert net1_new != net1
    # net t2/t3 НЕ изменился (изменяется только их cumulative).
    assert rows[1]["net_pnl_rub"] == net2
    assert rows[0]["net_pnl_rub"] == net3
    # Cumulative ВСЕХ последующих сделок пересчитан в хронологическом порядке.
    assert rows[2]["cumulative_net_pnl_rub"] == cum_of(net1_new)
    assert rows[1]["cumulative_net_pnl_rub"] == cum_of(net1_new, net2)
    assert rows[0]["cumulative_net_pnl_rub"] == cum_of(net1_new, net2, net3)


# ===========================================================================
# ТЕСТ V4-C. Одинаковые exit_time: стабильный tie-breaker (trade_id)
# ===========================================================================

def test_v4_c_identical_exit_times_stable_tiebreaker(isolated_paths):
    """Две сделки с ОДИНАКОВЫМ авторитетным временем закрытия (10:00).
    Порядок строк файла [b-z, a-y] (регистрация b-z первой). При равных
    метках действует стабильный tie-breaker — trade_id (лексикографически):
    a-y раньше b-z. Повторный пересчёт даёт идентичный результат
    (детерминированность, файл не переписывается зря)."""
    tmp_path = isolated_paths
    monitor = ExecutionMonitor(FakeClient())

    def add_closed(trade_id, figi, oid, exit_price, commission):
        pos = TrackedPosition(
            figi=figi, ticker=figi, direction="BUY", entry_price=ENTRY,
            quantity=LOTS, sl_price=ENTRY * 0.98, tp_price=ENTRY * 1.04,
            lot_size=1, state=PositionState.OPEN, trade_id=trade_id,
            price_before_order=ENTRY, close_price_before_order=ENTRY,
            order_send_time=T_0900,
        )
        monitor.positions[figi] = pos
        monitor.add_close_order(pos, oid, LOTS)
        pos.close_order_request_id = oid
        pos.close_requested_lots = LOTS
        pos.close_requested_at = T_1000  # ОДИНАКОВОЕ время закрытия
        assert monitor.apply_close_execution(
            pos, oid, LOTS, "CANCELLED", execution_price=exit_price,
            commission=commission, requested_lots=LOTS) is True
        return pos

    add_closed("t-vc-b", "F1", "sell-cb", 110.0, 2.0)   # строка первой в файле
    add_closed("t-vc-a", "F2", "sell-ca", 105.0, 2.0)   # строка второй в файле

    client = FakeClient(order_states={
        "sell-cb": FakeState(status_code=3, lots_executed=LOTS,
                             price_units=110.0 * LOTS, commission=2.0),
        "sell-ca": FakeState(status_code=3, lots_executed=LOTS,
                             price_units=105.0 * LOTS, commission=2.0),
    })
    run(main.process_closing(client, monitor, None))

    rows = read_trades_csv(tmp_path)
    assert len(rows) == 2
    assert [r["trade_id"] for r in rows] == ["t-vc-b", "t-vc-a"]
    assert rows[0]["exit_time"] == rows[1]["exit_time"] == T_1000
    net_b = rows[0]["net_pnl_rub"]
    net_a = rows[1]["net_pnl_rub"]
    # Tie-breaker: "t-vc-a" < "t-vc-b" лексикографически -> a-y закрывает
    # «первой», её cumulative = только её net; b-z — второй.
    assert rows[1]["cumulative_net_pnl_rub"] == cum_of(net_a)
    assert rows[0]["cumulative_net_pnl_rub"] == cum_of(net_a, net_b)

    # Детерминированность: повторный пересчёт ничего не меняет.
    bytes_before = read_trades_bytes(tmp_path)
    assert research_logger.recompute_cumulative_chronological() == "unchanged"
    time.sleep(0.05)  # исключаем скрытую зависимость от текущего времени
    assert research_logger.recompute_cumulative_chronological() == "unchanged"
    assert read_trades_bytes(tmp_path) == bytes_before


# ===========================================================================
# ТЕСТ V4-D. Отсутствующий/некорректный timestamp: детерминированное
# поведение, БЕЗ подмены текущим системным временем
# ===========================================================================

def test_v4_d_missing_or_garbage_timestamps_deterministic(isolated_paths):
    """Строки с полностью неизвестным временем (пустые все временные поля)
    и с НЕКОРРЕКТНЫМ exit_time сортируются детерминированно: фиксированный
    якорь (минимальная дата UTC, НЕ системное время), tie-break — trade_id;
    строка с корректным временем сортируется по нему. Порядок строк файла
    [d-valid, d-empty, d-garbage] отличается от детерминированного
    хронологического порядка [d-empty, d-garbage, d-valid]. Повторные
    пересчёты (в т.ч. с промежутком времени) и повторный пустой цикл
    process_closing не меняют файл."""
    tmp_path = isolated_paths

    def manual_row(trade_id, net, exit_time=""):
        row = {k: "" for k in research_logger.TRADE_FIELDS}
        row.update({
            "trade_id": trade_id, "ticker": trade_id, "figi": f"F-{trade_id}",
            "side": "BUY", "lot_size": "1", "requested_lots": "1",
            "executed_lots": "1", "net_pnl_rub": net,
            "cumulative_net_pnl_rub": net,
        })
        if exit_time:
            row["exit_time"] = exit_time
        return row

    # Порядок записи: корректная метка, пустые времена, мусорная метка.
    assert research_logger.log_trade(
        manual_row("t-vd-valid", "30.00", T_0900)) is True
    assert research_logger.log_trade(manual_row("t-vd-empty", "10.00")) is True
    assert research_logger.log_trade(
        manual_row("t-vd-garbage", "20.00", "not-a-timestamp")) is True

    rows = read_trades_csv(tmp_path)
    assert [r["trade_id"] for r in rows] == ["t-vd-valid", "t-vd-empty",
                                             "t-vd-garbage"], \
        "канонизация не переставляет строки файла"
    # Детерминированный хронологический порядок:
    #   t-vd-empty (якорь, tie "t-vd-empty" < "t-vd-garbage")
    #   -> t-vd-garbage (якорь) -> t-vd-valid (реальное время 09:00).
    assert rows[1]["cumulative_net_pnl_rub"] == cum_of("10.00")
    assert rows[2]["cumulative_net_pnl_rub"] == cum_of("10.00", "20.00")
    assert rows[0]["cumulative_net_pnl_rub"] == cum_of("10.00", "20.00", "30.00")

    # Повторные пересчёты не меняют файл (в т.ч. после промежутка времени —
    # доказательство отсутствия скрытой подстановки системного времени).
    bytes_before = read_trades_bytes(tmp_path)
    assert bytes_before, "CSV должен существовать"
    assert research_logger.recompute_cumulative_chronological() == "unchanged"
    time.sleep(0.05)
    assert research_logger.recompute_cumulative_chronological() == "unchanged"
    assert read_trades_bytes(tmp_path) == bytes_before
    # Повторный (пустой) цикл process_closing — тоже без изменений файла.
    run(main.process_closing(FakeClient(), ExecutionMonitor(FakeClient()), None))
    assert read_trades_bytes(tmp_path) == bytes_before


# ===========================================================================
# ТЕСТ V4-E. Новая позиция по тому же FIGI не теряет recovery-задачу
# ===========================================================================

def test_v4_e_new_position_same_figi_keeps_recovery_task(isolated_paths):
    """Первая позиция закрыта, CSV-строка записана, фактическая комиссия
    отсутствует. Регистрируется ВТОРАЯ позиция с тем же FIGI (объект первой
    вытеснен из monitor.positions). Первая сделка ОСТАЁТСЯ в очереди
    recovery; при появлении фактической комиссии обновляется именно ПЕРВАЯ
    CSV-строка; задача завершается и удаляется; новая позиция и её учёт
    не затрагиваются; опрос идёт только по СТАРОЙ заявке."""
    tmp_path = isolated_paths
    monitor, pos1, _ = make_closed_logged_at(
        tmp_path, trade_id="t-ve", figi="F1", oid="sell-e1",
        close_at=T_1000, price=110.0, commission=None)
    rows = read_trades_csv(tmp_path)
    assert rows[0]["actual_commission_rub"] == ""  # комиссии нет
    assert monitor.pending_csv_recoveries == []  # позиция ещё жива в positions

    # Новая позиция по ТОМУ ЖЕ FIGI: старая вытесняется из monitor.positions.
    pos2 = register_new_position(monitor, "F1", "t-ve-new")
    assert monitor.positions["F1"] is pos2
    # Первая сделка осталась в очереди восстановления.
    assert len(monitor.pending_csv_recoveries) == 1
    task = monitor.pending_csv_recoveries[0]
    assert task["trade_id"] == "t-ve"
    assert task["figi"] == "F1"
    assert task["position"]["close_order_request_id"] == "sell-e1"

    # Поздний отчёт СТАРОЙ заявки: фактическая комиссия 1.5.
    client = FakeClient(order_states={
        "sell-e1": FakeState(status_code=3, lots_executed=LOTS,
                             price_units=110.0 * LOTS, commission=1.5),
    })
    run(main.process_closing(client, monitor, None))

    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1, "восстановление не создаёт новых строк"
    row = rows[0]
    assert row["trade_id"] == "t-ve", "обновлена именно первая CSV-строка"
    assert row["actual_commission_rub"] == "1.50"
    assert row["commission_source"] == "mixed"
    assert row["exit_price"] == f"{110.0:.4f}"
    model_total = model_commission(110.0)
    expected_net = (110.0 - ENTRY) * LOTS - (model_total / 2 + 1.5)
    assert row["net_pnl_rub"] == f"{expected_net:.2f}"
    assert row["executed_lots"] == str(LOTS)
    # Задача завершена (цена и фактическая комиссия в строке) и удалена.
    assert monitor.pending_csv_recoveries == []
    events = "\n".join(read_events(tmp_path))
    assert "CSV_RECOVERY_TASK_COMPLETED" in events
    assert "CSV_TRADE_ROW_UPDATED" in events
    # Опрос — только по СТАРОЙ заявке (заявки новой позиции не существует).
    assert client.state_calls, "отчёт старой заявки должен опрашиваться"
    assert all(oid == "sell-e1" for oid, _t in client.state_calls)
    # Новая позиция не затронута: состояние/лоты/заявки без изменений.
    assert pos2.state == PositionState.OPEN
    assert pos2.quantity == LOTS
    assert pos2.close_orders == {}
    assert pos2.execution_price is None
    assert pos2.actual_commission is None
    assert pos2.logged is False


# ===========================================================================
# ТЕСТ V4-F. Две сделки с одним FIGI: отчёты в перемешанном порядке
# не смешиваются
# ===========================================================================

def test_v4_f_two_trades_same_figi_reports_not_mixed(isolated_paths):
    """Две сделки с одним FIGI, разные trade_id и разные заявки. Обе
    вытеснены третьей регистрацией (обе задачи в архиве). Поздние отчёты
    приходят в ПЕРЕМЕШАННОМ порядке: сначала комиссия второй сделки, затем
    полные данные первой. Каждый отчёт сопоставляется СО СВОЕЙ сделкой
    (по снимку задачи): строки обновляются независимо, перекрёстного
    обновления нет, опрос идёт только по собственным заявкам сделок."""
    tmp_path = isolated_paths
    # --- Сделка 1: цена известна, комиссии нет ---
    monitor, pos1, _ = make_closed_logged_at(
        tmp_path, trade_id="t-vf1", figi="F1", oid="sell-f1",
        close_at=T_1000, price=110.0, commission=None)
    # --- Регистрация второй позиции того же FIGI (сделка 1 в архиве) ---
    pos2 = register_new_position(monitor, "F1", "t-vf2")
    assert [t["trade_id"] for t in monitor.pending_csv_recoveries] == ["t-vf1"]
    # --- Сделка 2 закрыта своей SELL: цена И комиссия неизвестны ---
    monitor.add_close_order(pos2, "sell-f2", LOTS)
    pos2.close_order_request_id = "sell-f2"
    pos2.close_requested_lots = LOTS
    pos2.close_requested_at = T_1005
    assert monitor.apply_close_execution(
        pos2, "sell-f2", LOTS, "CANCELLED", execution_price=None,
        commission=None, requested_lots=LOTS) is True
    run(main.process_closing(
        FakeClient(order_states={
            "sell-f2": FakeState(status_code=3, lots_executed=LOTS,
                                 price_units=None, commission=None),
        }), monitor, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 2
    assert rows[1]["trade_id"] == "t-vf2"
    assert rows[1]["exit_price"] == "" and rows[1]["net_pnl_rub"] == ""
    assert "PRICE_UNKNOWN" in rows[1]["error_note"]
    # --- Третья позиция того же FIGI: обе сделки теперь в архиве ---
    pos3 = register_new_position(monitor, "F1", "t-vf3")
    assert monitor.positions["F1"] is pos3
    assert [t["trade_id"] for t in monitor.pending_csv_recoveries] == \
        ["t-vf1", "t-vf2"]

    # --- ПЕРЕМЕШАННЫЕ поздние отчёты: ШАГ 1 — только комиссия сделки 2 ---
    client1 = FakeClient(order_states={
        "sell-f2": FakeState(status_code=3, lots_executed=LOTS,
                             price_units=None, commission=1.5),
    })
    run(main.process_closing(client1, monitor, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 2
    row1, row2 = rows[0], rows[1]
    assert row1["trade_id"] == "t-vf1" and row2["trade_id"] == "t-vf2"
    # Комиссия попала в СВОЮ строку (сделка 2), строка сделки 1 не тронута.
    assert row1["actual_commission_rub"] == ""
    assert row2["actual_commission_rub"] == "1.50"
    assert row2["exit_price"] == "" and row2["net_pnl_rub"] == ""
    assert "PRICE_UNKNOWN" in row2["error_note"]

    # --- ШАГ 2: полные данные сделки 1 (перекрёстный порядок) ---
    client2 = FakeClient(order_states={
        "sell-f1": FakeState(status_code=3, lots_executed=LOTS,
                             price_units=110.0 * LOTS, commission=2.0),
        "sell-f2": FakeState(status_code=3, lots_executed=LOTS,
                             price_units=None, commission=1.5),
    })
    run(main.process_closing(client2, monitor, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 2, "дубли строк недопустимы"
    row1, row2 = rows[0], rows[1]
    # Сделка 1: свои цена и комиссия в СВОЕЙ строке.
    assert row1["trade_id"] == "t-vf1"
    assert row1["exit_price"] == f"{110.0:.4f}"
    assert row1["actual_commission_rub"] == "2.00"
    expected_net1 = (110.0 - ENTRY) * LOTS - (model_commission(110.0) / 2 + 2.0)
    assert row1["net_pnl_rub"] == f"{expected_net1:.2f}"
    # Сделка 2: своя комиссия, цена по-прежнему неизвестна (P&L пуст).
    assert row2["trade_id"] == "t-vf2"
    assert row2["exit_price"] == "" and row2["net_pnl_rub"] == ""
    assert row2["actual_commission_rub"] == "1.50"
    assert row2["commission_source"] == "mixed"
    # Опрос — только по собственным заявкам двух сделок (никаких чужих).
    polled = {oid for oid, _t in client2.state_calls}
    assert polled <= {"sell-f1", "sell-f2"}
    # Задача сделки 1 завершена (цена+комиссия), сделки 2 ждёт цену.
    assert [t["trade_id"] for t in monitor.pending_csv_recoveries] == ["t-vf2"]
    # Новая позиция (третья) не затронута.
    assert pos3.state == PositionState.OPEN and pos3.close_orders == {}


# ===========================================================================
# ТЕСТ V4-G. Перезапуск: незавершённая recovery-задача переживает рестарт
# ===========================================================================

def test_v4_g_recovery_task_survives_restart(isolated_paths):
    """Первая сделка закрыта, recovery не завершён (цена неизвестна).
    Новая позиция того же FIGI зарегистрирована (задача архивирована).
    Имитация перезапуска: _save_state -> state.json -> _load_state.
    После рестарта задача восстановлена (снимок содержит СВОЮ заявку и
    cursor), поздние данные первой сделки восстанавливаются в ЕЁ строку,
    дублей нет; затем вторая позиция штатно закрывается — обе сделки
    корректны."""
    tmp_path = isolated_paths
    monitor, pos1, _ = make_closed_logged_at(
        tmp_path, trade_id="t-vg", figi="F1", oid="sell-g1",
        close_at=T_1000, price=None, commission=None)
    row0 = read_trades_csv(tmp_path)[0]
    assert row0["exit_price"] == ""  # PRICE_UNKNOWN при закрытии

    # Новая позиция того же FIGI ДО перезапуска (задача архивирована).
    pos2 = register_new_position(monitor, "F1", "t-vg-n")
    assert len(monitor.pending_csv_recoveries) == 1

    # --- Перезапуск: _save_state -> json-файл -> _load_state ---
    rm = main.RiskManager(FakeClient())
    assert main._save_state(monitor, rm) is True
    monitor2 = ExecutionMonitor(FakeClient())
    rm2 = main.RiskManager(FakeClient())
    assert main._load_state(monitor2, rm2) is True
    # Новая позиция восстановлена; задача восстановления тоже.
    assert monitor2.positions["F1"].trade_id == "t-vg-n"
    assert len(monitor2.pending_csv_recoveries) == 1
    task = monitor2.pending_csv_recoveries[0]
    assert task["trade_id"] == "t-vg"
    assert task["position"]["close_order_request_id"] == "sell-g1"
    snap_cursor = task["position"]["close_orders"]["sell-g1"]
    assert snap_cursor["confirmed_executed_lots"] == LOTS
    assert snap_cursor["applied_lots"] == LOTS
    assert snap_cursor["avg_exec_price"] is None
    # JSON-сериализуемость снимков (state.json совместим).
    json.dumps(monitor2.export_state(), ensure_ascii=False)

    # --- Поздний отчёт ПОСЛЕ перезапуска: цена + комиссия для sell-g1 ---
    client = FakeClient(order_states={
        "sell-g1": FakeState(status_code=3, lots_executed=LOTS,
                             price_units=110.0 * LOTS, commission=1.5),
    })
    run(main.process_closing(client, monitor2, None))

    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1, "после перезапуска дубли CSV недопустимы"
    row = rows[0]
    assert row["trade_id"] == "t-vg"
    assert row["exit_price"] == f"{110.0:.4f}"
    assert row["actual_commission_rub"] == "1.50"
    assert "PRICE_UNKNOWN" not in row["error_note"]
    model_total = model_commission(110.0)
    expected_net1 = (110.0 - ENTRY) * LOTS - (model_total / 2 + 1.5)
    assert row["net_pnl_rub"] == f"{expected_net1:.2f}"
    assert monitor2.pending_csv_recoveries == []

    # --- Новая позиция штатно закрывается своей SELL: обе сделки корректны ---
    pos2r = monitor2.positions["F1"]
    monitor2.add_close_order(pos2r, "sell-g2", LOTS)
    pos2r.close_order_request_id = "sell-g2"
    pos2r.close_requested_lots = LOTS
    pos2r.close_requested_at = T_1005
    assert monitor2.apply_close_execution(
        pos2r, "sell-g2", LOTS, "CANCELLED", execution_price=105.0,
        commission=2.0, requested_lots=LOTS) is True
    client2 = FakeClient(order_states={
        "sell-g1": FakeState(status_code=3, lots_executed=LOTS,
                             price_units=110.0 * LOTS, commission=1.5),
        "sell-g2": FakeState(status_code=3, lots_executed=LOTS,
                             price_units=105.0 * LOTS, commission=2.0),
    })
    run(main.process_closing(client2, monitor2, None))

    rows = read_trades_csv(tmp_path)
    assert len(rows) == 2, "вторая сделка дописана ровно одна, дублей нет"
    assert [r["trade_id"] for r in rows] == ["t-vg", "t-vg-n"]
    assert rows[1]["exit_price"] == f"{105.0:.4f}"
    expected_net2 = (105.0 - ENTRY) * LOTS - (model_commission(105.0) / 2 + 2.0)
    assert rows[1]["net_pnl_rub"] == f"{expected_net2:.2f}"
    # Хронология: первая сделка (10:00) раньше второй (10:05) — порядок
    # строк совпадает с хронологией, cumulative согласован.
    assert rows[0]["cumulative_net_pnl_rub"] == cum_of(rows[0]["net_pnl_rub"])
    assert rows[1]["cumulative_net_pnl_rub"] == cum_of(
        rows[0]["net_pnl_rub"], rows[1]["net_pnl_rub"])


# ===========================================================================
# ТЕСТ V4-H. Конфликт идентичности: fail-closed, чужая строка не изменяется
# ===========================================================================

def test_v4_h_identity_conflict_fail_closed(isolated_paths, caplog):
    """Невозможно однозначно сопоставить отчёт и сделку: поздний отчёт
    СТАРОЙ заявки содержит РОСШИЙ cumulative (12 > учтённых терминальных 10)
    — идентичность отчёта не подтверждена: fail-closed, ни одна строка CSV
    (включая чужую сделку) не изменяется, задача НЕ завершается,
    диагностическое сообщение и событие конфликта записаны."""
    tmp_path = isolated_paths
    monitor, pos1, _ = make_closed_logged_at(
        tmp_path, trade_id="t-vh", figi="F1", oid="sell-h1",
        close_at=T_1000, price=None, commission=None)
    # Чужая сделка в журнале (не должна быть затронута никак).
    foreign = {k: "" for k in research_logger.TRADE_FIELDS}
    foreign.update({
        "trade_id": "t-foreign", "ticker": "OTHER", "figi": "F9",
        "side": "BUY", "lot_size": "1", "requested_lots": "1",
        "executed_lots": "1", "net_pnl_rub": "7.00",
        "cumulative_net_pnl_rub": "7.00",
    })
    assert research_logger.log_trade(foreign) is True
    # Новая позиция того же FIGI -> задача в архиве.
    register_new_position(monitor, "F1", "t-vh-n")
    assert len(monitor.pending_csv_recoveries) == 1
    bytes_before = read_trades_bytes(tmp_path)

    with caplog.at_level("ERROR"):
        run(main.process_closing(
            FakeClient(order_states={
                "sell-h1": FakeState(status_code=3, lots_executed=LOTS + 2,
                                     price_units=110.0 * LOTS, commission=1.5),
            }), monitor, None))

    assert read_trades_bytes(tmp_path) == bytes_before, \
        "конфликт идентичности не должен изменять CSV (в т.ч. чужую строку)"
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 2
    by_id = {r["trade_id"]: r for r in rows}
    assert by_id["t-foreign"]["net_pnl_rub"] == "7.00"
    assert by_id["t-vh"]["exit_price"] == ""  # цена не восстановлена
    assert by_id["t-vh"]["actual_commission_rub"] == ""
    # Задача НЕ завершена и НЕ удалена (повторная попытка возможна).
    assert [t["trade_id"] for t in monitor.pending_csv_recoveries] == ["t-vh"]
    # Диагностика: сообщение о конфликте + событие.
    assert "csv-recovery" in caplog.text
    events = "\n".join(read_events(tmp_path))
    assert "CSV_LATE_METADATA_CONFLICT" in events
    conflict = [json.loads(l) for l in events.splitlines()
                if "CSV_LATE_METADATA_CONFLICT" in l]
    assert any(c.get("reason") == "lots" and c.get("trade_id") == "t-vh"
               for c in conflict)


# ===========================================================================
# ТЕСТ V4-I. Ошибка CSV при recovery: файл цел, задача не завершается,
# повторная попытка возможна
# ===========================================================================

def test_v4_i_csv_error_keeps_task_and_file_intact(isolated_paths, tmp_path,
                                                   monkeypatch, caplog):
    """Сбой атомарной записи при восстановлении архивной задачи: исходный
    CSV остаётся целостным (байт-в-байт), временные файлы удалены, задача
    НЕ считается завершённой (остаётся в очереди); следующий успешный цикл
    выполняет восстановление и завершает задачу."""
    monitor, pos1, _ = make_closed_logged_at(
        tmp_path, trade_id="t-vi", figi="F1", oid="sell-i1",
        close_at=T_1000, price=None, commission=None)
    register_new_position(monitor, "F1", "t-vi-n")
    assert len(monitor.pending_csv_recoveries) == 1
    bytes_before = read_trades_bytes(tmp_path)
    assert bytes_before, "исходный CSV должен существовать"

    def _boom(path):
        raise OSError("имитация сбоя при проверке временного файла")

    original_read_tmp_rows = research_logger._read_tmp_rows
    monkeypatch.setattr(research_logger, "_read_tmp_rows", _boom)
    with caplog.at_level("ERROR"):
        run(main.process_closing(
            FakeClient(order_states={
                "sell-i1": FakeState(status_code=3, lots_executed=LOTS,
                                     price_units=110.0 * LOTS, commission=1.5),
            }), monitor, None))
    monkeypatch.setattr(research_logger, "_read_tmp_rows", original_read_tmp_rows)

    assert read_trades_bytes(tmp_path) == bytes_before, \
        "сбой записи не должен повреждать исходный файл"
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1 and rows[0]["trade_id"] == "t-vi"
    assert rows[0]["exit_price"] == ""  # восстановление не применилось
    # Задача НЕ завершена: остаётся в очереди восстановления.
    assert [t["trade_id"] for t in monitor.pending_csv_recoveries] == ["t-vi"]
    leftovers = [p for p in os.listdir(tmp_path)
                 if p.startswith(".research_trades_")]
    assert leftovers == [], "временные файлы не остаются после сбоя"

    # Повторная попытка (успешный цикл) завершает восстановление.
    run(main.process_closing(
        FakeClient(order_states={
            "sell-i1": FakeState(status_code=3, lots_executed=LOTS,
                                 price_units=110.0 * LOTS, commission=1.5),
        }), monitor, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    assert rows[0]["exit_price"] == f"{110.0:.4f}"
    assert rows[0]["actual_commission_rub"] == "1.50"
    assert monitor.pending_csv_recoveries == []
