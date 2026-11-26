# tests/conftest.py
# Изоляция тестовой среды SDK: если реальный SDK t_tech.invest /
# pandas_ta_classic / python-telegram-bot недоступны (например, прогон в
# чистом CI-окружении), ставятся минимальные заглушки. В окружении
# репозитория (SDK установлен) заглушки НЕ используются — поведение
# тестового набора не меняется.
#
# ИЗОЛЯЦИЯ ГЛОБАЛЬНОГО СОСТОЯНИЯ main (аудит pytest-изоляции):
#   autouse-фикстура _isolate_main_globals() сбрасывает глобальные
#   переменные/контейнеры модуля main к чистым производственным значениям
#   ПЕРЕД КАЖДЫМ тестом. Раньше прямые присваивания в тестах
#   (test_main.py, test_buy_registration_fix2*, test_fail_closed.py и др.)
#   и внутренние мутации production-функций (_save_state_checked ->
#   state_save_failed, reconcile -> reconcile_done /
#   _last_reconcile_confirmed_utc) переживали тест и ломали СЛЕДУЮЩИЕ
#   тесты в зависимости от порядка прогона (test_trading_flag,
#   test_persistence, test_main::trading_cycle).
#   Механизм: monkeypatch.setattr на те же имена — на старте каждого
#   теста значения чистые, после теста восстанавливаются pytest'ом.
#   Production-код не меняется; сценарии и ожидания тестов не меняются;
#   тест, задающий своё значение через monkeypatch/фикстуру, работает
#   как прежде (его подмена накладывается поверх сброса).

import enum
import sys
import types
from datetime import datetime, timezone
from decimal import Decimal

import pytest


class _GetMaxLotsRequest:
    """Минимальная заглушка GetMaxLotsRequest: принимает произвольные
    keyword-аргументы, как настоящий protobuf-конструктор (production
    tinkoff_client.get_sandbox_max_lots создаёт запрос через
    GetMaxLotsRequest(account_id=..., instrument_id=..., price=...)).
    Без неё в чистом CI-окружении get_sandbox_max_lots получает TypeError
    и fail-closed возвращает None — тесты max_lots падают не из-за логики."""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _EnumVal:
    def __init__(self, name, value=None):
        self.name = name
        self.value = value if value is not None else name

    def __repr__(self):
        return f"<{self.name}>"


def _quotation_to_decimal(q):
    return Decimal(q.units) + Decimal(q.nano) / Decimal(1e9)


def _decimal_to_quotation(d):
    units = int(d)
    nano = int((Decimal(str(d)) - units) * Decimal(1e9))
    return types.SimpleNamespace(units=units, nano=nano)


def _install_stubs():
    try:
        import t_tech.invest  # noqa: F401
        return  # реальный SDK доступен — ничего не подменяем
    except Exception:
        pass

    invest = types.ModuleType("t_tech.invest")
    invest.CandleInterval = types.SimpleNamespace(
        CANDLE_INTERVAL_1_MIN=_EnumVal("1min"),
        CANDLE_INTERVAL_5_MIN=_EnumVal("5min"),
        CANDLE_INTERVAL_DAY=_EnumVal("day"),
    )
    invest.OrderDirection = types.SimpleNamespace(
        ORDER_DIRECTION_BUY=_EnumVal("BUY", 1),
        ORDER_DIRECTION_SELL=_EnumVal("SELL", 2),
    )
    invest.OrderType = types.SimpleNamespace(
        ORDER_TYPE_MARKET=_EnumVal("MARKET", 1),
        ORDER_TYPE_LIMIT=_EnumVal("LIMIT", 2),
    )
    invest.InstrumentIdType = types.SimpleNamespace(
        INSTRUMENT_ID_TYPE_FIGI=_EnumVal("FIGI", 1),
        INSTRUMENT_ID_TYPE_TICKER=_EnumVal("TICKER", 2),
    )
    invest.InstrumentStatus = types.SimpleNamespace(
        INSTRUMENT_STATUS_ALL=_EnumVal("ALL", 1),
    )
    # ЭТАП 3: int-совместимая заглушка OrderExecutionReportStatus.
    # FakeClient в тестах передаёт СЫРЫЕ КОДЫ статусов (int, как реальный
    # protobuf-SDK: execution_report_status=1..6), а production сравнивает
    # их напрямую с членами перечисления (main.py: PARTIALLYFILL / FILL).
    # _EnumVal не реализует сравнение с int, поэтому ветки частичного
    # исполнения/исполнения не срабатывали. enum.IntEnum сохраняет имена
    # атрибутов (совместимость с production-кодом) и точные значения кодов
    # T-Invest API и восстанавливает равенство member == int в обе стороны.
    # Остальные _EnumVal-заглушки (OrderDirection, OrderType, ...) НЕ меняются.
    class OrderExecutionReportStatus(enum.IntEnum):
        EXECUTION_REPORT_STATUS_FILL = 1
        EXECUTION_REPORT_STATUS_REJECTED = 2
        EXECUTION_REPORT_STATUS_CANCELLED = 3
        EXECUTION_REPORT_STATUS_NEW = 4
        EXECUTION_REPORT_STATUS_PARTIALLYFILL = 5
        EXECUTION_REPORT_STATUS_EXPIRED = 6

    invest.OrderExecutionReportStatus = OrderExecutionReportStatus
    invest.GetMaxLotsRequest = _GetMaxLotsRequest
    # ЭТАП 5Б: enum Order_id_type (контракт T-Invest API GetOrderState/
    # CancelOrder). Стаблет позволяет production-коду TinkoffClient
    # передавать ЯВНЫЙ тип идентификатора в тестах; члены имитируют
    # protobuf-enum (атрибут name — полное имя члена).
    class Order_id_type:
        ORDER_ID_TYPE_UNSPECIFIED = _EnumVal("ORDER_ID_TYPE_UNSPECIFIED", 0)
        ORDER_ID_TYPE_EXCHANGE = _EnumVal("ORDER_ID_TYPE_EXCHANGE", 1)
        ORDER_ID_TYPE_REQUEST = _EnumVal("ORDER_ID_TYPE_REQUEST", 2)

    invest.Order_id_type = Order_id_type
    invest.AsyncClient = object

    grpc = types.ModuleType("t_tech.invest.grpc")
    grpc.GetMaxLotsRequest = invest.GetMaxLotsRequest

    sandbox_pkg = types.ModuleType("t_tech.invest.sandbox")
    sandbox_ac = types.ModuleType("t_tech.invest.sandbox.async_client")
    sandbox_ac.AsyncSandboxClient = object
    sandbox_pkg.async_client = sandbox_ac

    utils = types.ModuleType("t_tech.invest.utils")
    utils.now = lambda: datetime.now(timezone.utc)
    utils.quotation_to_decimal = _quotation_to_decimal
    utils.decimal_to_quotation = _decimal_to_quotation

    ttech = types.ModuleType("t_tech")
    ttech.invest = invest

    sys.modules.setdefault("t_tech", ttech)
    sys.modules.setdefault("t_tech.invest", invest)
    sys.modules.setdefault("t_tech.invest.grpc", grpc)
    sys.modules.setdefault("t_tech.invest.sandbox", sandbox_pkg)
    sys.modules.setdefault("t_tech.invest.sandbox.async_client", sandbox_ac)
    sys.modules.setdefault("t_tech.invest.utils", utils)

    if "pandas_ta_classic" not in sys.modules:
        try:
            import pandas_ta_classic  # noqa: F401
        except Exception:
            sys.modules["pandas_ta_classic"] = types.ModuleType("pandas_ta_classic")

    try:
        import telegram  # noqa: F401
    except Exception:
        telegram = types.ModuleType("telegram")
        telegram.Update = object
        telegram.BotCommand = object
        ext = types.ModuleType("telegram.ext")
        ext.Application = object
        ext.CommandHandler = object
        ext.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
        request = types.ModuleType("telegram.request")
        request.HTTPXRequest = object
        telegram.ext = ext
        telegram.request = request
        sys.modules.setdefault("telegram", telegram)
        sys.modules.setdefault("telegram.ext", ext)
        sys.modules.setdefault("telegram.request", request)


_install_stubs()

import main  # noqa: E402 — ПОСЛЕ установки заглушек SDK (см. _install_stubs)


# ------------------------------------------------------------------
# Общая изоляция глобального состояния main (см. шапку файла).
# Оригиналы функций фиксируются ОДИН РАЗ при импорте conftest — ДО любых
# подмен в тестах, чтобы подменённые MagicMock-функции не переживали тест.
# ------------------------------------------------------------------

_ORIG_IS_TRADING_ENABLED = main.is_trading_enabled
_ORIG_SAVE_STATE = main._save_state


@pytest.fixture(autouse=True)
def _isolate_main_globals(monkeypatch):
    """Сбрасывает глобальное состояние main к чистым значениям на каждый тест."""
    monkeypatch.setattr(main, "reconcile_done", False)
    monkeypatch.setattr(main, "state_save_failed", False)
    monkeypatch.setattr(main, "_last_reconcile_confirmed_utc", None)
    monkeypatch.setattr(main, "_external_close_candidates", {})
    monkeypatch.setattr(main, "_strategy_event_keys", set())
    monkeypatch.setattr(main, "_promote_throttle", {"n": 0, "alive": 0})
    monkeypatch.setattr(main, "top_instruments", [])
    monkeypatch.setattr(main, "telegram_bot", None)
    monkeypatch.setattr(main, "main_client", None)
    monkeypatch.setattr(main, "monitor_ref", None)
    monkeypatch.setattr(main, "rm_ref", None)
    monkeypatch.setattr(main, "ledger_ref", None)
    monkeypatch.setattr(main, "is_trading_enabled", _ORIG_IS_TRADING_ENABLED)
    monkeypatch.setattr(main, "_save_state", _ORIG_SAVE_STATE)


# ------------------------------------------------------------------
# V4 (ТЗ §5): изоляция runtime-файлов.
# OOS-1 (V3): несколько тестов (ветки trading_cycle и др.) не задают
# собственные пути и создавали state.json / research_events.jsonl /
# research_trades.csv / order_ledger.jsonl / trading.flag в КОРНЕ
# кандидата. Фикстура перенаправляет ДЕФОЛТНЫЕ production-пути в
# per-test tmp-каталог ДО тела теста. Тест, задающий свой путь через
# monkeypatch/прямое присваивание, перекрывает эти значения как прежде
# (его подмена накладывается поверх сброса; teardown восстанавливает).
# Production-код не меняется; сценарии и ожидания тестов не меняются.
# ------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_default_runtime_paths(tmp_path, monkeypatch):
    import logger as _logger
    monkeypatch.setattr(main, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(main, "STATE_FILE_TMP", str(tmp_path / "state.json.tmp"))
    monkeypatch.setattr(main, "LEDGER_FILE", str(tmp_path / "order_ledger.jsonl"))
    monkeypatch.setattr(main, "TRADING_FLAG", str(tmp_path / "trading.flag"))
    monkeypatch.setattr(_logger, "EVENTS_FILE", str(tmp_path / "research_events.jsonl"))
    monkeypatch.setattr(_logger, "TRADES_FILE", str(tmp_path / "research_trades.csv"))
    yield
