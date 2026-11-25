# ACCEPTED_FIXES_MATRIX.md — сохранность принятых исправлений (ТЗ V3 §7)

Проверка присутствия каждого принятого исправления **в итоговом production-коде кандидата V3**
(не «по проходящим тестам», а по коду: grep/diff + ссылка на конкретное место).

| № | Исправление | Исходная версия | Файл/функция | Доказательство присутствия в V3 | Тест | Статус |
|---|---|---|---|---|---|---|
| 1 | B2 v1: close accounting (per-order cursor, apply_close_execution) | samsung_merge_candidate_v1–v7 | execution.py: `apply_close_execution()` (строка 693+), `add_close_order()` | Функция присутствует; diff A0→B ⊂ diff A0→D; cursor-поля TrackedPosition: `close_orders`, `close_requested_at`, `close_applications` (execution.py:254–277) | test_b2_close_accounting.py (96-тестов батч) | **СОХРАНЁН** |
| 2 | B2 v2: идентичность cursor'а (обе ссылки close_order_id/close_order_request_id) | v2 | execution.py `apply_close_execution` (совместимые legacy-поля, ЭТАП 5Б) | Код присутствует (diff B→C/D не затрагивает эти ветки) | test_b2_close_accounting.py | **СОХРАНЁН** |
| 3 | B2 v3: timestamp identity (close_requested_at) | v3 | execution.py: `close_requested_at` field (строка 254) | Поле и обработка присутствуют | test_b2_v5_identity_and_timestamp.py | **СОХРАНЁН** |
| 4 | B2 v4: accounting consistency (recovery idempotency, autobind В4) | v4 | main.py: recovery autobind, `_uncertainty_resolved_by_reconcile` | Присутствует (main.py:4580+ recovery_autobind) | test_b2_v4_accounting_consistency.py | **СОХРАНЁН** |
| 5 | B2 v5: CLOSE TIMESTAMP + RECOVERY IDENTITY (CURSOR_IDENTITY_VERSION=2) | v5 | execution.py: `CURSOR_IDENTITY_VERSION = 2` (строка 359), `_cursor_identity_state()` | Присутствует; LEGACY/INVALID/UNKNOWN ветки (execution.py:1345–1398) | test_b2_v5_identity_and_timestamp.py | **СОХРАНЁН** |
| 6 | B2 v6: timestamp identity close reason (cursor format version, Defect B) | v6 | execution.py: `identity_version` в export (строка 688) | Присутствует | test_b2_v6_timestamp_identity_close_reason.py | **СОХРАНЁН** |
| 7 | B2 v7: cursor version + alt timestamp (ORDER_ID_TYPE_REQUEST) | v7 | order_ledger.py шапка (строка 16): «статуса должен идти по ORDER_ID_TYPE_REQUEST»; tinkoff_client.py `_order_id_type_member()` | Присутствует | test_b2_v7_cursor_version_and_alt_timestamp.py | **СОХРАНЁН** |
| 8 | B2: CSV recovery/update, cumulative P&L, дедуп CSV | B2-пакет | main.py CSV-recovery (`_csv_recovery_once`, needs_poll FIX-4) | Присутствует | test_b2_csv_recovery.py | **СОХРАНЁН** |
| 9 | B2: strict recovery identity / fail-closed / cursor identity validation | B2-пакет | execution.py:1345–1398 | Присутствует | test_b2_v5/v6 | **СОХРАНЁН** |
| 10 | BUY V1 FIX-1: повторный отчёт не затирает identity/метаданные (metadata-guard реестра) | Samsung_BUY_Accounting_Audit_V1 | order_ledger.py `append()`: блок «BUY ACCOUNTING AUDIT (v1, FIX-1)» (строки 235+) | **Присутствует и расширен V3** (валидность значений; см. FIXES.md V3-2) | test_order_ledger.py, test_corrective_audit_v3.py | **СОХРАНЁН** |
| 11 | BUY V1 FIX-2: commission persist в реестре (поле `commission` в RECORD_FIELDS, сигнатуры record_*) | BUY V1 | order_ledger.py: RECORD_FIELDS + `commission`, сигнатуры record_sent/record_status/record_uncertain | Присутствует | test_commission.py | **СОХРАНЁН** |
| 12 | BUY V1 FIX-3: `_extract_commission` — 0.0 достоверное значение | BUY V1 | execution.py: `_extract_commission` (строки 1270+) | Присутствует; V3 добавил только isfinite-защиту (0.0-семантика не изменена) | test_commission.py, test_corrective_audit_v2.py (SELL zero-commission 8 тестов) | **СОХРАНЁН** |
| 13 | BUY V1 FIX-4: needs_poll + entry_commission (позднее обогащение отражается в CSV) | BUY V1 | main.py: needs_poll (строка 2658) | Присутствует | test_buy_accounting_audit.py | **СОХРАНЁН** |
| 14 | BUY V2 FIX-1: атомарность `_enrich_buy_entry_metadata` (validate→stage→commit→checked save, откат при ошибке сохранения) | Samsung_BUY_Accounting_Corrective_Audit_V2 | main.py:3305–3412 | Присутствует байт-в-байт (V3 добавил только isfinite-валидацию в шаг 1; структура не изменена) | test_corrective_audit_v2.py (18 тестов A–F/C2/S) | **СОХРАНЁН** |
| 15 | Нулевая комиссия: семантика None/0.0 (None не подменяется нулём) | BUY V1 + V2 | main.py stage-блок (комментарий «0.0 — ДОСТОВЕРНОЕ реальное значение»), order_ledger `_valid_commission` (f >= 0) | Присутствует; V3 FIX-ZERO-PRICE явно кодифицирует: commission валидна при f>=0, цена при f>0 | test_corrective_audit_v2.py, test_corrective_audit_v3.py (тесты 11–12) | **СОХРАНЁН** |
| 16 | needs_poll zero commission handling (`or ""` на CSV-строках «0.00» безопасно) | V2 | main.py:2648–2664 | Присутствует; CSV-строки DictReader: «0.00» truthy — ноль не превращается в пустое значение | test_corrective_audit_v2.py (тесты 9–10 needs_poll) | **СОХРАНЁН** |

## Итог

* 16/16 принятых исправлений **подтверждены присутствием в production-коде кандидата V3**
  (местоположение указано; без опоры только на прохождение тестов).
* B2 v1–v7: `execution.py`/`order_ledger.py` V3-изменения затронули ТОЛЬКО `_extract_price`,
  `_extract_commission` (execution.py) и metadata-guard `append()` + 2 модульных валидатора
  (order_ledger.py). `apply_close_execution`, per-order cursor, cursor identity, close_applications,
  CSV recovery — **байт-в-байт без изменений** (см. `evidence/diffs/v3_candidate_vs_baseline_*.diff`).
* Отсутствующие откаты: не обнаружены.
