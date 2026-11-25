# MERGE_REPORT — samsung_merge_candidate_v6 (v2.3.9-stage1)

**B2 V6 — FINAL TIMESTAMP INTEGRITY + STRICT RECOVERY IDENTITY + EMPTY CLOSE REASON**

Дата: 2026-11-24. База: `samsung_merge_candidate_v5` (v2.3.8-stage1).
Папка `samsung_merge_candidate_v5` НЕ изменялась; создана независимая копия
`samsung_merge_candidate_v6`. Samsung-репозиторий READ-ONLY, не изменялся;
LIVE ORDERS и sandbox BUY/SELL не выполнялись; торговые методы брокера не
вызывались.

## 1. Цель

Три точечных исправления по независимому аудиту v5 (без переделки
архитектуры B2, без глобального рефакторинга):

* **Defect A** — перезапись первоначального времени запроса SELL временем
  позднего B2 reconcile (`updated_at_utc` реестра / `datetime.now()`).
* **Defect B** — недостаточно строгая проверка идентичности per-order
  cursor'а при восстановлении pending CSV recovery (пустые обязательные
  поля не считались конфликтом).
* **Defect C** — IndexError при пустом `close_reason` в
  `_try_resolve_absent_position()` (`"close:"` -> `.split()[0]`).

## 2. Фиксация базы v5

* git: `cristal-hub/temp` @ `faee75d53176ce7d1dad5f648950811d3cbe0b69`
  (2026-11-24 18:04:59 +0300, "Add files via upload"); папка
  `samsung_merge_candidate_v5/` в дереве; blob-хэши git всех исходников и
  тестов v5 совпали с локальной копией (побайтово).
* SHA256 исходников v5:
  * main.py `00d7fdfc813f4a98672790314e2a3e530e34471a73a40836220a93c7a471fe07`
  * execution.py `2b4ca67f61e816457f66f4d75a3b25dcecc2672815637be0febc300bc219b7fd`
  * logger.py `df22ed916cb2eda10473cb78c2f93846d0be00c8a7ad5913a6bab8d9ee8ad4c5`
* v6-копия создана из полного рабочего дерева с кодом v5 в корне
  (`env_v6`); baseline прогон выполнен на ЭТОЙ КОПИИ ДО изменений —
  различие baseline/final гарантированно исчерпывается изменениями v6.

## 3. Реализация исправлений

Кратко (полные детали — в CHANGED_FILES.md, полный diff — FULL_DIFF.patch):

* **Defect A (main.py)**: вместо перезаписи `pos.close_requested_at`
  значениями `rec.updated_at_utc` / `rec.timestamp_utc` / `datetime.now()`
  введена `_restore_close_requested_at(pos, oid)`: 1) существующее валидное
  значение — неизменяемый факт; 2) `requested_at` СВОЕГО cursor'а;
  3) `requested_at` собственной записи close_orders через другой сохранённый
  идентификатор этой же заявки; 4) иначе None (legacy-политика записи CSV
  применяется отдельно и явно; `timestamp_utc` в CSV остаётся пустым —
  подстановка не выдаётся за сохранённое время). Проверены все пути
  восстановления B2 (resolve_closing / apply_close_execution /
  _recover_late_csv_metadata `_close_requested_at` и `exit_time` не трогают;
  В3 `_finalize_position_closed` — отдельная явная legacy-политика для
  закрытий БЕЗ своей заявки, не менялась).
* **Defect B (execution.py)**: `add_close_order()` ставит в новые cursor'ы
  маркер `identity_version=2`; `validate_recovery_identity()` раздельно
  проверяет НОВЫЙ формат (обязательные trade_id/FIGI/side/order_id==ключу;
  пустое поле -> `cursor_missing_*`; противоречие -> `cursor_*_mismatch`) и
  LEGACY (проверка всех ДОСТУПНЫХ идентификаторов; противоречие fail-closed;
  неполнота НЕ выдаётся за полную — `cursor_validation="legacy_limited"`
  персистентен в задаче); вторая ссылка той же close-заявки тоже
  проверяется на противоречие; `cursor_validation` исключён из тела
  дедупликации. Fail-closed протокол v5 сохранён полностью.
* **Defect C (main.py)**: безопасный разбор причины — пустой/пробельный
  хвост `"close:"` не вызывает исключения; явная причина из реестра ->
  прежняя известная причина позиции -> существующий fallback
  `"LEDGER_CLOSE"`; обычные причины разбираются как раньше; функция
  переписана точечно, логика закрытия не затронута.

## 4. Тестирование

Окружение: Python 3.12.16, pytest 9.0.2, Linux sandbox. Команда прогонов:

```
python3 -m pytest -p no:cacheprovider --continue-on-collection-errors -q
```

### 4.1 Baseline (точный код v5, до изменений v6)

**74 failed, 627 passed, 1 error** — лог `appendix_BASELINE_FULL_PYTEST.txt`.
FAILED/ERROR-набор ПО ИМЕНАМ: `appendix_baseline_failed_names.txt`
(74 FAILED + 1 collection error `test_execution.py` — pre-existing, не
связан с B2; набор совпадает с финальным набором v5).

### 4.2 Final (после изменений v6)

**74 failed, 643 passed, 1 error** — лог `appendix_FINAL_FULL_PYTEST.txt`.
Разница с baseline: **+16 passed** (новые тесты V6-A..P).

### 4.3 Сравнение по КОНКРЕТНЫМ ИМЕНАМ (не по количеству)

```
diff appendix_baseline_failed_names.txt appendix_final_failed_names.txt
=> пусто
```

Ни одного нового или исчезнувшего FAILED; ERROR/collection errors сравнены
отдельно: единственный ERROR — pre-existing collection error корневого
`test_execution.py`, идентичен в baseline и final. Совпадение количества
не использовалось как доказательство отсутствия регрессий.

### 4.4 Прежние B2-тесты (51) на коде v6 — 51 passed

```
test_b2_close_accounting.py             20 passed
test_b2_csv_recovery.py                 10 passed
test_b2_terminal_metadata_recovery.py   12 passed
test_b2_v4_accounting_consistency.py     9 passed
test_b2_v5_identity_and_timestamp.py    10 passed
---------------------------------------------
ИТОГО                                   51 passed
```
Лог: `appendix_B2_TESTS_OUTPUT.txt`.

### 4.5 Новые тесты V6-A..P (16) на коде v6 — 16 passed

Файл `test_b2_v6_timestamp_identity_close_reason.py`; лог
`appendix_V6_TESTS_OUTPUT.txt`:

| Тест | Сценарий | Результат |
|---|---|---|
| V6-A | перезапись timestamp через B2 reconcile исключена (09:05 остаётся, updated_at_utc=10:20 не подставляется) | PASSED |
| V6-B | close_requested_at=None -> восстановление из СВОЕГО cursor'а (09:05), не из ledger | PASSED |
| V6-C | исторического времени нет -> None; datetime.now() в recovery не подставляется; legacy-политика явно на записи CSV | PASSED |
| V6-D | timestamp другой сделки не используется; неоднозначная привязка cursor'а — fail-closed | PASSED |
| V6-E | новый cursor без trade_id -> cursor_missing_trade_id, fail-closed | PASSED |
| V6-F | новый cursor без FIGI (пустое) -> cursor_missing_figi, fail-closed | PASSED |
| V6-G | новый cursor без side -> cursor_missing_side, fail-closed | PASSED |
| V6-H | новый cursor с неправильным trade_id/FIGI/side/order_id -> каждый конфликт распознан | PASSED |
| V6-I | корректный новый cursor -> штатное восстановление (cursor_validation=full) | PASSED |
| V6-J | корректный legacy cursor -> штатная legacy-ветка (cursor_validation=legacy_limited) | PASSED |
| V6-K | legacy cursor с противоречащим FIGI/order ID -> fail-closed | PASSED |
| V6-L | конфликтная задача после ДВУХ перезапусков остаётся заблокированной, не опрашивает брокера | PASSED |
| V6-M | reason_text="close:", причина неизвестна -> НЕТ IndexError, fallback LEDGER_CLOSE | PASSED |
| V6-N | reason_text="close:", прежняя причина известна -> сохранена | PASSED |
| V6-O | обычная причина close:STOP_LOSS -> STOP_LOSS (как раньше) | PASSED |
| V6-P | пустая причина в ПОЛНОМ reconcile UNCERTAIN-позиции -> без исключений и побочных торговых действий | PASSED |

### 4.6 Негативная валидация (V6-тесты на коде v5, до исправлений)

**15 failed, 1 passed** — лог `appendix_NEGATIVE_VALIDATION_OLD_CODE.txt`.
V6-A..N и V6-P падают на v5 (ловят дефекты A/B/C); V6-O проходит
(регрессионный guard: обычная причина разбиралась корректно и раньше).

## 5. Сохранность v1–v5 (проверено тестами, без регрессий)

* B2 close accounting (per-order cursor, идемпотентность, fail-closed) —
  test_b2_close_accounting.py: 20 passed;
* terminal duplicate enrichment / late metadata —
  test_b2_terminal_metadata_recovery.py: 12 passed;
* CSV late metadata recovery, атомарная запись, chronological cumulative
  P&L, deterministic tie-breaker, cross-contamination —
  test_b2_csv_recovery.py: 10 passed;
* persistent pending recovery, перезапуск, стабильный trade_id, requested/
  executed lots, отсутствие CSV-дубликатов —
  test_b2_v4_accounting_consistency.py: 9 passed;
* сохранение времени запроса SELL и fail-closed идентичность v5 —
  test_b2_v5_identity_and_timestamp.py: 10 passed;
* полный pytest: FAILED/ERROR-набор по именам идентичен baseline.

## 6. Проверка diff на изменения вне scope

Изменены ТОЛЬКО main.py и execution.py (+ новый тест-файл). logger.py,
конфигурация, стратегия, сигналы, BUY, SL/TP, RiskManager, screener,
фильтры/пороги, отправка заявок, B3 — НЕ тронуты (см. FULL_DIFF.patch —
только `_restore_close_requested_at`/`_valid_saved_ts` + разбор причины в
main.py; только cursor-идентичность в execution.py).

## 7. Ограничения соблюдены

* v1–v5 не перезаписаны; Samsung READ-ONLY; коммитов в Samsung нет;
* старый temp/main.py как база не использовался;
* LIVE ORDERS / sandbox BUY/SELL / торговые методы брокера — не выполнялись;
* реальные state.json не редактировались (все тесты — fake-объекты и tmp_path);
* глобального рефакторинга нет.

## Подтверждение

STRATEGY LOGIC: UNCHANGED

RESEARCH ONLY

NO THRESHOLD IS OPTIMIZED

NO FILTER IS INSTALLED

NO LIVE ORDERS

OOS SEALED / H4 EXECUTION NOT AUTHORIZED
