# test_v4_integration_integrity.py
# V4 (ТЗ §4): точечные интеграционные тесты групп, у которых ранее не было
# ПРЯМОГО покрытия по имени:
#   * группа 22 «Duplicate position prevention» — блокировка нового входа,
#     когда позиция уже есть (у брокера / в локальном monitor);
#   * группа 24 «Stale close order protection» — запрет новой SELL, пока
#     предыдущая заявка закрытия не разрешена (close_order_request_id /
#     нетерминальный журнал close_orders / незавершённая SELL в реестре).
# Остальные группы §4 покрыты существующими наборами (см. отчёт
# AUDIT_INTEGRITY.md). Тесты локальные, mock/stub, без сети.

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import main
from execution import ExecutionMonitor, PositionState
from order_ledger import OrderLedger
from risk_manager import RiskManager


def _setup_entry_env(monkeypatch, tmp_path, fake, monitor, *, trading_on=True):
    """Общая обвязка trading_cycle для проверки блокировки входов."""
    rm = MagicMock()
    sm = MagicMock()
    sm.get_signal = MagicMock(return_value=("BUY", "MA(9/21) ↑"))
    monkeypatch.setattr(main, "top_instruments", [{"figi": "F1", "ticker": "MVID"}])
    monkeypatch.setattr(main, "reconcile_done", True)
    monkeypatch.setattr(main, "state_save_failed", False)
    monkeypatch.setattr(main, "is_trading_enabled", MagicMock(return_value=trading_on))
    monkeypatch.setattr(main, "_save_state", MagicMock(return_value=True))
    monkeypatch.setattr(main, "reconcile", AsyncMock(return_value=None))
    ledger = OrderLedger(str(tmp_path / "order_ledger.jsonl"))
    monkeypatch.setattr(main, "ledger_ref", ledger)
    monitor.check_all = AsyncMock(return_value=[])
    return rm, sm


@pytest.mark.asyncio
async def test_trading_cycle_skips_entry_when_broker_position_exists(monkeypatch, tmp_path):
    """Группа 22: у брокера УЖЕ есть позиция по FIGI -> новый BUY НЕ отправляется
    (главный цикл, ветка «позиция уже открыта/в неопределённости»)."""
    from tinkoff_client import PositionData
    from decimal import Decimal

    fake = MagicMock()
    fake.get_last_prices = AsyncMock(return_value={"F1": 54.25})
    fake.get_positions = AsyncMock(return_value={
        "F1": PositionData(lots=1, direction="LONG", raw_shares=Decimal(1))})
    fake.post_market_order = AsyncMock()
    fake.is_uncertain = MagicMock(return_value=False)

    monitor = ExecutionMonitor(fake)
    rm, sm = _setup_entry_env(monkeypatch, tmp_path, fake, monitor)

    await main.trading_cycle(fake, rm, sm, monitor)
    assert fake.post_market_order.await_count == 0, \
        "Новый BUY отправлен при существующей позиции у брокера"
    assert monitor.has_active_position("F1") is False  # локальная позиция не создана


@pytest.mark.asyncio
async def test_trading_cycle_skips_entry_when_monitor_has_active_position(monkeypatch, tmp_path):
    """Группа 22: активная позиция в ЛОКАЛЬНОМ monitor (позиции брокера нет в
    снимке) -> новый BUY НЕ отправляется до разрешения (защита от дубля)."""
    fake = MagicMock()
    fake.get_last_prices = AsyncMock(return_value={"F1": 54.25})
    fake.get_positions = AsyncMock(return_value={})
    fake.post_market_order = AsyncMock()
    fake.is_uncertain = MagicMock(return_value=False)

    monitor = ExecutionMonitor(fake)
    monitor.register(figi="F1", ticker="MVID", direction="BUY",
                     entry_price=54.0, quantity=1, sl_price=53.0, tp_price=56.0,
                     lot_size=1, trade_id="tid-F1", entry_requested_lots=1)
    rm, sm = _setup_entry_env(monkeypatch, tmp_path, fake, monitor)

    await main.trading_cycle(fake, rm, sm, monitor)
    assert fake.post_market_order.await_count == 0, \
        "Новый BUY отправлен при активной локальной позиции"
    assert monitor.has_active_position("F1") is True


# ---------------------------------------------------------------------
# Группа 24: stale close order protection (_sell_block_reason)
# ---------------------------------------------------------------------

def _pos(**overrides):
    base = dict(direction="BUY", figi="F1", close_order_request_id=None,
                close_order_id=None, close_orders={})
    base.update(overrides)
    return SimpleNamespace(**base)


def test_sell_block_reason_blocks_unresolved_close_request_id():
    pos = _pos(close_order_request_id="req-123")
    reason = main._sell_block_reason(pos, None)
    assert reason is not None
    assert "close_order_request_id" in reason


def test_sell_block_reason_blocks_unresolved_close_order_id():
    pos = _pos(close_order_id="oid-1")
    assert main._sell_block_reason(pos, None) is not None


def test_sell_block_reason_blocks_nonterminal_close_journal():
    pos = _pos(close_orders={"o1": {"status": "NEW", "side": "SELL"}})
    reason = main._sell_block_reason(pos, None)
    assert reason is not None and "нетерминальном" in reason


def test_sell_block_reason_allows_terminal_close_journal():
    """Терминальные статусы журнала (включая сырые числовые коды) НЕ блокируют
    новую SELL — единое множество с execution._TERMINAL_SELL_STATUSES (OOS-4)."""
    for status in ("FILL", "CANCELLED", "REJECTED", "EXPIRED", "1", "2", "3"):
        pos = _pos(close_orders={"o1": {"status": status, "side": "SELL"}})
        assert main._sell_block_reason(pos, None) is None, f"статус {status} заблокировал SELL"


def test_sell_block_reason_blocks_open_sell_in_ledger(tmp_path):
    """Незавершённая SELL-запись реестра по FIGI (INTENT без исхода) блокирует
    повторную SELL — защита потерянного ответа после краха."""
    ledger = OrderLedger(str(tmp_path / "order_ledger.jsonl"))
    ok = ledger.record_intent("sell-intent-1", trade_id="t-1", figi="F1",
                              ticker="T", side="SELL", requested_lots=1)
    assert ok is True
    pos = _pos()
    reason = main._sell_block_reason(pos, ledger)
    assert reason is not None and "реестр" in reason


def test_sell_block_reason_clean_position_returns_none(tmp_path):
    ledger = OrderLedger(str(tmp_path / "order_ledger.jsonl"))
    ledger.load()
    assert main._sell_block_reason(_pos(), ledger) is None
