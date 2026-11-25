# test_b2_csv_recovery.py
# Tsclp_v2.1_volatile_Samsung — тесты v2.3.6-stage1 (B2 FINAL ACCOUNTING
# CONSISTENCY AUDIT + LATE METADATA CSV RECOVERY): восстановление поздних
# фактических данных брокера (цена исполнения, фактическая комиссия) в
# УЖЕ записанной CSV-строке закрытия.
#
# ДЕФЕКТ: process_closing() записывает CSV-строку закрытия ОДИН раз
# (pos.logged=True навсегда помечает позицию обработанной). Позднее
# поступление фактических данных брокера обновляло per-order cursor и
# поля позиции (v2.3.5-stage1), но уже записанную CSV-строку не исправляло:
# CSV и оперативный учёт расходились (PRICE_UNKNOWN, модельная комиссия и
# устаревший P&L оставались в CSV навсегда).
#
# Соответствие сценариям ТЗ (раздел 6):
#   A test_a_actual_commission_recovered_after_csv_write
#   B test_b_execution_price_recovered_after_price_unknown_csv
#   C test_c_commission_first_then_price
#   D test_d_price_first_then_commission
#   E test_e_repeated_identical_report_does_not_change_result_twice
#   F test_f_late_data_after_restart_updates_previous_trade
#   G test_g_cumulative_pnl_recomputed_for_subsequent_trades
#   H test_h_repeat_processing_creates_no_csv_duplicate
#   I test_i_conflicting_price_does_not_overwrite_confirmed_price
#   J test_j_conflicting_commission_does_not_overwrite_confirmed_commission
#   K test_k_partial_execution_does_not_reapply_lots
#   L test_l_failed_csv_update_does_not_corrupt_file
#   M test_m_missing_or_ambiguous_trade_id_does_not_update_foreign_trade
#   N test_n_full_process_repeat_gives_same_result_as_single
#
# Инварианты, проверяемые в тестах восстановления:
#   - обновляется СУЩЕСТВУЮЩАЯ строка; новых строк нет (дублей нет);
#   - исходный trade_id сохраняется; отсутствующий/неоднозначный
#     trade_id — обновление запрещено (чужая сделка не затрагивается);
#   - количество исполненных лотов НЕ меняется; лоты не применяются
#     повторно (applied/confirmed/quantity/close_applications);
#   - известная цена/комиссия не перезаписываются противоречивыми
#     значениями; отсутствие данных не трактуется как ноль;
#   - накопительный P&L последующих сделок пересчитывается;
#   - сбой обновления не повреждает исходный CSV (атомарная запись);
#   - повторные одинаковые отчёты идемпотентны (файл байт-в-байт).
#
# Запуск из корня репозитория: pytest test_b2_csv_recovery.py -v
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

OID = "sell-csv-recovery"

_IMPORT_ERROR = None


def _install_sdk_stubs():
    """Минимальные заглушки t_tech.invest / telegram_bot (как в
    test_b2_close_accounting.py) — нужны только для import main."""
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


def isolate_subdir(tmp_path, monkeypatch, name):
    """Изолирует пути в поддиректорию tmp_path/name (для теста N с двумя
    независимыми прогонами в одном тесте)."""
    subdir = tmp_path / name
    subdir.mkdir()
    monkeypatch.setattr(research_logger, "EVENTS_FILE",
                        str(subdir / "research_events.jsonl"))
    monkeypatch.setattr(research_logger, "TRADES_FILE",
                        str(subdir / "research_trades.csv"))
    return subdir


# ===========================================================================
# Инфраструктура (fake-клиент/отчёты — как в test_b2_terminal_metadata_recovery.py)
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


def _rows_equal_ignoring_time(rows_a, rows_b):
    """Сравнение строк CSV без wall-clock полей (exit_time/hold_minutes
    фиксируются в момент ШТАТНОЙ записи и не относятся к восстановлению)."""
    return _row_diffs(rows_a, rows_b) == []


def _row_diffs(rows_a, rows_b):
    """Список различающихся полей (без wall-clock полей исходной записи)."""
    ignore = {"exit_time", "hold_minutes", "order_send_time"}
    diffs = []
    if len(rows_a) != len(rows_b):
        return [f"row_count:{len(rows_a)}!={len(rows_b)}"]
    for i, (ra, rb) in enumerate(zip(rows_a, rows_b)):
        keys = set(ra) | set(rb)
        for k in sorted(keys):
            if k in ignore:
                continue
            if ra.get(k, "") != rb.get(k, ""):
                diffs.append(f"row{i}.{k}: {ra.get(k, '')!r}!={rb.get(k, '')!r}")
    return diffs


# ===========================================================================
# Единая точка создания «позиция закрыта своей SELL, CSV записан»
# ===========================================================================

ENTRY = 100.0
EXIT = 110.0
LOTS = 10


def make_closed_logged(subdir, *, trade_id="t-x", figi="F1", oid=OID,
                       lots=LOTS, price=None, commission=None,
                       entry_price=ENTRY, close_before=ENTRY,
                       entry_actual=None):
    """Позиция BUY, закрытая ПОЛНЫМ исполнением своей SELL-заявки
    (cumulative == requested -> CLOSED), CSV-строка записана штатным
    process_closing (logged=True).

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
    if trade_id:
        assert new_row["trade_id"] == trade_id
    else:
        # Штатный writer подставляет случайный trade_id для позиций без
        # идентификатора (строка не может быть надёжно найдена позже).
        assert new_row["trade_id"]
    assert pos.logged is True
    return monitor, pos, client


def late_client(oid=OID, lots=LOTS, price=None, commission=None):
    """Клиент с ПОЗДНИМ отчётом той же заявки (новые метаданные брокера)."""
    return FakeClient(order_states={
        oid: FakeState(status_code=3, lots_executed=lots,
                       price_units=((price * lots) if price is not None else None),
                       commission=commission),
    })


def model_commission(exit_price, entry_price=ENTRY, lots=LOTS):
    """Модельная (расчётная) СУММАРНАЯ комиссия сделки — формула штатной
    записи CSV (process_closing, v2.3.1)."""
    turnover = (exit_price + entry_price) * lots
    return abs(turnover * config.COMMISSION_PER_SIDE)


# ===========================================================================
# Тест A. Фактическая комиссия получена после первоначальной CSV-записи
# ===========================================================================

def test_a_actual_commission_recovered_after_csv_write(isolated_paths):
    """Цена известна при закрытии, фактическая комиссия нет: в CSV попадает
    расчётная (модельная) комиссия. Позднее брокер предоставляет фактическую
    комиссию — СУЩЕСТВУЮЩАЯ строка обновляется (новая не создаётся):
    actual_commission_rub/exit_commission_rub восстановлены, commission_source
    пересчитан (model -> mixed), net P&L пересчитан, лоты и цена не изменены."""
    tmp_path = isolated_paths
    monitor, pos, _ = make_closed_logged(tmp_path, trade_id="t-a",
                                         price=EXIT, commission=None)
    rows = read_trades_csv(tmp_path)
    row0 = rows[0]
    assert row0["exit_price"] == f"{EXIT:.4f}"
    assert row0["commission_source"] == "model"
    assert row0["actual_commission_rub"] == ""
    model_total = model_commission(EXIT)
    assert row0["exit_commission_rub"] == f"{model_total / 2:.2f}"
    executed_before = row0["executed_lots"]
    trade_id_before = row0["trade_id"]

    # Поздний отчёт: та же заявка/исполнение/цена, фактическая комиссия 1.5.
    run(main.process_closing(late_client(price=EXIT, commission=1.5), monitor, None))

    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1, "обновление НЕ должно создавать новую строку"
    row = rows[0]
    # Комиссия восстановлена, расчётная не подменяет фактическую.
    assert row["actual_commission_rub"] == "1.50"
    assert row["exit_commission_rub"] == "1.50"
    assert row["commission_source"] == "mixed"  # вход модельный, выход фактический
    expected_total = model_total / 2 + 1.5
    assert row["commission_rub"] == f"{expected_total:.2f}"
    expected_net = (EXIT - ENTRY) * LOTS - expected_total
    assert row["net_pnl_rub"] == f"{expected_net:.2f}"
    # Цена, лоты, trade_id не изменены.
    assert row["exit_price"] == f"{EXIT:.4f}"
    assert row["executed_lots"] == executed_before
    assert row["trade_id"] == trade_id_before
    # Оперативный учёт согласован с CSV.
    assert pos.actual_commission == pytest.approx(1.5)
    assert pos.close_orders[OID]["commission"] == pytest.approx(1.5)
    assert pos.execution_price == pytest.approx(EXIT)
    # Без повторного применения лотов.
    assert pos.quantity == 0
    assert pos.close_orders[OID]["applied_lots"] == LOTS
    assert pos.close_orders[OID]["confirmed_executed_lots"] == LOTS
    assert len(pos.close_applications) == 1
    assert pos.state == PositionState.CLOSED
    # Событие обновления записано.
    events = "\n".join(read_events(tmp_path))
    assert "CSV_TRADE_ROW_UPDATED" in events


# ===========================================================================
# Тест B. Цена исполнения получена после CSV-записи с PRICE_UNKNOWN
# ===========================================================================

def test_b_execution_price_recovered_after_price_unknown_csv(isolated_paths):
    """Цена неизвестна при закрытии: CSV с PRICE_UNKNOWN и пустыми финансовыми
    полями. Позднее брокер предоставляет фактическую цену — строка обновляется:
    exit_price восстановлен, PRICE_UNKNOWN убран, финансовые поля пересчитаны,
    накопительный P&L записан, лоты не изменены."""
    tmp_path = isolated_paths
    monitor, pos, _ = make_closed_logged(tmp_path, trade_id="t-b",
                                         price=None, commission=None)
    row0 = read_trades_csv(tmp_path)[0]
    assert row0["exit_price"] == ""
    assert row0["net_pnl_rub"] == "" and row0["gross_pnl_rub"] == ""
    assert row0["commission_rub"] == ""
    assert "PRICE_UNKNOWN" in row0["error_note"]
    assert row0["cumulative_net_pnl_rub"] == ""
    executed_before = row0["executed_lots"]

    run(main.process_closing(late_client(price=EXIT, commission=None), monitor, None))

    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["exit_price"] == f"{EXIT:.4f}"
    assert "PRICE_UNKNOWN" not in row["error_note"]
    model_total = model_commission(EXIT)
    expected_net = (EXIT - ENTRY) * LOTS - model_total
    assert row["gross_pnl_rub"] == f"{(EXIT - ENTRY) * LOTS:.2f}"
    assert row["commission_rub"] == f"{model_total:.2f}"
    assert row["commission_source"] == "model"
    assert row["net_pnl_rub"] == f"{expected_net:.2f}"
    assert row["cumulative_net_pnl_rub"] == f"{expected_net:.2f}"
    assert row["executed_lots"] == executed_before
    assert pos.exit_price_confirmed is True
    assert pos.execution_price == pytest.approx(EXIT)
    assert pos.close_orders[OID]["avg_exec_price"] == pytest.approx(EXIT)
    assert pos.state == PositionState.CLOSED


# ===========================================================================
# Тест C. Сначала получена комиссия, позднее цена
# ===========================================================================

def test_c_commission_first_then_price(isolated_paths):
    """Цена и комиссия приходят в РАЗНЫЕ моменты. Шаг 1: комиссия известна,
    цены нет — факт комиссии записывается в существующую строку, P&L остаётся
    пустым (фиктивный P&L запрещён), PRICE_UNKNOWN сохраняется. Шаг 2: цена
    подтверждена — полный пересчёт, PRICE_UNKNOWN убран, ранее восстановленная
    комиссия не затёрта."""
    tmp_path = isolated_paths
    monitor, pos, _ = make_closed_logged(tmp_path, trade_id="t-c",
                                         price=None, commission=None)

    # --- Шаг 1: поздняя комиссия 1.5 (цены ещё нет) ---
    run(main.process_closing(late_client(price=None, commission=1.5), monitor, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    row1 = rows[0]
    assert row1["actual_commission_rub"] == "1.50"
    assert row1["exit_commission_rub"] == "1.50"
    assert row1["commission_source"] == "mixed"
    # P&L не изобретается: цены нет — финансовые поля пустые.
    assert row1["exit_price"] == ""
    assert row1["net_pnl_rub"] == "" and row1["gross_pnl_rub"] == ""
    assert "PRICE_UNKNOWN" in row1["error_note"]

    # --- Шаг 2: поздняя цена 110 (комиссия та же) ---
    run(main.process_closing(late_client(price=EXIT, commission=1.5), monitor, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    row2 = rows[0]
    assert row2["exit_price"] == f"{EXIT:.4f}"
    assert "PRICE_UNKNOWN" not in row2["error_note"]
    # Комиссия, восстановленная на шаге 1, НЕ затёрта.
    assert row2["actual_commission_rub"] == "1.50"
    assert row2["exit_commission_rub"] == "1.50"
    assert row2["commission_source"] == "mixed"
    model_total = model_commission(EXIT)
    expected_net = (EXIT - ENTRY) * LOTS - (model_total / 2 + 1.5)
    assert row2["entry_commission_rub"] == f"{model_total / 2:.2f}"
    assert row2["commission_rub"] == f"{model_total / 2 + 1.5:.2f}"
    assert row2["net_pnl_rub"] == f"{expected_net:.2f}"
    assert row2["cumulative_net_pnl_rub"] == f"{expected_net:.2f}"
    # Лоты не изменены двумя обновлениями.
    assert row2["executed_lots"] == str(LOTS)
    assert pos.quantity == 0 and len(pos.close_applications) == 1


# ===========================================================================
# Тест D. Сначала получена цена, позднее комиссия
# ===========================================================================

def test_d_price_first_then_commission(isolated_paths):
    """Зеркальный тесту C порядок: цена подтверждена первой (модельная
    комиссия в строке), фактическая комиссия приходит позднее и обновляет
    существующую строку без повторного применения и без дублей."""
    tmp_path = isolated_paths
    monitor, pos, _ = make_closed_logged(tmp_path, trade_id="t-d",
                                         price=None, commission=None)

    # --- Шаг 1: цена 110 (комиссии нет) — модельная комиссия, P&L записан ---
    run(main.process_closing(late_client(price=EXIT, commission=None), monitor, None))
    row1 = read_trades_csv(tmp_path)[0]
    assert row1["exit_price"] == f"{EXIT:.4f}"
    assert row1["commission_source"] == "model"
    assert row1["actual_commission_rub"] == ""
    model_total = model_commission(EXIT)
    assert row1["net_pnl_rub"] == f"{(EXIT - ENTRY) * LOTS - model_total:.2f}"
    assert "PRICE_UNKNOWN" not in row1["error_note"]

    # --- Шаг 2: фактическая комиссия 1.5 ---
    run(main.process_closing(late_client(price=EXIT, commission=1.5), monitor, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    row2 = rows[0]
    assert row2["actual_commission_rub"] == "1.50"
    assert row2["exit_commission_rub"] == "1.50"
    assert row2["commission_source"] == "mixed"
    expected_net = (EXIT - ENTRY) * LOTS - (model_total / 2 + 1.5)
    assert row2["net_pnl_rub"] == f"{expected_net:.2f}"
    assert row2["exit_price"] == f"{EXIT:.4f}"  # цена не изменилась
    assert row2["executed_lots"] == str(LOTS)
    assert pos.actual_commission == pytest.approx(1.5)


# ===========================================================================
# Тест E. Повторный одинаковый отчёт не меняет результат второй раз
# ===========================================================================

def test_e_repeated_identical_report_does_not_change_result_twice(isolated_paths):
    """Первый поздний отчёт обновил строку; ВТОРОЙ идентичный отчёт не меняет
    файл ни байтом (идемпотентность обновления CSV)."""
    tmp_path = isolated_paths
    monitor, pos, _ = make_closed_logged(tmp_path, trade_id="t-e",
                                         price=EXIT, commission=None)

    run(main.process_closing(late_client(price=EXIT, commission=1.5), monitor, None))
    bytes_after_first = read_trades_bytes(tmp_path)
    row1 = read_trades_csv(tmp_path)[0]
    assert row1["actual_commission_rub"] == "1.50"

    # Второй идентичный отчёт.
    run(main.process_closing(late_client(price=EXIT, commission=1.5), monitor, None))
    bytes_after_second = read_trades_bytes(tmp_path)
    assert bytes_after_second == bytes_after_first, \
        "повторный идентичный отчёт обязан быть байт-в-байт идемпотентным"
    assert len(read_trades_csv(tmp_path)) == 1
    # Оперативный учёт также идемпотентен.
    assert pos.actual_commission == pytest.approx(1.5)
    assert len(pos.close_applications) == 1


# ===========================================================================
# Тест F. Поздние данные после перезапуска корректно обновляют прежнюю сделку
# ===========================================================================

def test_f_late_data_after_restart_updates_previous_trade(isolated_paths):
    """Перезапуск программы: state.json восстанавливает CLOSED+logged позицию
    с per-order cursor'ом; поздний отчёт брокера корректно обновляет ПРЕЖНЮЮ
    CSV-строку (дублей нет, восстановление работает и после рестарта)."""
    tmp_path = isolated_paths
    monitor, pos, _ = make_closed_logged(tmp_path, trade_id="t-f",
                                         price=None, commission=None)
    row0 = read_trades_csv(tmp_path)[0]
    assert row0["exit_price"] == ""  # PRICE_UNKNOWN при закрытии

    # --- Перезапуск: export_state -> import_state в новый monitor ---
    state = monitor.export_state()
    monitor2 = ExecutionMonitor(FakeClient())
    monitor2.import_state(state)
    pos2 = monitor2.positions["F1"]
    assert pos2.state == PositionState.CLOSED
    assert pos2.logged is True
    assert pos2.trade_id == "t-f"
    assert pos2.close_orders[OID]["confirmed_executed_lots"] == LOTS
    assert pos2.close_orders[OID]["avg_exec_price"] is None

    # --- Поздний отчёт после перезапуска: цена + комиссия ---
    run(main.process_closing(late_client(price=EXIT, commission=1.5), monitor2, None))

    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1, "после перезапуска дубли CSV недопустимы"
    row = rows[0]
    assert row["trade_id"] == "t-f"  # прежняя сделка обновлена, не создана новая
    assert row["exit_price"] == f"{EXIT:.4f}"
    assert "PRICE_UNKNOWN" not in row["error_note"]
    assert row["actual_commission_rub"] == "1.50"
    model_total = model_commission(EXIT)
    expected_net = (EXIT - ENTRY) * LOTS - (model_total / 2 + 1.5)
    assert row["net_pnl_rub"] == f"{expected_net:.2f}"
    # Восстановленная позиция синхронизирована с CSV.
    assert pos2.execution_price == pytest.approx(EXIT)
    assert pos2.actual_commission == pytest.approx(1.5)
    assert pos2.close_orders[OID]["avg_exec_price"] == pytest.approx(EXIT)
    assert pos2.close_orders[OID]["commission"] == pytest.approx(1.5)
    assert pos2.quantity == 0
    assert len(pos2.close_applications) == 1


# ===========================================================================
# Тест G. Накопительный P&L последующих сделок пересчитан правильно
# ===========================================================================

def test_g_cumulative_pnl_recomputed_for_subsequent_trades(isolated_paths):
    """Три сделки закрыты последовательно (t1 — с модельной комиссией).
    Поздняя фактическая комиссия t1 меняет её net_pnl — накопительный P&L
    ВСЕХ последующих сделок (t2, t3) пересчитан в правильном временном
    порядке; сами сделки t2/t3 не изменены (кроме их cumulative)."""
    tmp_path = isolated_paths
    monitor = ExecutionMonitor(FakeClient())
    specs = [
        ("t-g1", "F1", "sell-1", 110.0, None),   # цена есть, комиссии нет
        ("t-g2", "F2", "sell-2", 105.0, 2.0),    # цена и комиссия известны
        ("t-g3", "F3", "sell-3", 108.0, 3.0),    # цена и комиссия известны
    ]
    client_states = {}
    positions = {}
    for trade_id, figi, oid, price, commission in specs:
        pos = TrackedPosition(
            figi=figi, ticker=figi, direction="BUY", entry_price=ENTRY,
            quantity=LOTS, sl_price=ENTRY * 0.98, tp_price=ENTRY * 1.04,
            lot_size=1, state=PositionState.OPEN, trade_id=trade_id,
            price_before_order=ENTRY, close_price_before_order=ENTRY,
            order_send_time=(datetime.now(timezone.utc)
                             - timedelta(hours=1)).isoformat(),
        )
        monitor.positions[figi] = pos
        monitor.add_close_order(pos, oid, LOTS)
        pos.close_order_request_id = oid
        pos.close_requested_lots = LOTS
        assert monitor.apply_close_execution(
            pos, oid, LOTS, "CANCELLED",
            execution_price=price, commission=commission,
            requested_lots=LOTS) is True
        client_states[oid] = FakeState(
            status_code=3, lots_executed=LOTS,
            price_units=price * LOTS, commission=commission)
        positions[trade_id] = pos
        client = FakeClient(order_states=client_states)
        run(main.process_closing(client, monitor, None))
        assert len(read_trades_csv(tmp_path)) == len(positions)

    rows = read_trades_csv(tmp_path)
    assert [r["trade_id"] for r in rows] == ["t-g1", "t-g2", "t-g3"]
    model_total = model_commission(110.0)
    net1_model = (110.0 - ENTRY) * LOTS - model_total
    # net2/net3: фактическая exit-комиссия + МОДЕЛЬНАЯ entry-комиссия
    # (формула штатной записи CSV: entry = model_total/2 при неизвестной
    # фактической комиссии входа).
    model_total2 = model_commission(105.0)
    net2 = (105.0 - ENTRY) * LOTS - (model_total2 / 2 + 2.0)
    model_total3 = model_commission(108.0)
    net3 = (108.0 - ENTRY) * LOTS - (model_total3 / 2 + 3.0)
    assert rows[0]["net_pnl_rub"] == f"{net1_model:.2f}"
    # Исходный cumulative штатной записи.
    cum2_before = float(rows[1]["cumulative_net_pnl_rub"])
    cum3_before = float(rows[2]["cumulative_net_pnl_rub"])
    assert cum2_before == pytest.approx(net1_model + net2, abs=0.01)
    assert cum3_before == pytest.approx(net1_model + net2 + net3, abs=0.01)
    bytes_before = read_trades_bytes(tmp_path)
    net2_str_before = rows[1]["net_pnl_rub"]
    net3_str_before = rows[2]["net_pnl_rub"]

    # --- Поздняя фактическая комиссия 1.5 для t1 ---
    client_states["sell-1"] = FakeState(
        status_code=3, lots_executed=LOTS,
        price_units=110.0 * LOTS, commission=1.5)
    run(main.process_closing(FakeClient(order_states=client_states), monitor, None))

    rows = read_trades_csv(tmp_path)
    assert len(rows) == 3, "обновление одной сделки не должно создавать строки"
    net1_new = (110.0 - ENTRY) * LOTS - (model_total / 2 + 1.5)
    assert rows[0]["actual_commission_rub"] == "1.50"
    assert rows[0]["net_pnl_rub"] == f"{net1_new:.2f}"
    # Пересчёт накопительного P&L последующих сделок (в порядке файла).
    cum2_new = f"{float(rows[0]['net_pnl_rub']) + float(rows[1]['net_pnl_rub']):.2f}"
    cum3_new = f"{float(rows[0]['net_pnl_rub']) + float(rows[1]['net_pnl_rub']) + float(rows[2]['net_pnl_rub']):.2f}"
    assert rows[1]["cumulative_net_pnl_rub"] == cum2_new
    assert rows[2]["cumulative_net_pnl_rub"] == cum3_new
    # Сами сделки t2/t3 не повреждены (net не изменился).
    assert rows[1]["net_pnl_rub"] == net2_str_before
    assert rows[2]["net_pnl_rub"] == net3_str_before
    assert rows[1]["trade_id"] == "t-g2" and rows[2]["trade_id"] == "t-g3"


# ===========================================================================
# Тест H. Повторная обработка не создаёт CSV-дубликат
# ===========================================================================

def test_h_repeat_processing_creates_no_csv_duplicate(isolated_paths):
    """После восстановления метаданных повторные циклы process_closing не
    создают новых строк и не меняют файл."""
    tmp_path = isolated_paths
    monitor, pos, _ = make_closed_logged(tmp_path, trade_id="t-h",
                                         price=None, commission=None)
    run(main.process_closing(late_client(price=EXIT, commission=1.5), monitor, None))
    bytes_after_update = read_trades_bytes(tmp_path)
    assert len(read_trades_csv(tmp_path)) == 1

    for _ in range(3):
        run(main.process_closing(
            late_client(price=EXIT, commission=1.5), monitor, None))
    assert read_trades_bytes(tmp_path) == bytes_after_update
    assert len(read_trades_csv(tmp_path)) == 1


# ===========================================================================
# Тест I. Противоречивая цена не перезаписывает подтверждённую цену
# ===========================================================================

def test_i_conflicting_price_does_not_overwrite_confirmed_price(isolated_paths, caplog):
    """Строка неполна (нет фактической комиссии) — опрос выполняется. Поздний
    отчёт содержит ДРУГУЮ цену (120 вместо подтверждённой 110) при том же
    исполнении — противоречие двух достоверных значений: fail-closed, CSV и
    cursor не изменяются, конфликт зафиксирован."""
    tmp_path = isolated_paths
    monitor, pos, _ = make_closed_logged(tmp_path, trade_id="t-i",
                                         price=EXIT, commission=None)
    bytes_before = read_trades_bytes(tmp_path)
    row0 = read_trades_csv(tmp_path)[0]
    assert row0["exit_price"] == f"{EXIT:.4f}"

    with caplog.at_level("ERROR"):
        run(main.process_closing(late_client(price=120.0, commission=None),
                                 monitor, None))

    assert read_trades_bytes(tmp_path) == bytes_before, \
        "противоречивая цена не должна изменять CSV"
    row = read_trades_csv(tmp_path)[0]
    assert row["exit_price"] == f"{EXIT:.4f}"
    assert row["actual_commission_rub"] == ""  # частичное обновление запрещено
    assert pos.execution_price == pytest.approx(EXIT)
    assert pos.close_orders[OID]["avg_exec_price"] == pytest.approx(EXIT)
    assert "csv-recovery" in caplog.text
    events = "\n".join(read_events(tmp_path))
    assert "CSV_LATE_METADATA_CONFLICT" in events


# ===========================================================================
# Тест J. Противоречивая комиссия не перезаписывает подтверждённую комиссию
# ===========================================================================

def test_j_conflicting_commission_does_not_overwrite_confirmed_commission(isolated_paths, caplog):
    """Комиссия 1.5 подтверждена в cursor/позиции и уже отражена в
    PRICE_UNKNOWN-строке (цены нет — P&L пуст). Поздний отчёт содержит другую
    комиссию 2.0 — противоречие двух достоверных значений: fail-closed, CSV и
    учёт не изменяются, подтверждённая комиссия не перезаписывается."""
    tmp_path = isolated_paths
    monitor, pos, _ = make_closed_logged(tmp_path, trade_id="t-j",
                                         price=None, commission=1.5)
    bytes_before = read_trades_bytes(tmp_path)
    row0 = read_trades_csv(tmp_path)[0]
    assert row0["exit_price"] == ""  # PRICE_UNKNOWN строка: P&L не рассчитан
    assert row0["commission_rub"] == "" and row0["net_pnl_rub"] == ""
    # Факт комиссии подтверждён и записан.
    assert row0["actual_commission_rub"] == "1.50"
    assert row0["exit_commission_rub"] == "1.50"
    assert row0["commission_source"] == "mixed"
    assert pos.actual_commission == pytest.approx(1.5)
    assert pos.close_orders[OID]["commission"] == pytest.approx(1.5)

    with caplog.at_level("ERROR"):
        run(main.process_closing(late_client(price=None, commission=2.0),
                                 monitor, None))

    assert read_trades_bytes(tmp_path) == bytes_before, \
        "противоречивая комиссия не должна изменять CSV"
    row = read_trades_csv(tmp_path)[0]
    assert row["exit_price"] == "" and row["commission_rub"] == ""
    assert row["actual_commission_rub"] == "1.50"  # не перезаписана на 2.0
    assert pos.actual_commission == pytest.approx(1.5)
    assert pos.close_orders[OID]["commission"] == pytest.approx(1.5)
    assert "противоречит" in caplog.text
    events = "\n".join(read_events(tmp_path))
    assert "CSV_LATE_METADATA_CONFLICT" in events


# ===========================================================================
# Тест K. Частичное исполнение не приводит к повторному применению лотов
# ===========================================================================

def test_k_partial_execution_does_not_reapply_lots(isolated_paths):
    """Восстановление метаданных НИКОГДА не применяет исполнение повторно:
    согласованный отчёт (те же лоты) обновляет только метаданные;
    отчёт с выросшим cumulative (12 > учтённых 10 после терминала) отвергается
    целиком — лоты, состояние и CSV не изменяются."""
    tmp_path = isolated_paths
    monitor, pos, _ = make_closed_logged(tmp_path, trade_id="t-k",
                                         price=EXIT, commission=None)

    # --- Согласованный поздний отчёт с новыми метаданными ---
    run(main.process_closing(late_client(lots=LOTS, price=EXIT, commission=1.5),
                             monitor, None))
    cur = pos.close_orders[OID]
    assert cur["applied_lots"] == LOTS
    assert cur["confirmed_executed_lots"] == LOTS
    assert pos.quantity == 0
    assert len(pos.close_applications) == 1
    assert pos.executed_lots == LOTS
    assert pos.state == PositionState.CLOSED
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1 and rows[0]["executed_lots"] == str(LOTS)
    bytes_after_update = read_trades_bytes(tmp_path)

    # --- Отчёт с РОСШИМ cumulative (12 > 10) — отказ целиком ---
    run(main.process_closing(late_client(lots=LOTS + 2, price=EXIT, commission=1.5),
                             monitor, None))
    assert read_trades_bytes(tmp_path) == bytes_after_update, \
        "рост cumulative после терминала не должен изменять CSV"
    assert cur["applied_lots"] == LOTS
    assert cur["confirmed_executed_lots"] == LOTS
    assert pos.quantity == 0
    assert len(pos.close_applications) == 1
    assert pos.state == PositionState.CLOSED
    assert len(read_trades_csv(tmp_path)) == 1


# ===========================================================================
# Тест L. Сбой при обновлении CSV не повреждает исходный файл
# ===========================================================================

def test_l_failed_csv_update_does_not_corrupt_file(isolated_paths, tmp_path, monkeypatch, caplog):
    """Сбой на этапе проверки результата атомарной записи: исходный CSV
    остаётся целостным (байт-в-байт), временные файлы удалены; следующий
    успешный цикл выполняет обновление штатно."""
    monitor, pos, _ = make_closed_logged(tmp_path, trade_id="t-l",
                                         price=None, commission=None)
    bytes_before = read_trades_bytes(tmp_path)
    assert bytes_before, "исходный CSV должен существовать"

    def _boom(path):
        raise OSError("имитация сбоя при проверке временного файла")

    # ВАЖНО: восстанавливаем ТОЛЬКО _read_tmp_rows (не monkeypatch.undo() —
    # он откатил бы и изоляцию путей фикстуры isolated_paths).
    original_read_tmp_rows = research_logger._read_tmp_rows
    monkeypatch.setattr(research_logger, "_read_tmp_rows", _boom)
    with caplog.at_level("ERROR"):
        run(main.process_closing(late_client(price=EXIT, commission=1.5),
                                 monitor, None))
    monkeypatch.setattr(research_logger, "_read_tmp_rows", original_read_tmp_rows)

    assert read_trades_bytes(tmp_path) == bytes_before, \
        "сбой обновления не должен повреждать исходный файл"
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1 and rows[0]["trade_id"] == "t-l"
    # Временные файлы не остаются после сбоя.
    leftovers = [p for p in os.listdir(tmp_path)
                 if p.startswith(".research_trades_")]
    assert leftovers == []
    # Следующий (успешный) цикл выполняет обновление штатно.
    run(main.process_closing(late_client(price=EXIT, commission=1.5), monitor, None))
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1
    assert rows[0]["exit_price"] == f"{EXIT:.4f}"
    assert rows[0]["actual_commission_rub"] == "1.50"


# ===========================================================================
# Тест M. Отсутствующий или неоднозначный trade_id не обновляет чужую сделку
# ===========================================================================

def test_m_missing_or_ambiguous_trade_id_does_not_update_foreign_trade(isolated_paths, tmp_path, caplog):
    """(1) Позиция без trade_id: случайный идентификатор строки не сохранён —
    обновление НЕ выполняется (никакая строка не тронута). (2) Дублирующийся
    trade_id: обновление запрещено (неоднозначность), обе строки не изменены."""
    tmp_path = isolated_paths
    # --- (1) отсутствующий trade_id ---
    monitor, pos, _ = make_closed_logged(tmp_path, trade_id="",
                                         price=None, commission=None)
    bytes_before = read_trades_bytes(tmp_path)
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 1 and rows[0]["trade_id"], \
        "штатная запись должна была создать строку со случайным trade_id"

    run(main.process_closing(late_client(price=EXIT, commission=1.5), monitor, None))
    assert read_trades_bytes(tmp_path) == bytes_before, \
        "без стабильного trade_id обновление запрещено"

    # --- (2) неоднозначный trade_id: две строки с одним trade_id ---
    monitor2, pos2, _ = make_closed_logged(tmp_path, trade_id="t-dup",
                                           figi="F2", oid="sell-dup",
                                           price=EXIT, commission=None)
    # Легаси-ситуация: ВТОРАЯ строка с тем же trade_id (добавлена вручную).
    dup = {**{k: "" for k in research_logger.TRADE_FIELDS},
           "trade_id": "t-dup", "ticker": "OTHER",
           "net_pnl_rub": "55.00", "cumulative_net_pnl_rub": "55.00"}
    assert research_logger.log_trade(dup) is True
    bytes_before_dup = read_trades_bytes(tmp_path)
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 3  # случайная (из п.1) + t-dup + дубль t-dup

    with caplog.at_level("ERROR"):
        run(main.process_closing(
            late_client(oid="sell-dup", price=EXIT, commission=2.5),
            monitor2, None))
    assert read_trades_bytes(tmp_path) == bytes_before_dup, \
        "неоднозначный trade_id не должен обновлять ни одну строку"
    rows = read_trades_csv(tmp_path)
    assert len(rows) == 3
    dup_rows = [r for r in rows if r["trade_id"] == "t-dup"]
    assert len(dup_rows) == 2
    # Чужая строка (OTHER) не изменена; собственная строка t-dup тоже.
    assert dup_rows[1]["ticker"] == "OTHER"
    assert dup_rows[1]["net_pnl_rub"] == "55.00"
    assert dup_rows[0]["actual_commission_rub"] == ""
    events = "\n".join(read_events(tmp_path))
    assert "CSV_LATE_METADATA_CONFLICT" in events


# ===========================================================================
# Тест N. Повторное выполнение полного процесса = однократному
# ===========================================================================

def test_n_full_process_repeat_gives_same_result_as_single(isolated_paths, tmp_path, monkeypatch):
    """Полный процесс восстановления, выполненный дважды, даёт тот же файл,
    что и однократное выполнение (детерминированность обновления)."""
    tmp_path = isolated_paths

    # --- Прогон 1: одиночное обновление ---
    subdir1 = isolate_subdir(tmp_path, monkeypatch, "one")
    monitor1, pos1, _ = make_closed_logged(subdir1, trade_id="t-n",
                                           price=None, commission=None)
    run(main.process_closing(late_client(price=EXIT, commission=1.5), monitor1, None))
    bytes_single = read_trades_bytes(subdir1)

    # --- Прогон 2: два идентичных цикла восстановления подряд ---
    subdir2 = isolate_subdir(tmp_path, monkeypatch, "two")
    monitor2, pos2, _ = make_closed_logged(subdir2, trade_id="t-n",
                                           price=None, commission=None)
    run(main.process_closing(late_client(price=EXIT, commission=1.5), monitor2, None))
    run(main.process_closing(late_client(price=EXIT, commission=1.5), monitor2, None))
    bytes_repeated = read_trades_bytes(subdir2)

    assert bytes_repeated == bytes_single or _rows_equal_ignoring_time(
        read_trades_csv(subdir2), read_trades_csv(subdir1)), \
        f"двойное выполнение = однократному; различия: {_row_diffs(read_trades_csv(subdir1), read_trades_csv(subdir2))}"
    rows = read_trades_csv(subdir2)
    assert len(rows) == 1
    assert rows[0]["exit_price"] == f"{EXIT:.4f}"
    assert rows[0]["actual_commission_rub"] == "1.50"
