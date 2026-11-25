# CHANGED_FILES.md — samsung_merge_candidate_v4 (v2.3.7-stage1)

База: `samsung_merge_candidate_v3/` @ temp commit `af7cf3e`.
Полный дифф: FULL_DIFF.patch. Детальное обоснование: MERGE_REPORT.md.

---

## 1. main.py — изменён

| # | Место | Изменение | Обоснование |
|---|---|---|---|
| 1.1 | импорты (строка ~525) | `from execution import (... TrackedPosition ...)` | восстановление отсоединённых объектов recovery-задач из снимков |
| 1.2 | `_save_state()` | ключ `"pending_csv_recoveries"` из `monitor.export_state()` | персистентность архива (ТЗ №2: перезапуск) |
| 1.3 | `_load_state()` | передача `"pending_csv_recoveries"` в `monitor.import_state()` | восстановление архива после перезапуска; старый state.json без ключа → пустой список |
| 1.4 | writer CSV в `process_closing` | `"exit_time": pos.close_requested_at or datetime.now(UTC).isoformat()` (было: всегда `now()`) | авторитетное время закрытия для хронологического cumulative (ТЗ №1 п.1–2); фиксируется один раз, recovery не меняет |
| 1.5 | `process_closing`, после recovery-цикла v3 | НОВЫЙ проход по `monitor.pending_csv_recoveries`: восстановление снимка → `_recover_late_csv_metadata` → синхронизация снимка → завершение/удаление задачи | ТЗ №2: источник задач НЕ `positions[figi]`; лоты/состояние новой позиции не затрагиваются; удаление только при подтверждённых цене и комиссии |

НЕ изменено: стратегия/сигналы, BUY, SL/TP, риск-менеджмент, screener,
фильтры/пороги, отправка ордеров, `apply_close_execution`-вызовы,
recovery-цикл v3 по живым позициям (без изменений), `_finalize_position_closed`
(B3) — байт-идентично v3, схема CSV.

## 2. execution.py — изменён

| # | Место | Изменение | Обоснование |
|---|---|---|---|
| 2.1 | `ExecutionMonitor.__init__` | поле `pending_csv_recoveries: List[dict]` | архив незавершённых recovery-задач (ТЗ №2 п.3) |
| 2.2 | новый метод `archive_pending_csv_recovery(pos)` | снимок `pos.to_dict()` в архив при CLOSED+logged+trade_id+ссылка на свою close-заявку; дедуп по trade_id; runtime-only ключи (`_`) не экспортируются | сохранение идентичности старой сделки ПЕРЕД заменой позиции; без чтения CSV (без связности модулей); лишние задачи самоочищаются recovery-проходом |
| 2.3 | `register()` | хук `archive_pending_csv_recovery(self.positions.get(figi))` рядом с `_archive_closed_entry_order` | ТЗ №2 п.12: задача не удаляется, а сохраняется при замене |
| 2.4 | `register_recovery()` | тот же хук | та же замена через adoption-путь |
| 2.5 | `export_state()` | ключ `"pending_csv_recoveries"` (снимки без приватных ключей) | персистентность через state.json |
| 2.6 | `import_state()` | восстановление с валидацией; битые записи отбрасываются с журналом (fail-closed по записи); старый state.json без ключа → [] | миграция/совместимость/повреждённые данные (ТЗ №2) |

НЕ изменено: `TrackedPosition` (поля/`to_dict`/`from_dict`),
`apply_close_execution`, `resolve_closing`, `resolve_uncertain`,
`reconcile`, `_extract_price`/`_extract_commission`, per-order cursor,
B3-ветки — байт-идентичны v3.

## 3. logger.py — изменён

| # | Место | Изменение | Обоснование |
|---|---|---|---|
| 3.1 | `_parse_csv_ts(value)` — НОВАЯ функция | ISO-разбор ячейки; naive → UTC; None для пустого/мусора; БЕЗ подстановки текущего времени | детерминированный fallback (ТЗ №1 п.3, V4-D) |
| 3.2 | `_row_chrono_key(row, index)` — НОВАЯ функция | ключ сортировки: exit_time → timestamp_utc → order_send_time → signal_time → якорь `datetime(1,1,1,UTC)`; tie-breaker trade_id, затем индекс строки | авторитетное время закрытия + детерминизм (ТЗ №1 п.1–4) |
| 3.3 | `_recompute_cumulative(rows)` — переписана | хронологический порядок вместо порядка файла; строки не переставляются, net не меняется; PRICE_UNKNOWN-строки не трогаются | ТЗ №1 п.5–9 |
| 3.4 | `recompute_cumulative_chronological()` — НОВАЯ функция | канонизация всего журнала; перезапись только при реальном изменении; атомарная запись | самовосстановление журнала; идемпотентность |
| 3.5 | `log_trade()` | после успешного append — канонизация; append не отменяется при сбое канонизации | журнал каноничен после любой записи; байт-идемпотентность штатных сценариев (совместимость с тестами v1–v3) |
| 3.6 | шапка-документация | описание v2.3.7-stage1 | документирование нового поведения |

НЕ изменено: `update_trade_row` (тело), `find_trade_row`,
`_read_all_trade_rows`, `_read_tmp_rows`, `_write_all_trade_rows_atomic`,
`_ensure_files`, `log_event`, `get_cumulative_net_pnl`, TRADE_FIELDS
(схема CSV) — байт-идентичны v3.

## 4. Тестовые файлы

| Файл | Статус |
|---|---|
| test_b2_close_accounting.py | БЕЗ ИЗМЕНЕНИЙ (байт-идентичен v1) — 20/20 PASS |
| test_b2_terminal_metadata_recovery.py | БЕЗ ИЗМЕНЕНИЙ (байт-идентичен v2) — 8/8 PASS |
| test_b2_csv_recovery.py | БЕЗ ИЗМЕНЕНИЙ (байт-идентичен v3) — 14/14 PASS |
| test_b2_v4_accounting_consistency.py | НОВЫЙ — 9 тестов V4-A..V4-I, 9/9 PASS; негативная валидация на v3-коде: 9/9 FAIL |

## 5. Статистика диффа

| Файл | Добавлено | Удалено | Изменённые функции |
|---|---|---|---|
| main.py | ~100 строк | 4 | импорт, `_save_state`, `_load_state`, writer (exit_time), `process_closing` (новый проход) |
| execution.py | ~129 | 1 | `__init__`, новый метод, `register`, `register_recovery`, `export_state`, `import_state` |
| logger.py | ~180 | 25 | шапка, `log_trade`, новая `_recompute_cumulative` + 2 новые функции |
