# CHANGED_FILES.md — samsung_merge_candidate_v5 (v2.3.8-stage1)

База: **samsung_merge_candidate_v4** (v2.3.7-stage1), commit `a4c2491`
(ветка `temp-merge-candidate-v4` репозитория cristal-hub/temp).
Все исправления v1–v4 сохранены без изменений; Samsung-репозиторий не
изменён (origin/main @ `051b10f`, READ-ONLY).

## Изменённые файлы

| Файл | v4 (base) SHA256 | v5 SHA256 | Статус |
|---|---|---|---|
| `main.py` | `d50e66e7fcf95d0963b5d75b6039fe37f0b1d5dcba76fd95b1cd9a6d5ae535a0` | `00d7fdfc813f4a98672790314e2a3e530e34471a73a40836220a93c7a471fe07` | ИЗМЕНЁН (Defect A + Defect B) |
| `execution.py` | `7e347f0c6d162aa2add55f2d0ec68af0358c3125bf5c86d0d200a54ce4a1d7eb` | `2b4ca67f61e816457f66f4d75a3b25dcecc2672815637be0febc300bc219b7fd` | ИЗМЕНЁН (Defect B) |
| `logger.py` | `df22ed916cb2eda10473cb78c2f93846d0be00c8a7ad5913a6bab8d9ee8ad4c5` | `df22ed916cb2eda10473cb78c2f93846d0be00c8a7ad5913a6bab8d9ee8ad4c5` | БЕЗ ИЗМЕНЕНИЙ |
| `test_b2_close_accounting.py` | `9fa798bda539bbb1d8386f9836d64d3e9cf892c630a676257eced8078a347bc3` | `9fa798bda539bbb1d8386f9836d64d3e9cf892c630a676257eced8078a347bc3` | БЕЗ ИЗМЕНЕНИЙ |
| `test_b2_csv_recovery.py` | `8de760c885dc147c660767fe59b2ba0f7058173db78087059ae6eaa8e29a6e77` | `8de760c885dc147c660767fe59b2ba0f7058173db78087059ae6eaa8e29a6e77` | БЕЗ ИЗМЕНЕНИЙ |
| `test_b2_terminal_metadata_recovery.py` | `2f4ab482030e37808fcee4eca217f59b75dd27d084b542e8560fb717409be0f2` | `2f4ab482030e37808fcee4eca217f59b75dd27d084b542e8560fb717409be0f2` | БЕЗ ИЗМЕНЕНИЙ |
| `test_b2_v4_accounting_consistency.py` | `6b75e5d501c6a653ca769ee17cd3cd99b33de49cb70f800737966ab0a387a93e` | `6b75e5d501c6a653ca769ee17cd3cd99b33de49cb70f800737966ab0a387a93e` | БЕЗ ИЗМЕНЕНИЙ |
| `test_b2_v5_identity_and_timestamp.py` | — | `1c793deb40920da3232f473ebaf0b447cdd00ac00befa5f236014a523816f3fc` | НОВЫЙ (тесты V5-A..J) |

## Состав изменений

### main.py (Defect A + Defect B)

1. **Defect A — единое время запроса закрытия (`close_position`)**:
   - `close_requested_at = datetime.now(timezone.utc).isoformat()` создаётся
     ОДИН раз ДО `post_market_order()` (рядом с созданием клиентского UUID);
   - то же значение передаётся в `monitor.add_close_order(...)` →
     `close_orders[request_id]["requested_at"]`;
   - после успешной регистрации intent + per-order cursor'а
     `pos.close_requested_at = close_requested_at` — ДО сетевого вызова;
   - при `result.state is None` timestamp сохранён (позиция UNCERTAIN,
     close_order_request_id и close_requested_at уже в позиции);
   - на успешной ветке значение НЕ перезаписывается временем получения
     ответа брокера (удалён второй `datetime.now()` v4);
   - новый helper `_close_request_ts(pos)`: детерминированная цепочка
     `pos.close_requested_at` → `requested_at` СВОЕГО cursor'а
     (`close_orders[close_order_request_id/close_order_id]["requested_at"]`,
     для старых state.json) → None (вызывающий код применяет свою политику);
   - запись CSV (`process_closing`): `timestamp_utc` и `exit_time`
     берутся из `_close_request_ts(pos)`; для закрытий без своей заявки
     (B3) и полностью легаси-позиций — момент записи строки (как в v4,
     явно документировано).

2. **Defect B — fail-closed проверка идентичности recovery-задач**:
   - `_load_state`: после `monitor.import_state` по каждой задаче с
     маркером `"conflict"` пишется событие `CSV_RECOVERY_TASK_CONFLICT`
     (stage=import_state);
   - `process_closing`, цикл `pending_csv_recoveries`: ПЕРЕД обработкой
     каждой задачи — `ExecutionMonitor.validate_recovery_identity(rec)`;
     учитывается КАК свежая проверка, ТАК и ранее установленный маркер
     (заблокированная задача не «разблокируется» повторной проверкой);
     конфликт → задача не опрашивается, CSV не изменяется, задача не
     удаляется и не завершается, событие `CSV_RECOVERY_TASK_CONFLICT`
     (первичное обнаружение/смена причины);
     снимок, невосстановимый в памяти, больше НЕ удаляется — задача
     остаётся с маркером `snapshot_unrestorable` (fail-closed
     сохранение улики; событие `CSV_RECOVERY_TASK_CONFLICT`, прежнее
     `CSV_RECOVERY_TASK_DROPPED` удаление устранено);
   - `_recover_late_csv_metadata`, шаг 1а: проверка идентичности СТРОКИ
     перед обновлением — `row.figi == pos.figi` и `row.order_id`
     принадлежит close-заявке снимка; противоречие → обновление
     ЗАПРЕЩЕНО, события `CSV_LATE_METADATA_CONFLICT` с причинами
     `row_figi_mismatch` / `row_order_id_mismatch`.

### execution.py (Defect B)

1. `import json` (канонизация дубликатов).
2. `ExecutionMonitor._recovery_canonical_body(rec)` — детерминированная
   каноническая форма записи для сравнения дубликатов (без летучего
   маркера `"conflict"`).
3. `ExecutionMonitor.validate_recovery_identity(rec)` — возвращает None
   или причину конфликта: `not_dict`, `no_snapshot`,
   `snapshot_unrestorable`, `no_trade_id`, `trade_id_mismatch`,
   `no_figi`, `figi_mismatch`, `no_close_order_ref`,
   `cursor_trade_id_mismatch`, `cursor_figi_mismatch`,
   `cursor_side_mismatch`. Проверяются: rec.trade_id == snapshot.trade_id,
   rec.figi == snapshot.figi, наличие стабильного trade_id/FIGI, наличие
   СВОЕЙ close-заявки, привязка per-order cursor'а (trade_id/figi/side).
   Отсутствующий cursor (легаси-снимок) НЕ конфликт (штатный
   no_cursor-путь recovery).
4. `ExecutionMonitor._import_pending_recoveries(raw_pending)` — импорт
   задач: структурно нечитаемые записи (не dict) отбрасываются с журналом
   (сохранять нечего); все остальные СОХРАНЯЮТСЯ, запись с нарушенной
   идентичностью получает персистентный маркер `"conflict"` (причина
   экспортируется/импортируется обратно в state.json); дубликаты
   trade_id: ПОЛНЫЕ дубликаты — детерминированный дедуп (первая),
   КОНФЛИКТУЮЩИЕ (разные снимки/close-ID) — ОБЕ остаются с маркером
   `duplicate_trade_id_conflicting`, произвольный выбор запрещён.
5. `import_state` — делегирует импорт pending-задач в
   `_import_pending_recoveries`; комментарий шапки обновлён.

### logger.py

Без изменений (хронология cumulative V4 не затронута: `_row_chrono_key`
по-прежнему читает `exit_time` → `timestamp_utc` → …; v5 меняет только
то, КАКОЕ значение main.py записывает в эти столбцы).

## Что НЕ менялось

- Стратегия, сигналы, BUY, SL/TP, RiskManager, screener, фильтры, пороги,
  торговая конфигурация, алгоритмы заявок — без изменений.
- B3 (внешние закрытия) — без изменений.
- Механизмы v1–v4: per-order cursor, ledger, идемпотентность,
  fail-closed ветки, хронологический cumulative, персистентный архив
  recovery-задач, атомарная запись CSV — сохранены; 51 прежний B2-тест
  проходит без правок.

STRATEGY LOGIC: UNCHANGED
RESEARCH ONLY
NO THRESHOLD IS OPTIMIZED
NO FILTER IS INSTALLED
NO LIVE ORDERS
OOS SEALED / H4 EXECUTION NOT AUTHORIZED
