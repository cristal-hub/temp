# TRANSFER TABLE — перенос исправлений B2 v1–v7 в Samsung

Метод (ТЗ п.6, для каждого исправления): 1) найдена исходная Samsung-функция;
2) найдено исправление в B2-кандидате; 3) сопоставлены различия и зависимости;
4) перенесена только необходимая логика; 5) Samsung-specific поведение
сохранено; 6) совместимость вызовов/интерфейсов проверена (полный pytest,
smoke-импорт всех модулей, AST-сверка).

База: Samsung `051b10f095d45c053492ca333449a9a9f518f33f` (main @ origin/main).

| B2 fix | Samsung baseline (состояние до интеграции) | Действие | Обоснование | Тест |
|---|---|---|---|---|
| **v1** — B2 close accounting (единая точка apply_close_execution) | Механизм per-order cursor уже есть (`TrackedPosition.close_orders/close_applications`, `add_close_order`, `apply_close_execution` — используются `resolve_closing`), НО В2-ветка `reconcile` → `_try_resolve_absent_position()` закрывала учёт напрямую `_finalize_position_closed()`, в обход per-order механизма: позиция CLOSED при несогласованном cursor/реестре; `sold=min(executed, quantity)` затирал запрошенные лоты; частичное исполнение не отражалось в CSV | **ПЕРЕНЕСТИ** (main.py: ~180 строк в `_try_resolve_absent_position` + сигнатура +`monitor`; docstring `_finalize_position_closed`) | Дефект учёта: закрытие В2 в обход единой точки ломает cursor/close_applications/реестр; частичное исполнение фиктивно помечалось полным | `test_b2_close_accounting.py` — 20 passed |
| **v2** — повторный терминальный отчёт: восстановление поздних цены/комиссии | `apply_close_execution()`: повтор при терминальном cursor возвращал False ДО какого-либо обновления — фактически предоставленные брокером цена/комиссия терялись | **ПЕРЕНЕСТИ** (execution.py: блок безопасного обогащения в `apply_close_execution` + модульная `_report_value_conflict`; +`import json` не относится к v2 — см. v5) | Late metadata enrichment без повторного списания лотов; противоречивый повтор — fail-closed | `test_b2_terminal_metadata_recovery.py` — 8 passed |
| **v3** — late metadata CSV recovery | CLOSED+logged позиция не имела НИ ОДНОГО пути опроса брокера и НИ ОДНОГО механизма обновления записанной CSV-строки (`log_trade` append-only): CSV расходился с оперативным учётом | **ПЕРЕНЕСТИ** (main.py: `_recover_late_csv_metadata`, `_build_late_recovery_updates`, `_csv_recovery_once`, `_remove_price_unknown_marker`, константа `_CSV_PRICE_UNKNOWN_MARKER`, recovery-проход в `process_closing`; logger.py: `find_trade_row`, `update_trade_row` с атомарной записью, `+import tempfile`) | Поздние фактические цена/комиссия должны попадать в СУЩЕСТВУЮЩУЮ строку (без дубликатов), с пересчётом финансов | `test_b2_csv_recovery.py` — 14 passed |
| **v4** — chronological cumulative P&L + persistent recovery | `get_cumulative_net_pnl` считал cumulative в физическом порядке строк CSV; recovery-задача умирала при замене объекта позиции тем же FIGI / перезапуске (не персистентна) | **ПЕРЕНЕСТИ** (logger.py: `_recompute_cumulative`, `recompute_cumulative_chronological`, `_row_chrono_key`, `_parse_csv_ts`, `_read_all_trade_rows`, `_read_tmp_rows`, `_write_all_trade_rows_atomic`, канонизация в `log_trade`, `_CHRONO_UNKNOWN_TS`; main.py: экспорт/импорт `pending_csv_recoveries` в `_save_state`/`_load_state`; execution.py: `pending_csv_recoveries`, `archive_pending_csv_recovery`, вызовы в `register`/`register_recovery`, export/import_state) | Порядок строк = порядок записи, не хронология закрытий; задачи восстановления обязаны переживать перезапуск и замену позиции | `test_b2_v4_accounting_consistency.py` — 9 passed |
| **v5** — close timestamp (до сетевого вызова) + валидация идентичности recovery-задач | `close_position()`: `close_requested_at` ставился ТОЛЬКО после `post_market_order()` при `result.state != None` — при потере ответа время терялось; `import_state` не сверял внешнюю запись задачи со снимком (rec.trade_id vs snapshot.trade_id) | **ПЕРЕНЕСТИ** (main.py: единый `close_requested_at` до отправки в `close_position`, `_close_request_ts`, `timestamp_utc`/`exit_time` CSV через `_close_request_ts`; execution.py: `validate_recovery_identity`, `_import_pending_recoveries`, conflict-маркеры в `import_state`, CSV_RECOVERY_TASK_CONFLICT в `_load_state`) | Время запроса SELL — неизменяемый факт; конфликт идентичности задачи — fail-closed (без опроса, без CSV, без удаления) | `test_b2_v5_identity_and_timestamp.py` — 10 passed |
| **v6** — timestamp integrity (без подмен) + строгая идентичность cursor'а + пустой close_reason | В2-reconcile писал в `close_requested_at` значение `rec.updated_at_utc`/`rec.timestamp_utc`/`datetime.now()` — подмена исторического времени; `validate_recovery_identity` пропускал ПУСТЫЕ обязательные поля cursor'а; `reason_text[len("close:"):].split()[0]` падал IndexError при пустой причине | **ПЕРЕНЕСТИ** (main.py: `_valid_saved_ts`, `_restore_close_requested_at` (приоритеты 1–4), безопасный разбор `close_reason`; execution.py: `CURSOR_IDENTITY_VERSION`, маркер `identity_version` в `add_close_order`, `_cursor_identity_conflict`, `cursor_validation_mode`, строгая проверка нового формата) | Чужие/производные метки времени не подменяют SELL-время; пустое обязательное поле нового cursor — конфликт (fail-closed); пустая причина не роняет reconcile | `test_b2_v6_timestamp_identity_close_reason.py` — 16 passed |
| **v7** — трихотомия identity_version + подтверждение идентичности альтернативного cursor'а | `_cursor_is_new_format()` в v6 возвращала False и для legacy, и для некорректного маркера — некорректная версия трактовалась как legacy (ослабление); приоритет 3 `_restore_close_requested_at` брал `requested_at` найденного по ключу cursor'а БЕЗ проверки идентичности (чужой timestamp мог попасть в другую сделку, включая тот же FIGI) | **ПЕРЕНЕСТИ** (execution.py: `_cursor_identity_state` (legacy/new/invalid), `_cursor_is_new_format`, `_cursor_identity_conflict_checked`, режим `invalid_version` в `cursor_validation_mode`/`archive_pending_csv_recovery`; main.py: `_alt_cursor_identity_conflict`, приоритет 3 только при подтверждённой идентичности) | INVALID ≠ LEGACY: fail-closed без broker polling/CSV/удаления; timestamp альтернативного cursor'а — только после положительного подтверждения trade_id/FIGI/side/order_id | `test_b2_v7_cursor_version_and_alt_timestamp.py` — 19 passed |

## Уже имелось в Samsung (не переносилось повторно)

* per-order cursor и `close_applications` (поля `TrackedPosition`, `add_close_order`,
  `apply_close_execution`, `sync_recovery_quantity`);
* fail-closed протоколы `resolve_closing`/`resolve_uncertain` (legacy
  `close_applied_lots` без per-order истории — UNCERTAIN);
* guard «воскрешения» позиции (`closed_entry_order_ids`, `register_executed_buy`);
* ЭТАП 5Б: `record_intent` до отправки, клиентский UUID как ключ реестра,
  явные типы идентификаторов при опросе;
* извлечение цены/комиссии отчёта (`_extract_price`, `_extract_commission`);
* uncertainty resolution by reconcile, блокировка новых входов при
  `uncertain_state`;
* B3 (внешнее закрытие без своей SELL) — сохранено без изменений.

## Не потребовались

* изменения `strategy.py`, `config.py`, `risk_manager.py`, `screener.py`,
  `order_ledger.py`, `tinkoff_client.py`, `telegram_bot.py`, `tests/` —
  не потребовались ни одному исправлению v1–v7 (побайтово идентичны baseline);
* замена `logger.py` целиком — не потребовалась: изменён/добавлен только
  CSV-recovery API, остальные функции logger идентичны Samsung;
* какие-либо изменения стратегии, сигналов, фильтров, порогов, BUY-цепочки,
  SL/TP, риск-менеджмента — исправления B2 не касаются этих областей.

## Адаптации тестов к Samsung

НЕ ТРЕБУЮТСЯ: все 96 B2 тест-итемов запускаются на интегрированном
Samsung-коде в исходном виде (файлы побайтово взяты из
`temp/samsung_merge_candidate_v7`, SHA256 в CHANGED_FILES.md); проверяемые
инварианты не ослаблялись и не переписывались.
