# samsung_merge_candidate_v6 — README (проверка пакета)

B2 V6 — FINAL TIMESTAMP INTEGRITY + STRICT RECOVERY IDENTITY + EMPTY CLOSE
REASON (v2.3.9-stage1). Кандидат для НЕЗАВИСИМОГО аудита. База:
`samsung_merge_candidate_v5` (не изменялась). Samsung READ-ONLY.

## 1. Состав пакета

```
main.py                                        — изменён (Defect A, C)
execution.py                                   — изменён (Defect B)
logger.py                                      — БЕЗ изменений (включён для полноты)
test_b2_close_accounting.py                    — прежние B2-тесты v1 (20)
test_b2_csv_recovery.py                        — прежние B2-тесты v3 (10)
test_b2_terminal_metadata_recovery.py          — прежние B2-тесты v2 (12)
test_b2_v4_accounting_consistency.py           — прежние B2-тесты v4 (9)
test_b2_v5_identity_and_timestamp.py           — прежние B2-тесты v5 (10)
test_b2_v6_timestamp_identity_close_reason.py  — НОВЫЕ тесты V6-A..P (16)
MERGE_REPORT.md                                — отчёт о работе
CHANGED_FILES.md                               — изменённые файлы + SHA256 до/после
FULL_DIFF.patch                                — полный diff против v5
TEST_RESULTS.txt                               — сводка всех прогонов
SHA256SUMS.txt                                 — SHA256 всех файлов пакета
appendix_BASELINE_FULL_PYTEST.txt              — полный baseline pytest (код v5)
appendix_FINAL_FULL_PYTEST.txt                 — полный final pytest (код v6)
appendix_baseline_failed_names.txt             — FAILED/ERROR baseline ПО ИМЕНАМ
appendix_final_failed_names.txt                — FAILED/ERROR final ПО ИМЕНАМ
appendix_B2_TESTS_OUTPUT.txt                   — лог 51 прежнего B2-теста
appendix_V6_TESTS_OUTPUT.txt                   — лог 16 новых V6-тестов
appendix_NEGATIVE_VALIDATION_OLD_CODE.txt      — негативная валидация (V6 на коде v5)
```

## 2. Как распаковать и проверить SHA256

```bash
unzip Tsclp_B2_V6_candidate.zip -d v6_check
cd v6_check/samsung_merge_candidate_v6
sha256sum -c SHA256SUMS.txt
```

Все строки должны быть `OK` (или `ПРОШЕЛ`). Отдельно сверить исходники с
базой v5, если она доступна:

| Файл | SHA256 (v6) |
|---|---|
| main.py | `2fcd992a691947ad8afba7d4bf336d828b1ab6fd5cf8c4ba3acebc5450338aae` |
| execution.py | `db62dd127e4ac06acd7061cbb90bcfb6e29187119fc59d2540dd1039d5f5cd8f` |
| logger.py | `df22ed916cb2eda10473cb78c2f93846d0be00c8a7ad5913a6bab8d9ee8ad4c5` (не менялся) |

## 3. Как воспроизвести тесты

Папка — самодостаточный НАБОР файлов кандидата (исходники B2-цепочки +
тесты). Для прогона тестов файлы кладутся в КОРЕНЬ рабочего дерева робота
(там же, где config.py, order_ledger.py, conftest.py, risk_manager.py,
screener.py, strategy.py, tinkoff_client.py, telegram_bot.py), поверх кода
v5. Ничего, кроме перечисленных файлов, заменять не нужно.

```bash
# все 67 B2/V6-тестов (51 прежних + 16 новых):
python3 -m pytest -p no:cacheprovider -q \
  test_b2_close_accounting.py test_b2_csv_recovery.py \
  test_b2_terminal_metadata_recovery.py test_b2_v4_accounting_consistency.py \
  test_b2_v5_identity_and_timestamp.py \
  test_b2_v6_timestamp_identity_close_reason.py

# полный pytest (74 pre-existing FAILED + 1 collection error
# test_execution.py НЕ связаны с B2 — см. TEST_RESULTS.txt):
python3 -m pytest -p no:cacheprovider --continue-on-collection-errors -q
```

Ожидаемые результаты: 51 прежних B2 = passed; 16 V6 = passed; полный pytest —
74 failed / 643 passed / 1 error с FAILED-набором, ПОБАЙТОВО совпадающим по
именам с `appendix_final_failed_names.txt`.

Требования: Python 3.12, pytest 9.x, зависимости рабочего дерева
(pandas и пр. — как в основном репозитории). Сеть, токены и реальный
брокер НЕ нужны: все тесты — fake-объекты и tmp_path.

## 4. Что проверять аудитору (краткая карта)

1. FULL_DIFF.patch — границы изменений: ТОЛЬКО `_restore_close_requested_at`
   / `_valid_saved_ts` + разбор причины (main.py); cursor-идентичность
   (execution.py). Стратегия/сигналы/BUY/SL/TP/RiskManager/screener не тронуты.
2. Defect A: appendix_V6_TESTS_OUTPUT.txt (V6-A..D) + негативная валидация
   (на v5 падают).
3. Defect B: V6-E..L (строгий новый формат, отдельная legacy-политика,
   персистентная блокировка).
4. Defect C: V6-M..P (нет IndexError, fallback/сохранение причины,
   семантика обычных причин не изменилась).
5. Сравнение FAILED по именам: diff двух appendix_*_failed_names.txt — пусто.

## Подтверждение

STRATEGY LOGIC: UNCHANGED
RESEARCH ONLY
NO THRESHOLD IS OPTIMIZED
NO FILTER IS INSTALLED
NO LIVE ORDERS
OOS SEALED / H4 EXECUTION NOT AUTHORIZED
