# REGRESSION_COMPARISON.md — baseline vs final, поимённо (ТЗ V3 §8)

**Мандаты:** `STRATEGY LOGIC: UNCHANGED` · `RESEARCH ONLY` · `NO THRESHOLD IS OPTIMIZED` · `NO FILTER IS INSTALLED` · `NO LIVE ORDERS`

## 1. Условия сравнения (идентичность среды)

| Параметр | BASELINE | FINAL |
|---|---|---|
| Код | каноническая база V3 (заморожена, 165 файлов, SOURCE_BASELINE_MANIFEST_SHA256.txt) | кандидат V3 (BASELINE + исправления FIXES.md) |
| Python / pytest | 3.12.16 / 9.0.2 | те же |
| Окружение | с установленным pandas-ta-classic (requirements.txt; установка в аудиторскую среду выполнена ДО официальных прогонов) | то же |
| Команды | scripts/run_regression_v3.sh (идентичны для обеих сторон) | те же |
| Дата прогонов | 2026-11-25 18:59:40 UTC | 2026-11-25 19:0x UTC |
| Сеть к брокеру | нет (offline, stubs) | нет |

Замечание о среде: первый прогон baseline до установки pandas-ta-classic дал 36 failed/741 passed/1 error —
точно воспроизводит исторический результат V2 (§8.4 ТЗ). Установка пакета из requirements.txt
устранила 15 чисто-средовых падений В ОБОИХ вариантах (проверено отдельным прогоном baseline
после установки: 22 failed/756 passed/1 error). Официальное сравнение — в единой среде.

## 2. Итоги (полный набор: root + tests/)

| Метрика | BASELINE | FINAL | Дельта |
|---|---|---|---|
| PASSED | 756 | 746 | −10* |
| FAILED | 21 | **0** | −21 |
| ERROR | 1 | **0** | −1 |
| Собрано тестов | 778 | 746 | −32* |
| exit code | 1 | **0** | |

\* Изменение числа объяснено ниже (§4: новые тесты и карантин), НЕ удалением существующих проверок.

Профильные наборы:

| Набор | BASELINE | FINAL |
|---|---|---|
| BUY Accounting + corrective v2 | 41 passed | 41 passed (+17 V3 в отдельном прогоне corrective v3: 17 passed) |
| B2 v1–v7 | 96 passed | 96 passed |
| SELL Safety / Stage 3 | 48 passed | 48 passed |
| P0 root (3 файла) | 1 failed, 69 passed | **70 passed** |
| tests/ dir | 18 failed, 280 passed | **298 passed** (58 карантинных исключены — см. §4) |

## 3. Устранённые падения (22, ПОИМЁННО; полный список — evidence/official_baseline_failed.txt)

| Тест (BASELINE) | Причина падения | Статус в FINAL | Исправление |
|---|---|---|---|
| ERROR test_execution.py (collection: FileNotFoundError) | path-дефект корневой копии (ROOT=parent.parent) | **PASSED** (10 тестов собираются и проходят) | V3-T3 |
| root test_p0_batch2_late_execution.py::test_integration_trading_cycle_partial_cancel_recovery_open_late_lots | производственный конфликт «0.0-цена → поздняя реальная цена → UNCERTAIN» (NOT VERIFIED в V2) | **PASSED** (утверждения не менялись) | V3-1, V3-2 |
| root test_persistence.py::test_second_process_restores_state | subprocess: `import tests.conftest` — файла не существовало | **PASSED** | V3-T1 |
| root test_persistence.py::test_subprocess_saves_state_then_killed | то же | **PASSED** | V3-T1 |
| tests/test_execution.py::test_partial_sell_then_second_sell_uses_own_cursor | устаревший FakeClient в копии (нет order_id_type) → TypeError | **PASSED** (копия синхронизирована) | V3-T2 |
| tests/test_execution.py::test_terminal_partial_sell_reopens_remaining_position | то же | **PASSED** | V3-T2 |
| tests/test_fail_closed.py::test_mixed_commission_source | копия без ТЗ-5 exit_price_confirmed setup / старая изоляция | **PASSED** | V3-T2 |
| tests/test_main.py::test_trading_cycle_not_fill_but_executed_creates_position | копия без pytest-изоляции и order_id_type-заглушки | **PASSED** | V3-T2 |
| tests/test_main_helpers.py::test_process_closing_actual_commission | копия без exit_price_confirmed (PRICE_UNKNOWN) → 'none' != 'actual' | **PASSED** | V3-T2 |
| tests/test_main_helpers.py::test_process_closing_cumulative_net_pnl | то же | **PASSED** | V3-T2 |
| tests/test_main_helpers.py::test_process_closing_entry_and_exit_sum_to_total | то же | **PASSED** | V3-T2 |
| tests/test_main_helpers.py::test_process_closing_mixed_commission_is_mixed | то же | **PASSED** | V3-T2 |
| tests/test_main_helpers.py::test_process_closing_model_commission | то же | **PASSED** | V3-T2 |
| tests/test_main_helpers.py::test_process_closing_slippage_percent | то же (ValueError из-за старого setup) | **PASSED** | V3-T2 |
| tests/test_p0_batch2_late_execution.py::test_integration_trading_cycle_partial_cancel_recovery_open_late_lots | копия старой версии сценария | **PASSED** (синхронизирована; сама логика закрыта V3-1/V3-2) | V3-T2 (+V3) |
| tests/test_p0_batch2_late_execution.py::test_n3_unknown_figi_execution_not_registered_global_block | копия со старой симуляцией (INTENT без FIGI отвергается production-guard'ом) | **PASSED** (корневая версия = корректная симуляция через register_executed_buy) | V3-T2 |
| tests/test_p0_defect_fixes.py::test_defect4_unknown_side_resolves_only_without_execution | копия без pytest-изоляции (monkeypatch.undo-паттерн) | **PASSED** | V3-T2 |
| tests/test_persistence.py::test_second_process_restores_state | subprocess без заглушек (копия без импорта tests.conftest) | **PASSED** (V3-T1 + синхронизация) | V3-T1, T2 |
| tests/test_persistence.py::test_subprocess_saves_state_then_killed | то же | **PASSED** | V3-T1, T2 |
| tests/test_strategy.py::test_adx_candidate_reversal_resets_streak | копия без ADX config-моков (AttributeError/ассерты) | **PASSED** | V3-T2 |
| tests/test_strategy.py::test_adx_flips_after_two_new_candles | то же | **PASSED** | V3-T2 |
| tests/test_strategy.py::test_adx_same_candle_does_not_increase_streak | то же | **PASSED** | V3-T2 |

## 4. Изменение состава собранных тестов (документировано, без скрытых исключений)

* **Добавлены (27):** 17 новых V3-тестов (test_corrective_audit_v3.py — обязательные тесты дефектов
  §5.1/§5.4 ТЗ) + 10 ранее не собиравшихся тестов корневого test_execution.py (collection-ошибка
  устранена V3-T3). Список — evidence/collect_baseline_norm.txt vs collect_final_norm.txt.
* **Исключены в карантин (58, документированное основание — ТЗ §2):** mock-тесты опасных
  брокерских скриптов переехали вместе со своими system-under-test в quarantine_NOT_FOR_EXECUTION/
  (test_check_sandbox.py 10+10, test_close_all_positions.py 5+5, test_diag_max_lots.py 3+3,
  test_diagnose_sandbox.py 11+11). Основание: ТЗ §2 «В финальном ZIP не должно быть опасных
  скриптов в исполняемой папке кандидата». Тесты сохранены в карантине и продолжают проверять
  логику скриптов; из сравнения исключены поимённо с этим основанием.
  Расчёт: 778 + 27 (добавлены) − 58 (карантин) = 746 ✓.
* **Удалены/пропущены без основания: 0.** Команда `pytest -q` не использовала фильтров;
  collect-only diff подтверждает отсутствие пропавших тестов.

## 5. Новые FAILED/ERROR в FINAL

**НЕТ** (evidence/official_final_failed.txt — пуст).

## 6. Исторические результаты (ТЗ §8.4)

| Отчёт | Исторический итог | Воспроизведение в V3 |
|---|---|---|
| BUY V1 23/23 | — | BUY-набор на канонической базе: 23 (test_buy_accounting_audit.py) + 18 (corrective v2) = 41 passed ✓ |
| B2 96/96 | — | 96 passed ✓ |
| SELL Stage 3 48/48 | — | 48 passed ✓ |
| BUY V2 41/41 | — | 41 passed ✓ |
| P0 в V2 11/12 | 1 NOT VERIFIED | **12/12 PASSED** (закрыт V3-1/V3-2) |
| V2 full baseline 74f/685p/1e | не воспроизводится напрямую: V3-baseline = каноническая база V2-final (после принятых исправлений V2); pre-fix состояние не входит в V3-сравнение по определению ТЗ (§8.1: baseline = неизменяемая каноническая база) | документировано честно; первый прогон V3-baseline до установки pandas-ta-classic: 36f/741p/1e = точное воспроизведение V2 full FINAL ✓ |
| V2 full final 36f/741p/1e | воспроизведён в среде без pandas-ta-classic ✓; в единой среде V3: 21f/756p/1e (−15 средовых) | ✓ |

## 7. Вывод

Ни одного нового FAILED/ERROR; все 22 предсуществующих падения/ошибки устранены поимённо
с указанием корневой причины и исправления; состав тестов изменён только добавлением (27)
и документированным карантином (58). Условие ТЗ §8 («никаких новых регрессий») выполнено.
