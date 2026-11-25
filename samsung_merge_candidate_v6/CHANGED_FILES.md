# CHANGED_FILES.md — samsung_merge_candidate_v6 (v2.3.9-stage1)

B2 V6 — FINAL TIMESTAMP INTEGRITY + STRICT RECOVERY IDENTITY + EMPTY CLOSE REASON.

База: `samsung_merge_candidate_v5` (код v5 = дерево `env_final_v5`,
файлы main.py/execution.py/logger.py побайтово идентичны кандидатной папке v5).
Сама папка `samsung_merge_candidate_v5` НЕ изменялась.

Исходное состояние базы зафиксировано:
* git: `cristal-hub/temp` @ commit `faee75d53176ce7d1dad5f648950811d3cbe0b69`
  (2026-11-24 18:04:59 +0300, "Add files via upload") — папка
  `samsung_merge_candidate_v5/` присутствует в дереве;
* blob-хэши git всех 8 исходников/тестов v5 совпадают с локальной копией
  (проверено `git ls-tree temp/main samsung_merge_candidate_v5/`).

## Сводка изменений

| Файл | Статус | Назначение | Дефект | Тесты |
|---|---|---|---|---|
| main.py | ИЗМЕНЁН | Восстановление первоначального времени запроса SELL при B2 reconcile (`_restore_close_requested_at` + `_valid_saved_ts`); безопасный разбор пустого `close_reason` в `_try_resolve_absent_position()` | A, C | V6-A, V6-B, V6-C, V6-D(a), V6-M, V6-N, V6-O, V6-P |
| execution.py | ИЗМЕНЁН | Строгая проверка идентичности per-order cursor'а: маркер `identity_version` в `add_close_order()`, `_cursor_is_new_format`, `_cursor_identity_conflict`, `cursor_validation_mode`, `cursor_validation` в recovery-задачах; вторая ссылка close-заявки; `cursor_validation` исключён из тела дедупликации | B | V6-D(b), V6-E, V6-F, V6-G, V6-H, V6-I, V6-J, V6-K, V6-L |
| logger.py | БЕЗ ИЗМЕНЕНИЙ | — | — | — |
| test_b2_v6_timestamp_identity_close_reason.py | НОВЫЙ | 16 тестов V6-A..P | A, B, C | все 16 |
| test_b2_close_accounting.py (20) | БЕЗ ИЗМЕНЕНИЙ | прежние B2-тесты v1 | — | — |
| test_b2_csv_recovery.py (10) | БЕЗ ИЗМЕНЕНИЙ | прежние B2-тесты v3 | — | — |
| test_b2_terminal_metadata_recovery.py (12) | БЕЗ ИЗМЕНЕНИЙ | прежние B2-тесты v2 | — | — |
| test_b2_v4_accounting_consistency.py (9) | БЕЗ ИЗМЕНЕНИЙ | прежние B2-тесты v4 | — | — |
| test_b2_v5_identity_and_timestamp.py (10) | БЕЗ ИЗМЕНЕНИЙ | прежние B2-тесты v5 | — | — |

За пределами main.py / execution.py / logger.py и тестов изменений НЕТ
(проверено: см. «Проверка diff на изменения вне scope» в MERGE_REPORT.md).

## SHA256 изменённых/новых файлов

### До изменений (точный код v5)

```
00d7fdfc813f4a98672790314e2a3e530e34471a73a40836220a93c7a471fe07  main.py
2b4ca67f61e816457f66f4d75a3b25dcecc2672815637be0febc300bc219b7fd  execution.py
df22ed916cb2eda10473cb78c2f93846d0be00c8a7ad5913a6bab8d9ee8ad4c5  logger.py
```

### После изменений (v6)

```
2fcd992a691947ad8afba7d4bf336d828b1ab6fd5cf8c4ba3acebc5450338aae  main.py
db62dd127e4ac06acd7061cbb90bcfb6e29187119fc59d2540dd1039d5f5cd8f  execution.py
df22ed916cb2eda10473cb78c2f93846d0be00c8a7ad5913a6bab8d9ee8ad4c5  logger.py   (не менялся)
4cc14ee9a8e2573b8f9384770375e696f68866000599c7e4c6d34660db6599df  test_b2_v6_timestamp_identity_close_reason.py (новый)
```

Полный список SHA256 всех файлов кандидата — в `SHA256SUMS.txt`.

## Детали изменений

### main.py — Defect A (V6-A..D)

* ДО: в `_try_resolve_absent_position()` (ветка В2 «позиция отсутствует у
  брокера, своя SELL-заявка») первоначальное время запроса перезаписывалось:

  ```python
  pos.close_requested_at = (rec.get("updated_at_utc")
                            or rec.get("timestamp_utc")
                            or pos.close_requested_at
                            or datetime.now(timezone.utc).isoformat())
  ```

  `updated_at_utc` реестра — время ПОЗДНЕЙ синхронизации записи (после
  перезапуска/восстановления) — заменяло первоначальный timestamp запроса
  SELL, CSV получал искажённый `exit_time`, chronological cumulative P&L
  ломался. Резервное `datetime.now()` подставлялось внутрь recovery-функции.

* ПОСЛЕ: `pos.close_requested_at = _restore_close_requested_at(pos, oid)` —
  детерминированная приоритетность (ТЗ V6 п.2.2):
  1) существующий ВАЛИДНЫЙ `pos.close_requested_at` — не перезаписывается
     никогда;
  2) `requested_at` СВОЕГО per-order close cursor'а
     (`close_orders[oid]["requested_at"]`);
  3) `requested_at` собственной записи `close_orders` через другой
     сохранённый идентификатор ЭТОЙ ЖЕ заявки (close_order_request_id /
     close_order_id);
  4) исторического времени нет -> None; datetime.now() внутрь восстановления
     не подставляется — управление передаётся существующей ЯВНО обозначенной
     legacy-политике записи CSV (`_close_request_ts` -> момент записи строки;
     `timestamp_utc` при этом остаётся пустым — подстановка не выдаётся за
     сохранённое время).

* `_valid_saved_ts(value)` — валидатор сохранённого времени (непустая
  разборная ISO-строка); мусорные значения валидным временем не считаются.

* Проверены ВСЕ пути восстановления B2: `_try_resolve_absent_position()`
  (единственное место перезаписи); `resolve_closing()`/`apply_close_execution()`
  (execution.py) `close_requested_at` не трогают; `_recover_late_csv_metadata()`
  `exit_time` не меняет (обновляет только цену/комиссию); `_finalize_position_closed()`
  (В3, закрытие БЕЗ своей заявки) — существующая явная legacy-политика, не
  менялась. `updated_at_utc`/`timestamp_utc` реестра остаются метаданными
  ledger и в `close_requested_at` не попадают.

### main.py — Defect C (V6-M..P)

* ДО: `close_reason = reason_text[len("close:"):].split()[0].upper() or close_reason`
  при `reason_text == "close:"` бросал IndexError (путь достижим:
  UNCERTAIN-позиция, отсутствующая у брокера, своя close-заявка, пустой
  `close_reason` — INTENT записан с `reason="close:"` при пустом
  `pos.close_reason`).

* ПОСЛЕ: безопасный разбор — пустой/пробельный хвост не вызывает исключения;
  приоритет: явная причина из реестра -> прежняя известная причина позиции
  (`pos.close_reason`) -> существующий безопасный fallback проекта
  (`"LEDGER_CLOSE"`). Новый тип закрытия не придуман; семантика обычных
  причин (`close:STOP_LOSS` -> `STOP_LOSS`) не изменилась; функция переписана
  точечно (только разбор причины), логика закрытия и количество лотов не
  затронуты.

### execution.py — Defect B (V6-D(b)..L)

* `add_close_order()`: каждая НОВАЯ запись cursor'а получает ЯВНЫЙ маркер
  формата `"identity_version": 2` (`CURSOR_IDENTITY_VERSION`). Существующая
  запись до нового формата не повышается (идемпотентный повтор возвращает её
  как есть).

* `validate_recovery_identity()`: разделены ДВА формата cursor'а:
  * НОВЫЙ (маркер identity_version): обязательны `trade_id`, `figi`, `side`,
    `order_id` (== ключу `close_orders` — связь с соответствующей
    close-заявкой). Пустое/отсутствующее обязательное поле -> конфликт
    `cursor_missing_*` (fail-closed). Противоречие снимку ->
    `cursor_trade_id_mismatch` / `cursor_figi_mismatch` /
    `cursor_side_mismatch` / `cursor_order_id_mismatch`. Никакого молчаливого
    пропуска пустых обязательных полей.
  * LEGACY (без маркера — старые state.json): отдельная политика — проверяются
    ВСЕ реально доступные (непустые) идентификаторы; противоречие — fail-closed;
    НЕПОЛНОТА проверки не считается конфликтом (обратная совместимость), но
    НЕ выдаётся за полную: режим фиксируется в задаче
    (`cursor_validation="legacy_limited"`, персистентен в state.json) и
    журналируется. Автоматического повышения старой записи до нового формата
    нет; любой cursor без trade_id/figi/side автоматически «корректным
    legacy» не считается.

* ВТОРАЯ ссылка той же close-заявки: если сохранены и клиентский UUID, и
  биржевой ID, существующий cursor по второй ссылке тоже проверяется на
  противоречие снимку (клиентский UUID, биржевой ID и trade_id — РАЗНЫЕ
  идентификаторы; ни один не подменяет другой только потому, что все они
  строки).

* `cursor_validation_mode(rec)` -> "full" / "legacy_limited" / "none";
  значение сохраняется в задаче при `archive_pending_csv_recovery()` и при
  каждом `import_state()` (ревалидация идемпотентна, значение выводится из
  снимка).

* `_recovery_canonical_body()`: производные метаданные (`conflict`,
  `cursor_validation`) исключены из сравнения дубликатов — дедупликация
  стабильна между перезапусками.

* Не ослаблено: проверка rec<->снимок (trade_id, FIGI), требование своей
  close-заявки, fail-closed протокол (задача не опрашивается, не меняет CSV,
  не удаляется как завершённая, маркер персистентен), дедупликация
  trade_id-дубликатов, CSV-предпроверка строки (row_figi_mismatch /
  row_order_id_mismatch из v5).

## Подтверждение

STRATEGY LOGIC: UNCHANGED

RESEARCH ONLY

NO THRESHOLD IS OPTIMIZED

NO FILTER IS INSTALLED

NO LIVE ORDERS

OOS SEALED / H4 EXECUTION NOT AUTHORIZED
