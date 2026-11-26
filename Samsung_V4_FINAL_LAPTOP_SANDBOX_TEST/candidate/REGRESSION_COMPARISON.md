# REGRESSION COMPARISON — поимённое сравнение FAILED/ERROR (baseline → final)

Метод: полный pytest, единые флаги для baseline и final:
`pytest -q --no-header -p no:cacheprovider --import-mode=importlib --continue-on-collection-errors`,
`PYTHONPATH=<корень каталога кандидата>`. Имена извлечены из секции
`=== short test summary info ===` каждого лога; суффиксы « - …» отброшены.

| Прогон | Итог | Лог |
|---|---|---|
| Baseline (кандидат B2 v1–v7, до BUY-фиксов) | `74 failed, 662 passed, 1 error` | `FULL_PYTEST_BASELINE.txt` |
| Final (после BUY-фиксов) | `74 failed, 685 passed, 1 error` | `FULL_PYTEST_FINAL.txt` |

Разница passed: **+23** — ровно количество новых BUY-тестов
(`test_buy_accounting_audit.py`), все прошли.

## Поимённое сравнение (нормализованные имена, без суффиксов ошибок)

- Имя списка baseline: 75 записей (74 FAILED + 1 ERROR collection).
- Имя списка final: 75 записей (74 FAILED + 1 ERROR collection).
- **Новые FAILED/ERROR (regressions): 0**
- **Исчезнувшие FAILED/ERROR: 0**
- Списки идентичны как множества (полный список — в конце файла).

## Воспроизводимость baseline

Baseline этого аудита поимённо ИДЕНТИЧЕН baseline предыдущего исполнителя
(`appendix_baseline_failed_names.txt`, после нормализации: 75 = 75, 0
расхождений) и по счётчикам совпадает с `appendix_FINAL_FULL_PYTEST.txt`
(«74 failed, 662 passed, 1 error»).

## Известные (унаследованные) падения — НЕ являются регрессией этого аудита

1. `ERROR test_execution.py` — артефакт сбора корневой копии
   `test_execution.py` (ROOT = parent.parent). Присутствует и в
   baseline-прогоне предыдущего исполнителя.
2. 74 FAILED — known-failures кандидата/Samsung (пред-/B2-этапов), например:
   тесты `test_p0_batch2_late_execution.py` (FakeClient в
   `tests/test_p0_defect_fixes.py` не принимает kwarg `order_id_type` —
   несоответствие тестовой инфраструктуры, существовало до аудита),
   `test_v232_close_defects.py`, `test_v233_partial_sell_reopen_defect.py`,
   `test_buy_registration_fix2*.py::test_g_primary_buy_unsaved_state` и др.

## B2 v1–v7 (отдельная проверка сохранности)

| Набор | До | После |
|---|---|---|
| 7 файлов `test_b2_*.py` (96 тестов) | 96 passed | **96 passed** (B2-тесты не изменялись) |

## Негативная валидация фиксов

23 новых BUY-теста на коде ДО фиксов (`NEGATIVE_VALIDATION_BUY_TESTS.txt`):
`7 failed, 16 passed` — доказывают дефекты D1–D6. После фиксов: `23 passed`
(`BUY_TEST_RESULTS.txt`).

## Полный список FAILED/ERROR (идентичен в baseline и final)

```
ERROR test_execution.py
FAILED test_buy_registration_fix2.py::test_g_primary_buy_unsaved_state
FAILED test_buy_registration_fix2_FIX2_snapshot.py::test_g_primary_buy_unsaved_state
FAILED test_p0_batch2_late_execution.py::test_integration_trading_cycle_partial_cancel_recovery_open_late_lots
FAILED test_p0_batch2_late_execution.py::test_n1_no_premotion_while_order_alive
FAILED test_p0_batch2_late_execution.py::test_n1_promotion_only_at_terminal_syncs_final_quantity
FAILED test_p0_batch2_late_execution.py::test_n4_late_growth_after_terminal_cancelled_actually_repolled
FAILED test_p0_batch2_late_execution.py::test_p03_1_repeated_buy_report_does_not_restore_sold_lots
FAILED test_p0_batch2_late_execution.py::test_p03_2_stale_buy_report_contradiction_blocks_buy
FAILED test_p0_batch2_late_execution.py::test_p04_reconcile_before_poll_no_reapply_of_late_lots
FAILED test_p0_batch2_late_execution.py::test_p05_1_first_ambiguous_growth_sets_uncertain
FAILED test_p0_batch2_late_execution.py::test_p05_2_repeated_same_lots_poll_keeps_uncertain
FAILED test_p0_batch2_late_execution.py::test_p05_3_failed_or_contradictory_reconcile_keeps_uncertain
FAILED test_p0_batch2_late_execution.py::test_p05_4_successful_reconcile_allows_resolution_no_side_effects
FAILED test_p0_sell_id_fixes.py::test_16_request_lookup_unavailable_fails_closed
FAILED test_persistence.py::test_second_process_restores_state
FAILED test_persistence.py::test_subprocess_saves_state_then_killed
FAILED test_screener.py::test_screener_cache
FAILED test_screener.py::test_screener_error_does_not_return_stale_cache
FAILED test_screener.py::test_screener_filters_low_turnover
FAILED test_screener.py::test_screener_partial_scan_returns_none
FAILED test_screener.py::test_screener_returns_top_n
FAILED test_screener.py::test_screener_valid_result_less_than_10
FAILED test_strategy.py::test_adx_candidate_reversal_resets_streak
FAILED test_strategy.py::test_adx_flips_after_two_new_candles
FAILED test_strategy.py::test_adx_same_candle_does_not_increase_streak
FAILED tests/test_buy_registration_fix2 (1).py::test_g_primary_buy_unsaved_state
FAILED tests/test_buy_registration_fix2.py::test_g_primary_buy_unsaved_state
FAILED tests/test_buy_registration_fix2_FIX2_snapshot.py::test_g_primary_buy_unsaved_state
FAILED tests/test_execution.py::test_partial_sell_then_second_sell_uses_own_cursor
FAILED tests/test_execution.py::test_terminal_partial_sell_reopens_remaining_position
FAILED tests/test_fail_closed.py::test_mixed_commission_source
FAILED tests/test_main.py::test_trading_cycle_not_fill_but_executed_creates_position
FAILED tests/test_main_helpers.py::test_process_closing_actual_commission
FAILED tests/test_main_helpers.py::test_process_closing_cumulative_net_pnl
FAILED tests/test_main_helpers.py::test_process_closing_entry_and_exit_sum_to_total
FAILED tests/test_main_helpers.py::test_process_closing_mixed_commission_is_mixed
FAILED tests/test_main_helpers.py::test_process_closing_model_commission
FAILED tests/test_main_helpers.py::test_process_closing_slippage_percent
FAILED tests/test_p0_batch2_late_execution.py::test_integration_trading_cycle_partial_cancel_recovery_open_late_lots
FAILED tests/test_p0_batch2_late_execution.py::test_n1_no_premotion_while_order_alive
FAILED tests/test_p0_batch2_late_execution.py::test_n1_promotion_only_at_terminal_syncs_final_quantity
FAILED tests/test_p0_batch2_late_execution.py::test_n3_unknown_figi_execution_not_registered_global_block
FAILED tests/test_p0_batch2_late_execution.py::test_n4_late_growth_after_terminal_cancelled_actually_repolled
FAILED tests/test_p0_batch2_late_execution.py::test_p03_1_repeated_buy_report_does_not_restore_sold_lots
FAILED tests/test_p0_batch2_late_execution.py::test_p03_2_stale_buy_report_contradiction_blocks_buy
FAILED tests/test_p0_batch2_late_execution.py::test_p04_reconcile_before_poll_no_reapply_of_late_lots
FAILED tests/test_p0_batch2_late_execution.py::test_p05_1_first_ambiguous_growth_sets_uncertain
FAILED tests/test_p0_batch2_late_execution.py::test_p05_2_repeated_same_lots_poll_keeps_uncertain
FAILED tests/test_p0_batch2_late_execution.py::test_p05_3_failed_or_contradictory_reconcile_keeps_uncertain
FAILED tests/test_p0_batch2_late_execution.py::test_p05_4_successful_reconcile_allows_resolution_no_side_effects
FAILED tests/test_p0_defect_fixes.py::test_defect1_unavailable_portfolio_with_confirmed_lots_registers
FAILED tests/test_p0_defect_fixes.py::test_defect2_only_executed_quantity_registered
FAILED tests/test_p0_defect_fixes.py::test_defect4_unknown_side_resolves_only_without_execution
FAILED tests/test_p0_defect_fixes.py::test_defect8_poll_fill_zero_lots_stays_uncertain
FAILED tests/test_p0_defect_fixes.py::test_poll_registers_before_cancel
FAILED tests/test_p0_defect_fixes.py::test_scenario_14_fill_zero_lots_resolves_after_reconnect
FAILED tests/test_p0_defect_fixes.py::test_scenario_16_registered_partial_not_added_again
FAILED tests/test_p0_defect_fixes.py::test_scenario_1_partial_buy_cancelled_portfolio_silent
FAILED tests/test_p0_defect_fixes.py::test_scenario_2_cancelled_with_executed_lots
FAILED tests/test_p0_defect_fixes.py::test_scenario_3_expired_with_executed_lots
FAILED tests/test_p0_defect_fixes.py::test_scenario_4_repeated_poll_no_quantity_doubling
FAILED tests/test_p0_defect_fixes.py::test_scenario_5_late_execution_after_cancel
FAILED tests/test_p0_defect_fixes.py::test_scenario_6_new_order_regularly_polled_reaches_timeout
FAILED tests/test_persistence.py::test_second_process_restores_state
FAILED tests/test_persistence.py::test_subprocess_saves_state_then_killed
FAILED tests/test_screener.py::test_screener_cache
FAILED tests/test_screener.py::test_screener_error_does_not_return_stale_cache
FAILED tests/test_screener.py::test_screener_filters_low_turnover
FAILED tests/test_screener.py::test_screener_partial_scan_returns_none
FAILED tests/test_screener.py::test_screener_returns_top_n
FAILED tests/test_screener.py::test_screener_valid_result_less_than_10
FAILED tests/test_strategy.py::test_adx_candidate_reversal_resets_streak
FAILED tests/test_strategy.py::test_adx_flips_after_two_new_candles
FAILED tests/test_strategy.py::test_adx_same_candle_does_not_increase_streak
```
