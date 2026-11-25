# TEST_RESULTS.md — результаты тестирования (ТЗ V3 §8)

**Мандаты:** `STRATEGY LOGIC: UNCHANGED` · `RESEARCH ONLY` · `NO LIVE ORDERS`
Все прогоны — офлайн, mock/stub, временные каталоги. Команды — scripts/run_regression_v3.sh
(идентичны для baseline и final). Среда: Python 3.12.16, pytest 9.0.2.

---

## 1. Официальные прогоны (единая среда, после установки pandas-ta-classic из requirements.txt)

### BASELINE (каноническая база, без изменений) — 2026-11-25 18:59:40 UTC

| Прогон | Результат | exit |
|---|---|---|
| BUY Accounting + corrective v2 | 41 passed | 0 |
| B2 v1–v7 | 96 passed | 0 |
| SELL Safety / Stage 3 | 48 passed | 0 |
| P0 root files | 1 failed, 69 passed | 1 |
| FULL (root + tests/) | **21 failed, 756 passed, 1 error** | 1 |
| tests/ dir | 18 failed, 280 passed | 1 |

Точные имена FAILED/ERROR: `evidence/official_baseline_failed.txt` (22 позиции).

### FINAL (кандидат V3, после карантина опасных скриптов) — 2026-11-25 19:0x UTC

| Прогон | Результат | exit |
|---|---|---|
| BUY Accounting + corrective v2 | 41 passed | 0 |
| B2 v1–v7 | 96 passed | 0 |
| SELL Safety / Stage 3 | 48 passed | 0 |
| P0 root files | **70 passed** | 0 |
| FULL (root + tests/) | **746 passed, 0 failed, 0 errors** | 0 |
| tests/ dir | 298 passed | 0 |
| NEW: V3 corrective tests (отдельный прогон) | **17 passed** | 0 |

Точные имена FAILED/ERROR: `evidence/official_final_failed.txt` (пуст — падений нет).

## 2. История прогонов в ходе аудита (для прозрачности)

| Прогон | Среда | Результат | Комментарий |
|---|---|---|---|
| baseline_v3 (до установки pandas-ta-classic) | без пакета | 36f/741p/1e; tests/: 24f/274p | точно воспроизводит исторический V2 final (§8.4 ТЗ) |
| baseline_v3b / baseline_v3_final | с пакетом | 22f/756p/1e → 21f/756p/1e | −1: удалён инструментальный диагностический файл из BASELINE; база снова байт-в-байт = манифесту |
| final_v3 (до карантина) | с пакетом | 804p/0f/0e | все 36f/741p/1e устранены |
| final_v3_quar (официальный) | с пакетом | 746p/0f/0e | −58: mock-тесты опасных скриптов в карантине (ТЗ §2) |

## 3. Профильные наборы (обязательные, ТЗ §8.3)

| Профиль | Baseline | Final | Примечание |
|---|---|---|---|
| BUY Accounting | 23/23 + 18 corrective = 41 | 41 | без изменений |
| B2 v1–v7 | 96/96 | 96/96 | production B2-код не менялся |
| SELL Safety / Stage 3 | 48/48 | 48/48 | |
| P0 | 11/12 + 1 NOT VERIFIED | **12/12** | §5.14 закрыт |
| Новые V3 tests | отсутствуют | 17/17 | тесты дефектов §5.1/§5.4 |
| Полная регрессия | 21f/756p/1e | 746p/0f/0e | см. REGRESSION_COMPARISON.md |

## 4. NOT RUN / NOT VERIFIED

* **NOT RUN:** mock-тесты карантинных скриптов в составе полного набора кандидата
  (58 items) — исключены вместе с system-under-test по ТЗ §2; сами тесты сохранены
  в quarantine_NOT_FOR_EXECUTION/ и там исполняемы.
* **NOT VERIFIED (окружение):** t-tech-investments==1.51.0 (приватный пакет, недоступен
  в аудиторской среде) — интеграционные тесты против РЕАЛЬНОГО SDK не выполнялись;
  conftest-заглушки (штатный CI-режим проекта) покрывают этот пробел, но контракт
  SDK в живом окружении остаётся вне проверки V3 (см. UNVERIFIED_AND_RISKS.md).
* **NOT VERIFIED (брокер):** любые сценарии на реальном/sandbox брокере — вне RESEARCH-мандата.

Статусы «NOT VERIFIED» не засчитаны как PASS нигде в этом отчёте.

## 5. Воспроизводимость

Каждый тест запускается из корня кандидата: `python3 -m pytest -q` (полный набор),
`PYTHONPATH=. python3 -m pytest <файлы>` (профильные). Все зависимости — requirements.txt
(pandas, pandas-ta-classic, python-telegram-bot, python-dotenv, pytest, pytest-asyncio —
из PyPI; t-tech-investments — приватный, см. §4).
