# REGRESSION_COMPARISON.md — поимённое сравнение baseline и final

Среда: Python 3.12.16, pytest 9.0.2, Linux; идентичные команды
`python3 -m pytest -q --continue-on-collection-errors`; полные копии деревьев.
Полные логи приложены (`logs/full_base.log`, `logs/full_b2.log`,
`logs/full_buy.log`).

## 1. Итоги

| Дерево | passed | failed | collection error | Новые тесты vs предыдущее дерево |
|---|---|---|---|---|
| Baseline `051b10f` | 566 | 74 | 1 (test_execution.py, корень) | — |
| B2 `samsung_B2_integrated_v1_v7` | 662 | 74 | 1 (тот же) | +96 passed, failed не изменились |
| BUY `Samsung_BUY_Accounting_Audit_V1` | 685 | 74 | 1 (тот же) | +23 passed, failed не изменились |

+96 = 7 новых B2-тестовых файлов (96 тестов, все проходят).
+23 = `test_buy_accounting_audit.py` (23 теста, все проходят).

## 2. Поимённое сравнение набора FAILED (точные имена тестов)

Метод: из каждого прогона извлечены строки `FAILED <test id>`; текст исключений
отброшен; списки отсортированы; выполнен `diff`.

| Пара сравнения | Результат diff |
|---|---|
| baseline (мой прогон) vs B2 (мой прогон) | **ПУСТО — идентичны** |
| B2 (мой прогон) vs BUY (мой прогон) | **ПУСТО — идентичны** |
| baseline (мой прогон) vs BUY (мой прогон) | **ПУСТО — идентичны** |
| BUY (мой прогон) vs `FULL_PYTEST_FINAL.txt` кандидата | **ПУСТО — идентичны** |
| `FULL_PYTEST_BASELINE.txt` vs `FULL_PYTEST_FINAL.txt` кандидата | **ПУСТО — идентичны** |

**Вывод: ни одного нового падения, ни одного исчезнувшего падения, ни одного
переименованного падения. Кандидаты B2 и BUY не создали регрессий в тестовом
наборе.**

## 3. Полный список 74 FAILED (общий для всех деревьев)

```
test_buy_registration_fix2.py::test_g_primary_buy_unsaved_state
test_buy_registration_fix2_FIX2_snapshot.py::test_g_primary_buy_unsaved_state
test_p0_batch2_late_execution.py::test_integration_trading_cycle_partial_cancel_recovery_open_late_lots
test_p0_batch2_late_execution.py::test_n1_no_premotion_while_order_alive
test_p0_batch2_late_execution.py::test_n1_promotion_only_at_terminal_syncs_final_quantity
test_p0_batch2_late_execution.py::test_n4_late_growth_after_terminal_cancelled_actually_repolled
test_p0_batch2_late_execution.py::test_p03_1_repeated_buy_report_does_not_restore_sold_lots
test_p0_batch2_late_execution.py::test_p03_2_stale_buy_report_contradiction_blocks_buy
test_p0_batch2_late_execution.py::test_p04_reconcile_before_poll_no_reapply_of_late_lots
test_p0_batch2_late_execution.py::test_p05_1_first_ambiguous_growth_sets_uncertain
test_p0_batch2_late_execution.py::test_p05_2_repeated_same_lots_poll_keeps_uncertain
test_p0_batch2_late_execution.py::test_p05_3_failed_or_contradictory_reconcile_keeps_uncertain
test_p0_batch2_late_execution.py::test_p05_4_successful_reconcile_allows_resolution_no_side_effects
test_p0_sell_id_fixes.py::test_16_request_lookup_unavailable_fails_closed
test_persistence.py::test_second_process_restores_state
test_persistence.py::test_subprocess_saves_state_then_killed
test_screener.py::test_screener_cache
test_screener.py::test_screener_error_does_not_return_stale_cache
test_screener.py::test_screener_filters_low_turnover
test_screener.py::test_screener_partial_scan_returns_none
test_screener.py::test_screener_returns_top_n
test_screener.py::test_screener_valid_result_less_than_10
test_strategy.py::test_adx_candidate_reversal_resets_streak
test_strategy.py::test_adx_flips_after_two_new_candles
test_strategy.py::test_adx_same_candle_does_not_increase_streak
tests/test_buy_registration_fix2 (1).py::test_g_primary_buy_unsaved_state
tests/test_buy_registration_fix2.py::test_g_primary_buy_unsaved_state
tests/test_buy_registration_fix2_FIX2_snapshot.py::test_g_primary_buy_unsaved_state
tests/test_execution.py::test_partial_sell_then_second_sell_uses_own_cursor
tests/test_execution.py::test_terminal_partial_sell_reopens_remaining_position
tests/test_fail_closed.py::test_mixed_commission_source
tests/test_main.py::test_trading_cycle_not_fill_but_executed_creates_position
tests/test_main_helpers.py::test_process_closing_actual_commission
tests/test_main_helpers.py::test_process_closing_cumulative_net_pnl
tests/test_main_helpers.py::test_process_closing_entry_and_exit_sum_to_total
tests/test_main_helpers.py::test_process_closing_mixed_commission_is_mixed
tests/test_main_helpers.py::test_process_closing_model_commission
tests/test_main_helpers.py::test_process_closing_slippage_percent
tests/test_p0_batch2_late_execution.py::test_integration_trading_cycle_partial_cancel_recovery_open_late_lots
tests/test_p0_batch2_late_execution.py::test_n1_no_premotion_while_order_alive
tests/test_p0_batch2_late_execution.py::test_n1_promotion_only_at_terminal_syncs_final_quantity
tests/test_p0_batch2_late_execution.py::test_n3_unknown_figi_execution_not_registered_global_block
tests/test_p0_batch2_late_execution.py::test_n4_late_growth_after_terminal_cancelled_actually_repolled
tests/test_p0_batch2_late_execution.py::test_p03_1_repeated_buy_report_does_not_restore_sold_lots
tests/test_p0_batch2_late_execution.py::test_p03_2_stale_buy_report_contradiction_blocks_buy
tests/test_p0_batch2_late_execution.py::test_p04_reconcile_before_poll_no_reapply_of_late_lots
tests/test_p0_batch2_late_execution.py::test_p05_1_first_ambiguous_growth_sets_uncertain
tests/test_p0_batch2_late_execution.py::test_p05_2_repeated_same_lots_poll_keeps_uncertain
tests/test_p0_batch2_late_execution.py::test_p05_3_failed_or_contradictory_reconcile_keeps_uncertain
tests/test_p0_batch2_late_execution.py::test_p05_4_successful_reconcile_allows_resolution_no_side_effects
tests/test_p0_defect_fixes.py::test_defect1_unavailable_portfolio_with_confirmed_lots_registers
tests/test_p0_defect_fixes.py::test_defect2_only_executed_quantity_registered
tests/test_p0_defect_fixes.py::test_defect4_unknown_side_resolves_only_without_execution
tests/test_p0_defect_fixes.py::test_defect8_poll_fill_zero_lots_stays_uncertain
tests/test_p0_defect_fixes.py::test_poll_registers_before_cancel
tests/test_p0_defect_fixes.py::test_scenario_14_fill_zero_lots_resolves_after_reconnect
tests/test_p0_defect_fixes.py::test_scenario_16_registered_partial_not_added_again
tests/test_p0_defect_fixes.py::test_scenario_1_partial_buy_cancelled_portfolio_silent
tests/test_p0_defect_fixes.py::test_scenario_2_cancelled_with_executed_lots
tests/test_p0_defect_fixes.py::test_scenario_3_expired_with_executed_lots
tests/test_p0_defect_fixes.py::test_scenario_4_repeated_poll_no_quantity_doubling
tests/test_p0_defect_fixes.py::test_scenario_5_late_execution_after_cancel
tests/test_p0_defect_fixes.py::test_scenario_6_new_order_regularly_polled_reaches_timeout
tests/test_persistence.py::test_second_process_restores_state
tests/test_persistence.py::test_subprocess_saves_state_then_killed
tests/test_screener.py::test_screener_cache
tests/test_screener.py::test_screener_error_does_not_return_stale_cache
tests/test_screener.py::test_screener_filters_low_turnover
tests/test_screener.py::test_screener_partial_scan_returns_none
tests/test_screener.py::test_screener_returns_top_n
tests/test_screener.py::test_screener_valid_result_less_than_10
tests/test_strategy.py::test_adx_candidate_reversal_resets_streak
tests/test_strategy.py::test_adx_flips_after_two_new_candles
tests/test_strategy.py::test_adx_same_candle_does_not_increase_streak
```

Collection error (все деревья, не входит в 74):
`test_execution.py` (корень) — `FileNotFoundError` из-за
`ROOT = Path(__file__).resolve().parent.parent` при расположении файла в корне.

## 4. Классификация падений (см. TEST_RESULTS.md §4)

* ~34 — устаревшие FakeClient-заглушки без kwarg `order_id_type`
  (введён ЭТАП 5Б, присутствующим уже в baseline): P0-батчи,
  buy_registration_fix2, tests/test_main, tests/test_execution.
* 12 — screener: отсутствие SDK (заглушки conftest), assert на содержимое.
* 6 — strategy ADX: заглушка pandas_ta_classic без `adx`.
* 4 — persistence: subprocess.
* 7 — tests/test_main_helpers.py + tests/test_fail_closed.py: семантический
  дрейф «commission_source 'none' vs 'model'» при PRICE_UNKNOWN.
* 1 — collection error корневого test_execution.py (путь).

Все группы воспроизводятся на неизменном baseline — регрессий кандидатов нет;
однако покрытие перечисленных сценариев фактически потеряно до обновления
заглушек (см. UNVERIFIED_AND_RISKS.md U-3/R-4).

## 5. Дополнительные проверки кандидата, воспроизведённые независимо

| Заявление кандидата | Моя проверка | Совпадение |
|---|---|---|
| `appendix_TEST_RESULTS_B2_v1_v7.txt`: «96 passed» | мой прогон: 96 passed | да |
| `BUY_TEST_RESULTS.txt`: «23 passed» | мой прогон: 23 passed | да |
| KNOWN_LIMITATIONS §1: «74 FAILED + 1 collection error, идентичны baseline/final по именам» | подтверждено (diff пуст) | да |
| B2_TEST_RESULTS.txt: «96 passed» | подтверждено | да |
| Регрессионное сравнение REGRESSION_COMPARISON.md кандидата | подтверждено поимённо | да |
| CHANGED_FILES.md §4: runtime-файлы идентичны baseline | **ОПРОВЕРГНУТО** (state.json сброшен, research_events.jsonl +160 событий) — см. UNVERIFIED_AND_RISKS.md U-1/U-2 | НЕТ |
