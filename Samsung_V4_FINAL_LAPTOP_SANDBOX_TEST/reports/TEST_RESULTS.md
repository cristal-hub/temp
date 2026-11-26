# TEST_RESULTS.md — результаты тестирования V4 (ТЗ V4 §9)

**Мандаты:** `STRATEGY LOGIC: UNCHANGED` · `RESEARCH ONLY` · `NO THRESHOLD IS OPTIMIZED` ·
`NO FILTER IS INSTALLED` · `NO LIVE ORDERS`
Все прогоны — офлайн, mock/stub, временные каталоги. Команды идентичны для BASELINE
и V4 (`evidence/logs/*.log`, протокол — scripts/run_regression_v4.sh).
Среда аудита: **Python 3.12.16, pytest 9.0.2, Linux** (Windows-запуск — НЕ проверено,
см. KNOWN_ISSUES §2).

---

## 1. Официальные прогоны (единая среда)

### BASELINE = принятый кандидат V3 (без изменений) — 2026-11-25

| Прогон | Результат | exit | Совпадение с V3 |
|---|---|---|---|
| BUY Accounting + corrective v2 | 41 passed | 0 | = официальному V3 |
| B2 v1–v7 | 96 passed | 0 | = |
| SELL Safety / Stage 3 | 48 passed | 0 | = |
| P0 root files | 70 passed | 0 | = |
| V3 corrective tests | 17 passed | 0 | = |
| FULL (root + tests/) | **746 passed, 0 failed, 0 errors** | 0 | = (официальный evidence V3) |
| tests/ dir | 269 passed | 0 | = официальной evidence-записи V3 (см. KNOWN_ISSUES §4) |

### FINAL = кандидат V4 — 2026-11-25

| Прогон | Результат | exit |
|---|---|---|
| BUY Accounting + corrective v2 | 41 passed | 0 |
| B2 v1–v7 | 96 passed | 0 |
| SELL Safety / Stage 3 | 48 passed | 0 |
| P0 root files | 70 passed | 0 |
| V3 corrective tests | 17 passed | 0 |
| NEW: V4 tests (3 файла) | **43 passed** | 0 |
| FULL (root + tests/) | **789 passed, 0 failed, 0 errors** | 0 |
| tests/ dir | 269 passed | 0 |

## 2. Контрольная арифметика (ТЗ §9)

* BASELINE: 746 test items (не считая отдельные collection errors — их в финальном
  наборе нет; проверено `--collect-only`: 746).
* V4: 789 = 746 + **43 новых теста V4**. Удалённых/карантинизированных в V4: **0**.
* Разница к официальным цифрам V3: полный набор 746 совпал точно; к историческому
  «746 после карантина» вопросов нет. Замечание по числу «298» для tests/ dir в
  таблице V3 (реально 269 в evidence) — `KNOWN_ISSUES.md` §4, на арифметику V4 не влияет.
* Неустранённых FAILED/ERROR нет ни у одной стороны: **FAILED/ERROR baseline = 0,
  V4 = 0** (поимённые списки — `evidence/lists/baseline_v3_failed_error_names.txt`
  и `final_v4_failed_error_names.txt`, оба пусты).

## 3. Точное сравнение baseline ↔ V4 (по именам тестов)

Списки имён: `evidence/lists/…collect_names.txt` (нормализованы к путям от корня
кандидата). Результат:

* **Новых тестов: 43** (`evidence/lists/evidence_names_new_in_v4.txt`):
  * `test_v4_order_ledger_first_append.py` — 17 (ТЗ §2: 15 обязательных + 2 на
    единообразие путей record_sent/record_observation);
  * `test_v4_safety_build.py` — 18 (ТЗ §7/§8);
  * `test_v4_integration_integrity.py` — 8 (группы 22/24 ТЗ §4).
* **Устранённых ошибок: 0** (устранять нечего — baseline green).
* **Новых ошибок: 0**.
* **Потерянных из baseline: 0** (`evidence_names_lost_from_baseline.txt` пуст).
* **Исключённых из исполнения: 0**; quarantine в V4 не менялся (те же 58 позиций,
  исключённые в V3 вместе с system-under-test; файлы — `quarantine_NOT_FOR_EXECUTION/`).

## 4. Профильные наборы и карантин

* Карантин опасных скриптов и их mock-тестов — унаследован из V3 без изменений
  (обоснование — DANGEROUS_SCRIPTS.md V3; скрипты в кандидате отсутствуют).
* Runtime-изоляция (ТЗ §5): после полного прогона V4 корень кандидата пуст
  (state.json / research_events.jsonl / research_trades.csv / order_ledger.jsonl /
  trading.flag не создаются). В BASELINE V3 тем же набором создавались
  research_events.jsonl + research_trades.csv (воспроизведено и задокументировано
  в `reports/AUDIT_INTEGRITY.md` §5).

## 5. NOT RUN / NOT VERIFIED

* **NOT RUN:** 58 mock-тестов карантинных скриптов (унаследовано из V3, см. выше).
* **NOT VERIFIED (окружение):** живой SDK `t-tech-investments==1.51.0` (приватный,
  недоступен; прогоны на заглушках conftest — штатный CI-режим проекта);
  фактический Windows-запуск (среда аудита — Linux).
* **NOT VERIFIED (брокер):** любые сценарии с реальным/sandbox брокером — вне мандата.
* Статусы NOT VERIFIED нигде не засчитаны как PASS.

## 6. Воспроизводимость

Из корня кандидата: полный набор `python -m pytest -q`; профильные —
`PYTHONPATH=. python -m pytest <файлы> -q`. Зависимости — `requirements.txt`
(pandas, pandas-ta-classic, python-telegram-bot, python-dotenv, pytest,
pytest-asyncio — PyPI; t-tech-investments — приватный, см. §5). Полные логи —
`evidence/logs/`.
