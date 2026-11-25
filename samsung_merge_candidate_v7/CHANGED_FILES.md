# CHANGED_FILES.md — samsung_merge_candidate_v7 (v2.3.10-stage1)

B2 V7 — CURSOR IDENTITY VERSION TRICHOTOMY + CONFIRMED ALTERNATIVE
TIMESTAMP (исправление двух остаточных дефектов V6).

База: `samsung_merge_candidate_v6` (код v6 = рабочее дерево `env_v6`;
файлы main.py/execution.py/logger.py побайтово идентичны кандидатной папке
v6 — SHA256 сверены). Сама папка `samsung_merge_candidate_v6` НЕ изменялась
(SHA256 до/после совпадают, см. MERGE_REPORT.md §8). Samsung-репозиторий
READ-ONLY, не изменялся.

Исходное состояние базы зафиксировано SHA256 (точный код v6):

```
2fcd992a691947ad8afba7d4bf336d828b1ab6fd5cf8c4ba3acebc5450338aae  main.py
db62dd127e4ac06acd7061cbb90bcfb6e29187119fc59d2540dd1039d5f5cd8f  execution.py
df22ed916cb2eda10473cb78c2f93846d0be00c8a7ad5913a6bab8d9ee8ad4c5  logger.py
```

Baseline-прогон выполнен на КОПИИ этого кода (env_v7) ДО изменений V7 —
различие baseline/final гарантированно исчерпывается изменениями v7.

## Сводка изменений

| Файл | Статус | Назначение | Дефект | Тесты |
|---|---|---|---|---|
| execution.py | ИЗМЕНЁН | Трихотомия маркера `identity_version` (`_cursor_identity_state`: legacy / new / invalid); `_cursor_is_new_format` — только «new»; единая точка проверки `_cursor_identity_conflict_checked` (invalid -> `cursor_invalid_identity_version`, ДО остальных проверок); `cursor_validation_mode` — новый режим `invalid_version`; `archive_pending_csv_recovery` — три состояния | №1 | V7-A..F |
| main.py | ИЗМЕНЁН | `_restore_close_requested_at()`: приоритет 3 — ТОЛЬКО подтверждённый альтернативный cursor (новый helper `_alt_cursor_identity_conflict`: версия cursor'а, trade_id, FIGI, side, order_id==ключу, положительная привязка trade_id+order_id; отказ -> timestamp НЕ используется, None + legacy-политика) | №2 | V7-G..M |
| logger.py | БЕЗ ИЗМЕНЕНИЙ | — | — | — |
| test_b2_v7_cursor_version_and_alt_timestamp.py | НОВЫЙ | 13 тестов V7-A..M (19 pytest-итемов: V7-E параметризован ×7) | №1, №2 | все 19 |
| test_b2_close_accounting.py (20) | БЕЗ ИЗМЕНЕНИЙ | прежние B2-тесты v1 | — | — |
| test_b2_csv_recovery.py (14) | БЕЗ ИЗМЕНЕНИЙ | прежние B2-тесты v3 | — | — |
| test_b2_terminal_metadata_recovery.py (8) | БЕЗ ИЗМЕНЕНИЙ | прежние B2-тесты v2 | — | — |
| test_b2_v4_accounting_consistency.py (9) | БЕЗ ИЗМЕНЕНИЙ | прежние B2-тесты v4 | — | — |
| test_b2_v5_identity_and_timestamp.py (10) | БЕЗ ИЗМЕНЕНИЙ | прежние B2-тесты v5 | — | — |
| test_b2_v6_timestamp_identity_close_reason.py (16) | БЕЗ ИЗМЕНЕНИЙ | тесты V6-A..P | — | — |

Примечание о счётчиках прежних B2-тестов: фактические количества по файлам
(сверены с pytest output `appendix_B2_TESTS_OUTPUT.txt`) —
test_b2_close_accounting.py **20**, test_b2_csv_recovery.py **14**,
test_b2_terminal_metadata_recovery.py **8**, test_b2_v4_accounting_consistency.py
**9**, test_b2_v5_identity_and_timestamp.py **10**; итого **61** (см.
MERGE_REPORT.md §5 — исправление расхождения V6, где отчёт ошибочно
указывал 51 и неверные количества по файлам). Тесты не менялись «под
количество» — исправлена только отчётная цифра.

За пределами main.py / execution.py / logger.py и тестов изменений НЕТ
(проверено: см. «Проверка diff на изменения вне scope» в MERGE_REPORT.md §7).

## SHA256 изменённых/новых файлов

### До изменений (точный код v6)

```
2fcd992a691947ad8afba7d4bf336d828b1ab6fd5cf8c4ba3acebc5450338aae  main.py
db62dd127e4ac06acd7061cbb90bcfb6e29187119fc59d2540dd1039d5f5cd8f  execution.py
df22ed916cb2eda10473cb78c2f93846d0be00c8a7ad5913a6bab8d9ee8ad4c5  logger.py
```

### После изменений (v7)

```
fac787ac6d51b377efec35aff4122971ad681c3e9a463739e64e0c5938162777  main.py
6fd0ed195392085c503d0d696e3a7d72d7cf0b691dd6bf29bf8f03a3be9ede00  execution.py
df22ed916cb2eda10473cb78c2f93846d0be00c8a7ad5913a6bab8d9ee8ad4c5  logger.py   (не менялся)
13dad5593c15a17dd01b080c2f73c4a1b7e17a66ba653943f2bca915d5cbd7f4  test_b2_v7_cursor_version_and_alt_timestamp.py (новый)
```

Полный список SHA256 всех файлов пакета — в `SHA256SUMS.txt`.

## Детали изменений

### execution.py — Дефект №1 (V7-A..F)

* ДО (v6): `_cursor_is_new_format()` возвращала False не только для
  настоящего legacy-cursor (ключа `identity_version` нет), но и для cursor
  с ПРИСУТСТВУЮЩИМ, но некорректным/неизвестным маркером (`"abc"`, 1, 999,
  пустые/нулевые значения) — во всех местах проверки такой cursor
  ошибочно шёл по ОСЛАБЛЕННОЙ legacy-политике (проверка только доступных
  идентификаторов, `cursor_validation="legacy_limited"`): некорректный
  маркер версии ослаблял проверку идентичности.
* ПОСЛЕ (v7): введена строгая ТРИХОТОМИЯ `_cursor_identity_state()`:
  - `"legacy"` — ТОЛЬКО отсутствие ключа `identity_version` (существующая
    legacy-политика сохранена без изменений);
  - `"new"` — маркер равен поддерживаемой `CURSOR_IDENTITY_VERSION`
    (число/строка эквивалентны — JSON-окружение state.json);
  - `"invalid"` — ключ присутствует, но значение None/пустое/нулевое/
    нечисловое/неизвестное — fail-closed: НЕ legacy, `_cursor_is_new_format()`
    по-прежнему False (но False больше не означает «legacy»), проверки идут
    через `_cursor_identity_conflict_checked()`, который при состоянии
    invalid ДО любых других проверок возвращает
    `cursor_invalid_identity_version`; recovery-задача остаётся с
    диагностической причиной конфликта: брокер не опрашивается, CSV не
    обновляется, задача не удаляется; автоматическое повышение версии и
    молчаливое преобразование формата исключены;
  - `cursor_validation_mode()` — отдельный режим `invalid_version`
    (персистентен в задаче; НЕ full, НЕ legacy_limited);
  - `add_close_order()` — маркер версии новых записей НЕ изменён
    (по-прежнему `CURSOR_IDENTITY_VERSION`).

### main.py — Дефект №2 (V7-G..M)

* ДО (v6): `_restore_close_requested_at()`, приоритет 3 — запись
  close_orders, найденная через ДРУГОЙ сохранённый идентификатор
  (close_order_request_id / close_order_id), использовала свой
  `requested_at` БЕЗ проверки, что найденный cursor действительно
  относится к той же сделке и заявке: совпадение КЛЮЧА считалось
  достаточным доказательством, под собственным ключом мог лежать cursor
  другой сделки того же FIGI — чужой timestamp попадал в
  close_requested_at.
* ПОСЛЕ (v7): перед использованием requested_at вызывается
  `_alt_cursor_identity_conflict(pos, alt_id, cursor)`:
  - некорректная/неизвестная версия маркера -> отказ
    (`cursor_invalid_identity_version`);
  - противоречие снимку (trade_id / FIGI / side) или собственной
    close-заявке (order_id != ключу) -> отказ (cursor_*_mismatch);
  - положительная привязка: cursor обязан содержать непустые trade_id
    (== снимку) и order_id (== ключу) — иначе идентичность НЕ подтверждена
    (`cursor_unconfirmed_identity`), timestamp НЕ используется;
  - отказ -> приоритет 4: None и существующая явно обозначенная
    legacy-политика записи CSV; datetime.now() внутрь восстановления НЕ
    подставляется; updated_at_utc/timestamp_utc реестра не используются.
* Правильный приоритет времени СОХРАНЁН: 1) существующий валидный
  pos.close_requested_at; 2) свой валидный per-order cursor; 3)
  подтверждённый альтернативный cursor той же заявки; 4) None +
  legacy-политика. Новых типов закрытия нет, семантика CSV не менялась.

## Что НЕ изменено

* logger.py — байт-в-байт идентичен v6/v5 (изменение не требовалось);
* стратегия, сигналы, фильтры/пороги, риск-менеджмент, BUY-цепочка, SL/TP,
  screener, B3-внешние закрытия — не тронуты (см. FULL_DIFF.patch);
* формат state.json и legacy-совместимость — сохранены (legacy cursor без
  маркера по-прежнему обрабатывается существующей legacy-политикой);
* публичные интерфейсы — не переименовывались, поля не переименовывались;
* `add_close_order()` — формат новых cursor'ов не изменён.
