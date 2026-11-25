# samsung_merge_candidate_v7 — README (проверка пакета)

B2 V7 — CURSOR IDENTITY VERSION TRICHOTOMY + CONFIRMED ALTERNATIVE TIMESTAMP
(v2.3.10-stage1). Кандидат для НЕЗАВИСИМОГО аудита. База:
`samsung_merge_candidate_v6` (не изменялась). Samsung READ-ONLY.

## 1. Состав пакета

```
main.py                                        — изменён (Дефект №2)
execution.py                                   — изменён (Дефект №1)
logger.py                                      — БЕЗ изменений (включён для полноты)
test_b2_close_accounting.py                    — прежние B2-тесты v1 (20)
test_b2_csv_recovery.py                        — прежние B2-тесты v3 (14)
test_b2_terminal_metadata_recovery.py          — прежние B2-тесты v2 (8)
test_b2_v4_accounting_consistency.py           — прежние B2-тесты v4 (9)
test_b2_v5_identity_and_timestamp.py           — прежние B2-тесты v5 (10)
test_b2_v6_timestamp_identity_close_reason.py  — тесты V6-A..P (16)
test_b2_v7_cursor_version_and_alt_timestamp.py — НОВЫЕ тесты V7-A..M (19 pytest-итемов)
MERGE_REPORT.md                                — отчёт о работе
CHANGED_FILES.md                               — изменённые файлы + SHA256 до/после
FULL_DIFF.patch                                — полный diff против v6
TEST_RESULTS.txt                               — сводка всех прогонов
SHA256SUMS.txt                                 — SHA256 всех файлов пакета
appendix_BASELINE_FULL_PYTEST.txt              — полный baseline pytest (код v6)
appendix_BASELINE_B2_TESTS_OUTPUT.txt          — baseline ВСЕХ старых B2 v1–v6 (77) на коде v6
appendix_FINAL_FULL_PYTEST.txt                 — полный final pytest (код v7)
appendix_baseline_failed_names.txt             — FAILED/ERROR baseline ПО ИМЕНАМ
appendix_final_failed_names.txt                — FAILED/ERROR final ПО ИМЕНАМ
appendix_B2_TESTS_OUTPUT.txt                   — лог 61 прежнего B2-теста (v1–v5 файлы)
appendix_OLD_B2_TESTS_V1_V6_OUTPUT.txt         — лог ВСЕХ старых B2 v1–v6 (77)
appendix_V7_TESTS_OUTPUT.txt                   — лог 19 новых V7-тестов
appendix_NEGATIVE_VALIDATION_OLD_CODE.txt      — негативная валидация (V7 на коде v6)
```

## 2. Как распаковать и проверить SHA256

```bash
unzip Tsclp_B2_V7_candidate.zip -d v7_check
cd v7_check/samsung_merge_candidate_v7
sha256sum -c SHA256SUMS.txt
```

Все строки должны быть `OK` (или `ПРОШЕЛ`). Отдельно сверить исходники с
базой v6, если она доступна:

| Файл | SHA256 (v7) |
|---|---|
| main.py | `fac787ac6d51b377efec35aff4122971ad681c3e9a463739e64e0c5938162777` |
| execution.py | `6fd0ed195392085c503d0d696e3a7d72d7cf0b691dd6bf29bf8f03a3be9ede00` |
| logger.py | `df22ed916cb2eda10473cb78c2f93846d0be00c8a7ad5913a6bab8d9ee8ad4c5` (не менялся) |

## 3. Как воспроизвести тесты

Папка — самодостаточный НАБОР файлов кандидата (исходники B2-цепочки +
тесты). Для прогона тестов файлы кладутся в КОРЕНЬ рабочего дерева робота
(там же, где config.py, order_ledger.py, conftest.py, risk_manager.py,
screener.py, strategy.py, tinkoff_client.py, telegram_bot.py), поверх кода
v6. Ничего, кроме перечисленных файлов, заменять не нужно.

```bash
# все 96 старых и новых B2/V6/V7-тестов (77 старых + 19 новых):
python3 -m pytest -p no:cacheprovider -q \
  test_b2_close_accounting.py test_b2_csv_recovery.py \
  test_b2_terminal_metadata_recovery.py test_b2_v4_accounting_consistency.py \
  test_b2_v5_identity_and_timestamp.py \
  test_b2_v6_timestamp_identity_close_reason.py \
  test_b2_v7_cursor_version_and_alt_timestamp.py

# полный pytest (74 pre-existing FAILED + 1 collection error
# test_execution.py НЕ связаны с B2 — см. TEST_RESULTS.txt):
python3 -m pytest -p no:cacheprovider --continue-on-collection-errors -q
```

Ожидаемые результаты: 61 прежних B2 (v1–v5 файлы) = passed; 16 V6 = passed
(77 старых всего); 19 V7 = passed; полный pytest — 74 failed / 662 passed /
1 error с FAILED-набором, ПОБАЙТОВО совпадающим по именам с
`appendix_final_failed_names.txt`.

Требования: Python 3.12, pytest 9.x, зависимости рабочего дерева
(pandas и пр. — как в основном репозитории). Сеть, токены и реальный
брокер НЕ нужны: все тесты — fake-объекты и tmp_path.

## 4. Что проверять аудитору (краткая карта)

1. FULL_DIFF.patch — границы изменений: ТОЛЬКО трёхсостоянийая
   классификация cursor'а и единая точка проверки (execution.py);
   `_alt_cursor_identity_conflict` + проверка идентичности альтернативного
   cursor'а в `_restore_close_requested_at` (main.py). Стратегия/сигналы/
   BUY/SL/TP/RiskManager/screener/logger не тронуты.
2. Дефект №1 (некорректная версия != legacy): appendix_V7_TESTS_OUTPUT.txt
   (V7-C, V7-D, V7-E×7, V7-F) + негативная валидация (на v6 падают);
   V7-A/B — контроль несмешивания состояний (только отсутствие ключа —
   legacy; поддерживаемая версия — strict/full).
3. Дефект №2 (альтернативный cursor без подтверждения идентичности):
   V7-G (принимается ТОЛЬКО подтверждённый), V7-H/I/J/K (отказы по
   trade_id/FIGI/side/order_id/версии), V7-L (None + legacy-политика,
   datetime.now() не подставляется), V7-M (две сделки одного FIGI —
   смешивание невозможно).
4. Fail-closed протокол recovery-задач при некорректной версии: V7-C/V7-F
   (задача сохраняется с диагностической причиной, брокер не опрашивается,
   CSV не обновляется, задача не удаляется, маркер не «повышается»).
5. Исправление отчётности V6: фактические количества прежних B2-тестов —
   61 (20+14+8+9+10), а не 51 (см. MERGE_REPORT.md §4.5); сверьте
   `appendix_B2_TESTS_OUTPUT.txt` — `collected 61 items`, `61 passed`.
6. Сравнение FAILED по именам: diff двух appendix_*_failed_names.txt —
   пусто (набор совпадает и с финальным набором v6).

## Подтверждение

STRATEGY LOGIC: UNCHANGED
RESEARCH ONLY
NO THRESHOLD IS OPTIMIZED
NO FILTER IS INSTALLED
NO LIVE ORDERS
OOS SEALED / H4 EXECUTION NOT AUTHORIZED
