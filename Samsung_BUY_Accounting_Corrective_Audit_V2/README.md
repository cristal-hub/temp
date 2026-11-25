# README — Samsung_BUY_Accounting_Corrective_Audit_V2

**Дата:** 2026-11-25
**Мандаты:** `RESEARCH ONLY` · `NO LIVE ORDERS` · `NO SANDBOX ORDERS` ·
`NO GITHUB WRITES` · `STRATEGY LOGIC: UNCHANGED` · `NO THRESHOLD IS
OPTIMIZED` · `NO FILTER IS INSTALLED`

Корректирующий аудит кандидата **Samsung_BUY_Accounting_Audit_V1**
(интеграция B2 v1–v7) по ТЗ «Samsung BUY Accounting — исправления
атомарности, закрытие P0/SELL тестов и повторный независимый аудит».
Никаких торговых операций, никакой сети к брокеру; все прогоны — локальный
pytest на mock/stub-клиентах во временных каталогах; GitHub — только
read-only проверка контрольного коммита.

---

## 1. Что сделано (кратко)

| Пункт ТЗ | Результат | Статус |
|---|---|---|
| FIX-1: атомарность `_enrich_buy_entry_metadata()` | Переработана: validate → stage → commit → **проверяемое** сохранение; при ошибке записи — откат значений, без ложного подтверждения (event/True), fail-closed | **ВЫПОЛНЕН** (тесты A–F/G: 18/18; негативная валидация: 3 fail-режимных теста падают на старом коде) |
| FIX-2: 12 падений P0-тестов | Причина подтверждена поимённо: 11 — устаревшая заглушка `tests/test_p0_defect_fixes.py::FakeClient` (нет kwarg `order_id_type`), 1 — ошибка имени атрибута `Order_id_type` в `test_16`. Заглушки обновлены (только тестовая инфраструктура, явные именованные параметры, без `**kwargs`) | **11/12 ПРОЙДЕНЫ; 1/12 NOT VERIFIED** (`test_integration_trading_cycle_partial_cancel_recovery_open_late_lots` — семантический конфликт production-кода, см. п. 3 и `evidence/not_verified_integration_evidence.md`) |
| FIX-3-tests: регрессия нулевой комиссии SELL | 8 тестов: подтверждённый 0.0 / положительная / None / повтор отчёта / позднее получение / отсутствие бесконечного poll / недопущение двойного применения / семантика `_extract_commission` | **ВЫПОЛНЕН** |
| §6: проверка `or ""` на числовых метаданных | Проверены все места; дефектов НЕ обнаружено (чтение — из CSV-строк, где ноль пишется как «0.00»; путь записи сохраняет «0.00» для реального нуля). Добавлены 2 теста отсутствия лишнего polling | **ВЫПОЛНЕН (без изменения production)** |
| §7: защита B2 v1–v7 | 96/96 проходят на исправленном кандидате; diff не затрагивает B2-код | **ПОДТВЕРЖДЕНО** |
| §8: полная регрессия BASELINE vs FINAL | Идентичные команды/окружение; полная: 74 failed → 36 failed (38 исправлены ПОИМЁННО, **0 новых**); tests/: 49 → 24; P0-root: 12 → 1; B2/BUY/SELL — без изменений | **ВЫПОЛНЕНО** |
| §9: независимый review собственных изменений | Diff: 1 production-файл (одна функция), 2 тестовых файла (заглушки/имя атрибута), 1 новый тестовый файл; остальные 10 production-модулей байт-в-байт | **ВЫПОЛНЕНО** |
| §10: безопасность архива | Runtime-файлы, RESET/backup-архивы, вложенные ZIP-пакеты, 4 order-capable скрипта — исключены из `candidate/` и задокументированы (`DANGEROUS_SCRIPTS.md`); секретов нет | **ВЫПОЛНЕНО** |

## 2. Исходная точка и целостность

* Baseline Samsung: коммит `051b10f095d45c053492ca333449a9a9f518f33f`
  (HEAD `cristal-hub/cristal-hub-Tsclp_v2.1_volatile_Samsung`, проверен
  read-only 2026-11-25).
* SHA256 исходного Samsung baseline (совпадают с ТЗ):
  * `main.py` `8ed2293bb88bb96b196b451ff0dc468d9fdc96a856634907f5ee9191f2df6be6`
  * `execution.py` `72b19783d1d1e811e51c7522ba60f524ecffb7b57f393c34efd2c033680d40d2`
  * `logger.py` `266c937e2946058e6255b6584aee5c26e4e34dadaffeffe755eca7435924f164`
* Рабочая основа — кандидат `Samsung_BUY_Accounting_Audit_V1`
  (B2 v1–v7 интегрированы; наличие всех 7 B2-файлов проверено):
  * `main.py` `9cad7d500782c5a908f128f0e95e982eb6eab26750f94854e78d09edb313c772`
  * `execution.py` `03cec03b5015c390573d5f3bb30198cc7605a99669b8118e62361605ee561764`
  * `logger.py` `df22ed916cb2eda10473cb78c2f93846d0be00c8a7ad5913a6bab8d9ee8ad4c5`
* Расхождений с заявленной структурой НЕ обнаружено (п. 2 ТЗ выполнен без
  остановки).

## 3. Изменённые файлы (все изменения)

**Production (1 файл, 1 функция):**
* `main.py` — `_enrich_buy_entry_metadata()`: атомарность
  (validate → stage → commit → checked save → rollback при ошибке
  сохранения). Остальной main.py не изменён (один hunk diff).
  `9cad7d50…` → `2a2dd3f84648a84c2991087a5f3a646be5c07a02b6c6f6870ba027e5b6facc52`

**Тесты (2 изменены, 1 добавлен):**
* `tests/test_p0_defect_fixes.py` — заглушка FakeClient: добавлен явный
  параметр `order_id_type=None` в `get_sandbox_order_state` и `cancel_order`
  (сверка с корневой копией, семантика поиска не изменена).
  `b26878c4…` → `a6e1d2f4c2941d2db2de38254c6343341926d666e18b469d44db0b46b3453984`
* `test_p0_sell_id_fixes.py` — `tinkoff_client.Order_id_type` →
  `tinkoff_client.OrderIdType` (3 места, тест 16; семантика проверки не
  изменена). `1f1cd328…` → `7fc14b073545b0c1b6c7df50d843665df1a8035ef3c9e728b4097af893195001`
* `test_corrective_audit_v2.py` — НОВЫЙ (18 тестов FIX-1 A–F/G + SELL
  zero commission + needs_poll).
  `de585e60a793efaa4fb5837b02dac8fd778a6caa8599704e2d99bd731c3392ce`

**Не изменены (проверено SHA256):** execution.py, logger.py,
order_ledger.py, config.py, strategy.py, risk_manager.py, screener.py,
tinkoff_client.py, telegram_bot.py, conftest.py, все остальные тесты.

## 4. Команды воспроизведения тестов

Окружение: Linux; Python 3.12.16; pytest 9.0.2 (pytest-asyncio 1.3.0);
SDK t-tech-investments/pandas_ta_classic/python-telegram-bot ОТСУТСТВУЮТ —
используются заглушки conftest.py (та же среда, что у прогонов кандидата;
сравнение корректно).

```bash
# ВАЖНО (U-2): запускать pytest в КОПИИ каталога кандидата, не в рабочем
# каталоге с реальными runtime-файлами (часть тестов пишет
# research_events.jsonl/state.json в текущий каталог).

# 1. Новые тесты корректирующего аудита (FIX-1 A–F/G, SELL zero commission,
#    needs_poll) — 18 тестов:
PYTHONPATH=. python3 -m pytest test_corrective_audit_v2.py -v

# 2. BUY Accounting (23) + новые (18) = 41 passed:
PYTHONPATH=. python3 -m pytest test_buy_accounting_audit.py test_corrective_audit_v2.py -q

# 3. B2 v1–v7 (96 passed):
PYTHONPATH=. python3 -m pytest test_b2_close_accounting.py test_b2_csv_recovery.py \
  test_b2_terminal_metadata_recovery.py test_b2_v4_accounting_consistency.py \
  test_b2_v5_identity_and_timestamp.py test_b2_v6_timestamp_identity_close_reason.py \
  test_b2_v7_cursor_version_and_alt_timestamp.py -q

# 4. SELL Safety / Stage 3 (48 passed):
PYTHONPATH=. python3 -m pytest test_v232_close_defects.py test_v233_partial_sell_reopen_defect.py \
  test_stage1_packet_v.py test_stage1_s1_telemetry.py test_manual_close_integration.py -q

# 5. P0-тесты корня (69 passed / 1 failed — NOT VERIFIED, см. п. 5):
PYTHONPATH=. python3 -m pytest test_p0_defect_fixes.py test_p0_batch2_late_execution.py \
  test_p0_sell_id_fixes.py -q --continue-on-collection-errors

# 6. Полный набор (36 failed / 741 passed / 1 collection error; все 36 —
#    предсуществующие, поимённый список в REGRESSION_COMPARISON.md):
python3 -m pytest -q --continue-on-collection-errors
```

## 5. Известные ограничения

1. **1 из 12 P0-тестов — NOT VERIFIED** (не «упавших заглушек», а
   семантический конфликт production-кода, обнаруженный тестом после
   починки заглушек). Полное досье: `evidence/not_verified_integration_
   evidence.md`. Production-код по этому пункту НЕ исправлялся (ТЗ §4 п.7).
2. SDK брокера отсутствует — контракт `executed_order_price`/SDK не
   проверялся (унаследовано, U-5 предыдущего аудита).
3. Часть предсуществующих падений не относится к ТЗ и оставлена как есть
   (screener/ADX/persistence — отсутствие SDK; tests/ копии с устаревшими
   ожиданиями — «дрейф копий»; tests/test_main, tests/test_execution —
   свои устаревшие заглушки ВНЕ области 12 P0-тестов). Поимённо — в
   REGRESSION_COMPARISON.md.
4. WUSH BUY 495: первопричина по-прежнему не установлена (нет реальных
   артефактов инцидента) — «исправленным» не объявляется.
5. Запуск тестов в корне кандидата дописывает события в
   `research_events.jsonl` (предсуществующая особенность U-2) — запускать
   в копии; `candidate/` в архиве содержит исходные runtime-файлы в
   неизменном виде… точнее: runtime-файлы ИСКЛЮЧЕНЫ из кандидата по §10
   (см. DANGEROUS_SCRIPTS.md §4).

## 6. Состав архива

* `README.md` — этот файл
* `FINAL_VERDICT.md` — итоговый статус (PARTIAL) и критерии приёмки
* `AUDIT_REPORT.md` — полный отчёт аудита
* `FIXES.md` — описание каждого исправления с обоснованием
* `REGRESSION_COMPARISON.md` — baseline vs final, поимённо
* `TEST_RESULTS.md` — команды, exit codes, итоговые строки
* `UNVERIFIED_AND_RISKS.md` — всё неподтверждённое
* `DANGEROUS_SCRIPTS.md` — опасные скрипты и решения по упаковке
* `FULL_DIFF.patch` — полный diff (ORIGINAL → FINAL)
* `SHA256SUMS.txt` — контрольные суммы всех файлов архива
* `candidate/` — полный итоговый кандидат (production + тесты)
* `evidence/` — логи прогонов, списки FAILED, трейсбеки, досье NOT VERIFIED
