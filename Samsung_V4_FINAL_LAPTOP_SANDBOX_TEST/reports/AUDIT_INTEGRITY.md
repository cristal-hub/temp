# AUDIT_INTEGRITY.md — полный аудит интеграционной целостности V4 (ТЗ §4)

**Мандаты:** `STRATEGY LOGIC: UNCHANGED` · `RESEARCH ONLY` · `NO THRESHOLD IS OPTIMIZED` ·
`NO FILTER IS INSTALLED` · `NO LIVE ORDERS`

Проверяемая цепочка: **Broker report → execution parsing → OrderLedger → local
position/state → CSV → P&L → recovery after restart.**

Формат: группа → ключевые функции/файлы → существующее покрытие → добавленное в V4 →
фактический результат → остаточный риск. Прогоны: BASELINE V3 и V4, идентичные команды
(`reports/TEST_RESULTS.md`).

| № | Группа | Функции/файлы | Существующие тесты | Добавлено в V4 | Результат | Остаточный риск |
|---|---|---|---|---|---|---|
| 1 | BUY execution accounting | `main.register_executed_buy`, `ExecutionMonitor._extract_price`, `OrderLedger.record_sent/record_status` | test_buy_accounting_audit (23), test_buy_registration_fix2*, test_commission | — | 41/41 (обе стороны) | SDK-контракт (K-NV1) |
| 2 | SELL execution accounting | `main.close_position`, `execution.apply_close_execution` | B2 test_01–test_12, Stage3 | — | 96+48/96+48 | — |
| 3 | Partial BUY | cumulative `executed_lots`, `_extract_price` | test_p0_batch2 (partial cancel recovery), B2 | — | P0 70/70 | — |
| 4 | Partial SELL | `apply_close_execution`, cursor | test_v233_partial_sell_reopen_defect, B2 test_05/06/07 | — | 48/48, 96/96 | — |
| 5 | Cancelled order with partial execution | `main.register_executed_buy` (CANCELLED+executed) | test_p0_batch2::…partial_cancel…, V3-тесты | — | P0 70/70; V3 17/17 | — |
| 6 | Late execution after terminal status | `_build_late_recovery_updates`, `_recover_late_csv_metadata`, ledger enrichment | test_p0_batch2 (late_lots), test_b2_terminal_metadata_recovery, V3 | — | P0 70/70; B2 96/96 | частотность на живом API (K-NV3) |
| 7 | Duplicate broker reports | ledger guard повторного отчёта (FIX-1/V3-2), B2 идемпотентность | test_03_repeated_identical…, test_12_repeated_reconciliation…, V3 №8 | — | 96/96; 17/17 | — |
| 8 | Repeated reconciliation | `main.reconcile` (каждый цикл), двойное подтверждение В3 | test_reconcile_* (7), test_stage1_packet_v | — | green (в FULL 789) | — |
| 9 | Missing execution price | `_extract_price`→None, ledger absence-семантика | V3-тесты №1/2, **V4 first_append №10** | 17 first-append тестов | 17/17 | — |
| 10 | Missing commission | `commission=None` ≠ 0.0 | B2 test_11a/11b, **V4 №6–8** | — | green | — |
| 11 | Zero commission | FIX-3 семантика, `_valid_commission` | test_commission, V3 №11–12 | **V4 №9 + zero-commission-ветки №13/15** | green | — |
| 12 | Non-finite numeric values | `math.isfinite` (V3-3, V4-1) | V3 №13–17 | **V4 №3–5, 7–8 (NaN/±Inf, цена и комиссия)** | 17/17 | — |
| 13 | Contradictory execution metadata | `_confirmed_value_conflicts`, `_report_value_conflicts`, ledger conflict-guard | B2 test_04, V3 №5/11, test_fail_closed | — | green | — |
| 14 | Ledger persistence | `OrderLedger.load/_append_raw` (fsync) | test_order_ledger, test_persistence | **V4 №14 (roundtrip)** | green | K-1 (file lock) |
| 15 | State persistence | `_save_state_checked` (FIX-2/D6), atomic tmp+replace | test_main::save_load_roundtrip, test_buy_registration_fix2 (FIX2) | — | green | — |
| 16 | CSV persistence | `logger.log_trade/_ensure_files`, atomic rewrite | test_fail_closed, test_commission (CSV-строки) | — | green | — |
| 17 | CSV row recovery (update, не дублирование) | `_recover_late_csv_metadata`, `_csv_recovery_once` | test_b2_csv_recovery (a–h), B2 V4/V5 | — | 96/96 | — |
| 18 | Cumulative P&L (chronological) | `process_closing`, `_finalize_position_closed`, logger | test_g_cumulative_pnl…, test_process_closing_cumulative_net_pnl, sellzc_7 | — | green | — |
| 19 | Restart recovery | `OrderLedger.load`, `_load_state`, `startup_recovery` | test_persistence (restart), test_v4_g_recovery_task_survives_restart, test_v5_c/j | **V4 №15 (behavior_after_restart)** | green | живой SDK (K-NV1) |
| 20 | Recovery with incomplete broker snapshot | `reconcile` (None-снимок не подтверждение), `_try_resolve_absent_position` | none_snapshot-тесты (2), test_fail_closed::reconcile_error… | — | green | — |
| 21 | Recovery with incomplete local state | `_load_state` (отсутствует/повреждён → False, fail-closed) | test_load_state_missing/corrupted, corrupted-ledger тесты | — | green | — |
| 22 | Duplicate position prevention | `trading_cycle` (позиция у брокера/в monitor), `register_executed_buy` guards | test_buy_registration_fix2, FIX2_snapshot | **4 теста: trading_cycle skip ×2, sell_block ×2 (см. 24)** | 8/8 | — |
| 23 | UNCERTAIN state transitions | `record_uncertain`, resolve через reconcile/сверку | test_process_closing_resolves_uncertain, test_reconcile_*, V3-тесты | — | green | — |
| 24 | Stale close order protection | `_sell_block_reason`, close_requested_at, cursor identity | test_v5/v6/v7, second_sell/sell_block-тесты | **test_v4_integration_integrity: 4 теста _sell_block_reason (вкл. все 7 терминальных статусов после OOS-4)** | 8/8 | — |
| 25 | Idempotency after restart | ledger reload+enrich, pending CSV recovery persist | test_12, test_f_late_data_after_restart…, **V4 №14/15** | — | green | — |

**Итог:** все 25 групп покрыты; в V4 добавлены 43 теста (17 P1-контракт реестра,
18 безопасность сборки, 8 прямых интеграционных групп 22/24). Прямо не покрытых по
имени групп не осталось; остаточные риски — только вне-офлайн пункты (K-NV1 SDK,
K-NV2 Windows-запуск, K-NV3 живой брокер) — см. `KNOWN_ISSUES.md` §2.

## §5 (ТЗ V4). Отчёт изоляции тестов — какие тесты раньше создавали файлы в корне

Пофайловая проверка на копии BASELINE V3 (каждый root-файл запускался отдельно, фиксировались
файлы, оставшиеся в корне кандидата):

| Тест-файл V3 | Создавал в корне | Изоляция в V4 |
|---|---|---|
| test_fail_closed.py (8 тестов) | research_events.jsonl, research_trades.csv | autouse-фикстура conftest (tmp_path) |
| test_main.py (11) | research_events.jsonl, research_trades.csv | —«— |
| test_main_helpers.py (18) | research_events.jsonl, research_trades.csv | —«— |
| test_safety.py (7) | research_events.jsonl, research_trades.csv | —«— |
| test_telegram_handlers.py (10) | research_events.jsonl, research_trades.csv | —«— |
| test_trading_flag.py (7) | research_events.jsonl, research_trades.csv (+trading.flag на пути start/stop) | —«— |

* Способ: `_isolate_default_runtime_paths` (autouse) — `main.STATE_FILE/STATE_FILE_TMP/
  LEDGER_FILE/TRADING_FLAG`, `logger.EVENTS_FILE/TRADES_FILE` → per-test tmp_path.
* Доказательство: полный прогон V4 (root+tests/, 789 тестов) оставляет корень кандидата
  пустым; тот же прогон BASELINE V3 создавал research_events.jsonl/research_trades.csv.
* Гарантии ТЗ §5: исходный Samsung не изменяется (тесты работают в копии/временных
  каталогах); runtime-каталоги кандидата не загрязняются; мусор не остаётся; порядок
  запуска не влияет (изоляция per-test); зависимости от ранее созданных файлов нет.
