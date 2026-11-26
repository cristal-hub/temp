# REGRESSION_COMPARISON.md — точное сравнение BASELINE (V3) ↔ V4 (ТЗ V4 §9)

**Мандаты:** `STRATEGY LOGIC: UNCHANGED` · `RESEARCH ONLY` · `NO LIVE ORDERS`

База сравнения: полный набор (root + tests/), идентичные команды и среда
(Python 3.12.16, pytest 9.0.2, Linux), имена тестов нормализованы к путям от корня
кандидата. Первоисточники: `evidence/lists/baseline_v3_collect_names.txt`,
`evidence/lists/final_v4_collect_names.txt`, логи в `evidence/logs/`.

## 1. Сводка

| Показатель | BASELINE (V3) | V4 |
|---|---|---|
| Тестов в полном наборе | 746 | 789 |
| FAILED | 0 | 0 |
| ERROR | 0 | 0 |
| Collection errors | 0 | 0 |

## 2. Поимённые списки

* **FAILED baseline:** пусто — `evidence/lists/baseline_v3_failed_error_names.txt`.
* **ERROR baseline:** пусто (тот же файл, один протокол).
* **FAILED V4:** пусто — `evidence/lists/final_v4_failed_error_names.txt`.
* **ERROR V4:** пусто.
* **Устранённые ошибки:** 0 (устранять нечего — baseline полностью green).
* **Новые ошибки:** 0.
* **Новые тесты (43):** `evidence/lists/evidence_names_new_in_v4.txt` — все 43 имени
  перечислены; состав: 17 (test_v4_order_ledger_first_append.py) + 18
  (test_v4_safety_build.py) + 8 (test_v4_integration_integrity.py).
* **Тесты, исключённые из исполнения:** 0. Карантин V4 = карантин V3 (58 позиций,
  унаследованы без изменений вместе с обоснованием DANGEROUS_SCRIPTS.md V3; в V4
  ничего не добавлялось и не удалялось — отдельного обоснования не требуется).
* **Потерянные из baseline: 0** — `evidence/lists/evidence_names_lost_from_baseline.txt`
  пуст: каждый из 746 baseline-тестов присутствует в V4 под тем же именем.

## 3. Контрольные профильные наборы (ТЗ §9)

| Профиль | Baseline | V4 | Разница |
|---|---|---|---|
| BUY Accounting (+ corrective v2) | 41 passed | 41 passed | 0 |
| B2 v1–v7 | 96 passed | 96 passed | 0 |
| SELL Safety / Stage 3 | 48 passed | 48 passed | 0 |
| P0 root | 70 passed | 70 passed | 0 |
| V3 corrective | 17 passed | 17 passed | 0 |
| V4 new (3 файла) | — | 43 passed | +43 (новые) |
| tests/ dir | 269 passed | 269 passed | 0 |
| FULL | 746p/0f/0e | 789p/0f/0e | +43 новых, 0 удалённых, 0 сменили статус |

## 4. Вывод

Регрессий нет: ни один baseline-тест не удалён, не переименован и не сменил статус;
все 43 добавленных теста проходят. Состав тестов изменён ТОЛЬКО добавлением
(ТЗ §9: «нельзя удалять тесты или переносить их в quarantine без отдельного
обоснования» — таких операций в V4 нет).
