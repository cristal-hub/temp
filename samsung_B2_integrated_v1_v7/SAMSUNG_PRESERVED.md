# SAMSUNG_PRESERVED — сохранённые Samsung-specific функции и проверки

Верификация сохранности Samsung-кода при интеграции B2 v1–v7
(база Samsung `051b10f095d45c053492ca333449a9a9f518f33f`).

## 1. Функции/классы: AST-сверка (исходник → кандидат)

Ни одна функция/класс Samsung не удалена и не переименована.

### main.py — 39 элементов Samsung
* Идентичны побайтово (32): `_status_name`, `_age_in_cycles`,
  `_uncertainty_resolved_by_reconcile`, `_poll_ledger_order_state`,
  `_cancel_confirmed_request_id`, `_sell_block_reason`,
  `_link_broker_order_to_position`, `is_trading_enabled`, `start_trading`,
  `stop_trading`, `get_status`, `notify`, `_stop_telegram_bot`,
  `_try_create_telegram_bot`, `_telegram_watchdog`,
  `_trade_id_already_logged`, `_timestamp_for_log`,
  `_log_strategy_diagnostic`, `_parse_iso_ts`, `_atr_from_df`,
  `_fetch_extremes_and_atrs`, `_save_state_checked`, `_ledger_last_buy_time`,
  `_match_own_close_sell`, `_build_candles_df`, `register_executed_buy`,
  `poll_open_orders`, `_try_bind_recovery_entry`, `promote_recovery_positions`,
  `startup_recovery`, `trading_cycle`, `main`.
* Изменены ТОЛЬКО B2-логикой (7): `_save_state` (+`pending_csv_recoveries`),
  `_load_state` (+импорт задач + события конфликтов),
  `_finalize_position_closed` (только docstring: В2 больше не использует
  функцию — тело без изменений; В3 сохранён),
  `_try_resolve_absent_position` (В2-ветка: apply_close_execution, комиссия,
  частичное исполнение, timestamp; В3-ветка без изменений),
  `reconcile` (передача `monitor` в resolver; текст диагностической строки),
  `close_position` (единый `close_requested_at` до отправки),
  `process_closing` (`_close_request_ts` для CSV, PRICE_UNKNOWN-маркер,
  recovery-проходы CLOSED+logged и pending-задач).
* Добавлены только B2-функции (11): `_valid_saved_ts`,
  `_alt_cursor_identity_conflict`, `_restore_close_requested_at`,
  `_canonical_report_status`, `_confirmed_value_conflicts`,
  `_remove_price_unknown_marker`, `_build_late_recovery_updates`,
  `_csv_recovery_once`, `_recover_late_csv_metadata`, `_close_request_ts`,
  константа `_CSV_PRICE_UNKNOWN_MARKER`.
* Импорт из execution РАСШИРЕН (superset): `+TrackedPosition`; прежние имена
  (`ExecutionMonitor, PositionState, ACTIVE_STATES`) сохранены.

### execution.py — 31 элемент Samsung
* Идентичны побайтово (23): `PositionState` (все значения enum без изменений),
  `TrackedPosition` (ВСЕ 34 поля dataclass без изменений),
  `TrackedPosition.to_dict/from_dict`,
  `ExecutionMonitor._archive_closed_entry_order`, `_valid_position`,
  `promote_recovery`, `sync_recovery_quantity`, `record_recovery_entry_lots`,
  `apply_late_entry_lots`, `get_position`, `has_active_position`,
  `_be_buffer`, `_risk_per_share`, `update_extremes`, `_update_sl`,
  `_classify_sl_exit`, `check_all`, `resolve_closing`, `resolve_uncertain`,
  `_extract_price`, `_extract_commission`, `active_count`.
* Изменены ТОЛЬКО B2-логикой (8): `ExecutionMonitor.__init__`
  (+`pending_csv_recoveries`), `register`/`register_recovery`
  (+вызов `archive_pending_csv_recovery` перед заменой позиции),
  `add_close_order` (+маркер `identity_version`; вся прежняя логика
  сохранена), `apply_close_execution` (ветка повторного терминального
  отчёта: безопасное обогащение; первичное применение — без изменений),
  `export_state`/`import_state` (+ персистентность/валидация
  `pending_csv_recoveries`), тело класса (+комментарии-версии).
* Добавлены только B2-методы (10): `archive_pending_csv_recovery`,
  `_recovery_canonical_body`, `_cursor_identity_state`, `_cursor_is_new_format`,
  `_cursor_identity_conflict`, `cursor_validation_mode`,
  `_cursor_identity_conflict_checked`, `validate_recovery_identity`,
  `_import_pending_recoveries`; константа класса `CURSOR_IDENTITY_VERSION`.

### logger.py — 6 элементов Samsung
* Идентичны побайтово (5): `_file_is_empty_or_header_only`,
  `_csv_header_matches`, `_ensure_files`, `log_event`,
  `get_cumulative_net_pnl`; константы/схема CSV (`TRADE_FIELDS`) — без
  изменений.
* Изменён (1): `log_trade` — добавлена канонизация cumulative ПОСЛЕ
  успешного append (append и формат строки — как в Samsung; сбой
  канонизации не отменяет успешную запись).
* Добавлены только B2-функции (9): `_read_all_trade_rows`, `find_trade_row`,
  `_parse_csv_ts`, `_row_chrono_key`, `_recompute_cumulative`,
  `recompute_cumulative_chronological`, `_read_tmp_rows`,
  `_write_all_trade_rows_atomic`, `update_trade_row`; `+import tempfile`.

## 2. Модули вне трёх изменённых — побайтово идентичны Samsung

`config.py`, `strategy.py`, `risk_manager.py`, `order_ledger.py`,
`tinkoff_client.py`, `screener.py`, `telegram_bot.py`, `pay_in.py`,
`preflight_check.py`, `close_all_positions.py`, `tools/`, `tests/` и все
прочие файлы репозитория — SHA256 совпадают с `051b10f` (см. SHA256SUMS.txt).
Инвентаризация diff-ом всего дерева: различаются ТОЛЬКО `main.py`,
`execution.py`, `logger.py` (+7 добавленных B2 тест-файлов).

## 3. Публичные интерфейсы и связи между модулями

* Smoke-импорт всех модулей кандидата (config, logger, execution,
  order_ledger, risk_manager, screener, strategy, tinkoff_client, main) —
  успешен; API-сверка: все методы, вызываемые main из ExecutionMonitor и
  logger, присутствуют; ни один интерфейс не переименован и не удалён.
* Состояния и переходы позиций (OPEN → CLOSING → UNCERTAIN → CLOSED …) —
  без изменений (enum `PositionState` идентичен).
* Формат `state.json` — обратная совместимость: старый state.json без
  `pending_csv_recoveries` восстанавливается с пустым списком; новые ключи
  добавляются, прежние не переименовываются.
* Конфигурация и параметры запуска (`config.py`) — не изменялись.

## 4. Samsung-specific сценарии, затронутые изменёнными функциями

Проверены полным pytest Samsung на интегрированном коде (набор Samsung-тестов
не менялся): `test_main.py`, `test_main_helpers.py`, `test_fail_closed.py`,
`test_persistence.py`, `test_p0_defect_fixes.py`, `test_p0_sell_id_fixes.py`,
`test_p0_batch2_late_execution.py`, `test_manual_close_integration.py`,
`test_v232_close_defects.py`, `test_v233_partial_sell_reopen_defect.py`,
`test_execution.py` (в tests/), `test_stage1_*`, `test_trading_flag.py` и др.
Результат: FAILED/ERROR-набор по ТОЧНЫМ именам идентичен baseline Samsung
(74 FAILED + 1 pre-existing collection error) — ни один Samsung-сценарий не
деградировал (подробности: TEST_RESULTS.txt, appendix-файлы).

## 5. Доказательство минимальности

`FULL_DIFF.patch` (Samsung → кандидат) содержит ровно 10 секций:
3 изменённых производственных файла + 7 новых тест-файлов. Каждая строка
патча выверена вручную: только B2-логика, диагностические события и
комментарии-версии; ни одного изменения стратегии/сигналов/фильтров/порогов/
BUY/SL/TP/рисков/screener; wholesale replacement отсутствует (патч = 9338
строк на файлы размером 4327+1083+159 строк Samsung).
