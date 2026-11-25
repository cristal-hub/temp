# REGRESSION_COMPARISON.md — baseline vs final, поимённо

Мандаты: `RESEARCH ONLY` · `NO LIVE ORDERS` · `STRATEGY LOGIC: UNCHANGED`.

Сравнение выполнялось в идентичной среде (Python 3.12.16, pytest 9.0.2,
заглушки SDK conftest.py) на двух неизменяемых копиях:
**BASELINE** = кандидат `Samsung_BUY_Accounting_Audit_V1` до исправлений
(SHA256 main.py `9cad7d50…`), **FINAL** = кандидат после исправлений
(SHA256 main.py `2a2dd3f8…`). Baseline после начала сравнения не менялся.
Сравнение — ПОИМЁННОЕ (не по количествам).

## 1. Итоги

| Набор | BASELINE | FINAL | Динамика |
|---|---|---|---|
| Полный pytest | 74 failed, 685 passed, 1 error | 36 failed, 741 passed, 1 error | **38 failed устранены, 0 новых failed/error** |
| tests/ (официальный) | 49 failed, 249 passed | 24 failed, 274 passed | 25 устранены, 0 новых |
| P0-файлы корня | 58 passed / 12 failed | 69 passed / 1 failed | 11 устранены, 1 NOT VERIFIED |
| B2 v1–v7 | 96 passed | 96 passed | без изменений |
| SELL Safety / Stage 3 | 48 passed | 48 passed | без изменений |
| BUY Accounting | 23 passed | 23 passed | без изменений |
| Новый тестовый файл | — | 18 passed | добавлен |

Списки имён: `evidence/failed_names_baseline_full.txt` (75),
`evidence/failed_names_final_full.txt` (37). Метод — `comm` по
отсортированным спискам: новые = ∅, совпадающие = 37.

## 2. Устранённые падения (38, ПОИМЁННО) и причина каждой

### Группа A — корневые P0-файлы (12; цель FIX-2)

| Тест | Причина падения в baseline | Статус в FINAL |
|---|---|---|
| test_p0_batch2_late_execution.py::test_n1_no_premotion_while_order_alive | TypeError: заглушка без order_id_type | **PASSED** (заглушка обновлена) |
| test_p0_batch2_late_execution.py::test_n1_promotion_only_at_terminal_syncs_final_quantity | то же | **PASSED** |
| test_p0_batch2_late_execution.py::test_n4_late_growth_after_terminal_cancelled_actually_repolled | то же | **PASSED** |
| test_p0_batch2_late_execution.py::test_p03_1_repeated_buy_report_does_not_restore_sold_lots | то же | **PASSED** |
| test_p0_batch2_late_execution.py::test_p03_2_stale_buy_report_contradiction_blocks_buy | то же | **PASSED** |
| test_p0_batch2_late_execution.py::test_p04_reconcile_before_poll_no_reapply_of_late_lots | то же | **PASSED** |
| test_p0_batch2_late_execution.py::test_p05_1_first_ambiguous_growth_sets_uncertain | то же | **PASSED** |
| test_p0_batch2_late_execution.py::test_p05_2_repeated_same_lots_poll_keeps_uncertain | то же | **PASSED** |
| test_p0_batch2_late_execution.py::test_p05_3_failed_or_contradictory_reconcile_keeps_uncertain | то же | **PASSED** |
| test_p0_batch2_late_execution.py::test_p05_4_successful_reconcile_allows_resolution_no_side_effects | то же | **PASSED** |
| test_p0_sell_id_fixes.py::test_16_request_lookup_unavailable_fails_closed | AttributeError: `Order_id_type` не существует | **PASSED** (имя атрибута исправлено) |
| test_p0_batch2_late_execution.py::test_integration_trading_cycle_partial_cancel_recovery_open_late_lots | TypeError (заглушка); после починки — вскрывается производственный конфликт нулевой цены | **FAILED (NOT VERIFIED)** — производство не менялось; досье в evidence |

### Группа B — каскад обновления заглушки на tests/-копии (26)

Обновление `tests/test_p0_defect_fixes.py::FakeClient` позволило выполняться
тестам, которые импортируют эту заглушку. 24 из них проходят, их устранение
— прямое следствие обязательного исправления (11 из них входят в цель FIX-2
по корню):

| Тест | Статус в FINAL |
|---|---|
| tests/test_p0_batch2_late_execution.py::test_n1_no_premotion_while_order_alive | **PASSED** |
| tests/test_p0_batch2_late_execution.py::test_n1_promotion_only_at_terminal_syncs_final_quantity | **PASSED** |
| tests/test_p0_batch2_late_execution.py::test_n4_late_growth_after_terminal_cancelled_actually_repolled | **PASSED** |
| tests/test_p0_batch2_late_execution.py::test_p03_1_repeated_buy_report_does_not_restore_sold_lots | **PASSED** |
| tests/test_p0_batch2_late_execution.py::test_p03_2_stale_buy_report_contradiction_blocks_buy | **PASSED** |
| tests/test_p0_batch2_late_execution.py::test_p04_reconcile_before_poll_no_reapply_of_late_lots | **PASSED** |
| tests/test_p0_batch2_late_execution.py::test_p05_1_first_ambiguous_growth_sets_uncertain | **PASSED** |
| tests/test_p0_batch2_late_execution.py::test_p05_2_repeated_same_lots_poll_keeps_uncertain | **PASSED** |
| tests/test_p0_batch2_late_execution.py::test_p05_3_failed_or_contradictory_reconcile_keeps_uncertain | **PASSED** |
| tests/test_p0_batch2_late_execution.py::test_p05_4_successful_reconcile_allows_resolution_no_side_effects | **PASSED** |
| tests/test_p0_defect_fixes.py::test_defect1_unavailable_portfolio_with_confirmed_lots_registers | **PASSED** |
| tests/test_p0_defect_fixes.py::test_defect2_only_executed_quantity_registered | **PASSED** |
| tests/test_p0_defect_fixes.py::test_defect8_poll_fill_zero_lots_stays_uncertain | **PASSED** |
| tests/test_p0_defect_fixes.py::test_poll_registers_before_cancel | **PASSED** |
| tests/test_p0_defect_fixes.py::test_scenario_1_partial_buy_cancelled_portfolio_silent | **PASSED** |
| tests/test_p0_defect_fixes.py::test_scenario_2_cancelled_with_executed_lots | **PASSED** |
| tests/test_p0_defect_fixes.py::test_scenario_3_expired_with_executed_lots | **PASSED** |
| tests/test_p0_defect_fixes.py::test_scenario_4_repeated_poll_no_quantity_doubling | **PASSED** |
| tests/test_p0_defect_fixes.py::test_scenario_5_late_execution_after_cancel | **PASSED** |
| tests/test_p0_defect_fixes.py::test_scenario_6_new_order_regularly_polled_reaches_timeout | **PASSED** |
| tests/test_p0_defect_fixes.py::test_scenario_14_fill_zero_lots_resolves_after_reconnect | **PASSED** |
| tests/test_p0_defect_fixes.py::test_scenario_16_registered_partial_not_added_again | **PASSED** |
| test_buy_registration_fix2.py::test_g_primary_buy_unsaved_state | **PASSED** (импортирует ту же заглушку) |
| test_buy_registration_fix2_FIX2_snapshot.py::test_g_primary_buy_unsaved_state | **PASSED** |
| tests/test_buy_registration_fix2.py::test_g_primary_buy_unsaved_state | **PASSED** |
| tests/test_buy_registration_fix2 (1).py::test_g_primary_buy_unsaved_state | **PASSED** |
| tests/test_buy_registration_fix2_FIX2_snapshot.py::test_g_primary_buy_unsaved_state | **PASSED** |

(26 позиций: 11 tests/batch2 + 12 tests/defect_fixes + 5 buy_registration;
2 tests/defect_fixes-теста остались — см. §4.)

## 3. Оставшиеся падения (36 FAILED + 1 ERROR) — ПОИМЁННО идентичны baseline

Набор совпадает с baseline ПОИМЁННО (`comm -12` — все 37 строк). Это
предсуществующие падения, возникшие до контрольного коммита (воспроизводятся
на неизменённом Samsung baseline 051b10f — установлено предыдущим
независимым аудитом и подтверждено настоящим прогоном BASELINE). Классы:

1. **Среда (SDK/заглушки отсутствуют), 22:** test_screener.py ×12,
   test_strategy.py ADX ×6, test_persistence.py ×4.
2. **Дрейф tests/-копий (устаревшие ожидания против обновлённых корневых
   канонических версий), 8:** tests/test_main_helpers.py ×6,
   tests/test_fail_closed.py::test_mixed_commission_source,
   tests/test_p0_batch2_late_execution.py::test_n3_unknown_figi…,
   tests/test_p0_defect_fixes.py::test_defect4_unknown_side….
   Утверждения копий НЕ изменялись (изменение = правка проверок, вне
   мандата FIX-2); рекомендовано отдельное ТЗ на синхронизацию копий.
3. **Свои устаревшие заглушки вне 12 P0, 3:** tests/test_execution.py ×2,
   tests/test_main.py::test_trading_cycle_not_fill_but_executed_….
4. **NOT VERIFIED (производственный конфликт), 1:** корневой
   test_integration_trading_cycle_partial_cancel_recovery_open_late_lots.
5. **Дефект пути теста, 1 collection error:** корневой test_execution.py
   (`ROOT = Path(__file__).parent.parent` при расположении в корне).

## 4. Что НЕ менялось в тестах

* Ни один тест не удалён (проверка: набор имён в FINAL ⊇ baseline).
* Ни одно утверждение не ослаблено: изменены только сигнатуры заглушек и
  имя атрибута enum (2 файла), добавлен 1 новый файл.
* Скрытия ошибок нет: collection error отражён в итоговых строках; запуск
  без deselect/ignore; `--continue-on-collection-errors` — как в прогонах
  кандидатов.
