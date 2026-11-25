# MERGE_REPORT — samsung_merge_candidate_v7 (v2.3.10-stage1)

**B2 V7 — CURSOR IDENTITY VERSION TRICHOTOMY + CONFIRMED ALTERNATIVE TIMESTAMP**

Дата: 2026-11-25. База: `samsung_merge_candidate_v6` (v2.3.9-stage1).
Папка `samsung_merge_candidate_v6` НЕ изменялась; создана независимая копия
`samsung_merge_candidate_v7`. Samsung-репозиторий READ-ONLY, не изменялся;
LIVE ORDERS и sandbox BUY/SELL не выполнялись; торговые методы брокера не
вызывались; state.json не изменялся.

## 1. Цель

Два точечных исправления остаточных дефектов V6 (без переделки архитектуры
B2, без глобального рефакторинга):

* **Дефект №1 (execution.py)** — некорректная версия cursor'а превращалась
  в LEGACY: `_cursor_is_new_format()` возвращала False не только для
  настоящего legacy-cursor (без ключа `identity_version`), но и для cursor
  с присутствующим, но некорректным/неизвестным маркером (`"abc"`, 1, 999,
  None, "", 0) — такой cursor ошибочно обрабатывался ослабленной
  legacy-политикой, т.е. некорректный маркер версии ОСЛАБЛЯЛ проверку
  идентичности.
* **Дефект №2 (main.py)** — альтернативный cursor мог предоставить чужой
  timestamp: `_restore_close_requested_at()` на приоритете 3 (запись
  close_orders через другой сохранённый идентификатор той же заявки)
  использовала `requested_at` найденного cursor'а БЕЗ проверки, что запись
  относится к той же сделке и заявке — совпадение ключа считалось
  достаточным доказательством идентичности.

## 2. Фиксация базы v6

* SHA256 исходников v6 (сверены с кандидатной папкой v6, побайтово):
  * main.py `2fcd992a691947ad8afba7d4bf336d828b1ab6fd5cf8c4ba3acebc5450338aae`
  * execution.py `db62dd127e4ac06acd7061cbb90bcfb6e29187119fc59d2540dd1039d5f5cd8f`
  * logger.py `df22ed916cb2eda10473cb78c2f93846d0be00c8a7ad5913a6bab8d9ee8ad4c5`
* v7-копия создана из полного рабочего дерева с кодом v6 в корне
  (`env_v7`); baseline-прогон выполнен на ЭТОЙ КОПИИ ДО изменений —
  различие baseline/final гарантированно исчерпывается изменениями v7.
* Старые B2-тесты v1–v6 и logger.py в копии побайтово идентичны
  кандидатной папке v6 (SHA256 сверены до и после работы).

## 3. Реализация исправлений

Кратко (полные детали — в CHANGED_FILES.md, полный diff — FULL_DIFF.patch):

* **Дефект №1 (execution.py)**: введена строгая ТРИХОТОМИЯ
  `_cursor_identity_state()`: `"legacy"` — ТОЛЬКО отсутствие ключа
  `identity_version` (существующая legacy-политика сохранена);
  `"new"` — маркер равен поддерживаемой `CURSOR_IDENTITY_VERSION`;
  `"invalid"` — ключ присутствует, но значение пустое/нулевое/нечисловое/
  неизвестное — fail-closed. Единая точка проверки
  `_cursor_identity_conflict_checked()`: состояние invalid ДО остальных
  проверок даёт конфликт `cursor_invalid_identity_version` (recovery-задача
  сохраняется с диагностической причиной: брокер не опрашивается, CSV не
  обновляется, задача не удаляется); состояние new — строгая проверка
  обязательных полей (trade_id, FIGI, side, order_id==ключу); состояние
  legacy — проверка всех ДОСТУПНЫХ идентификаторов. `cursor_validation_mode()`
  получил отдельный режим `invalid_version` (НЕ full, НЕ legacy_limited);
  `archive_pending_csv_recovery()` классифицирует все три состояния.
  Отсутствие ключа, None, пустая строка, ноль, неверная строка и
  неизвестная числовая версия — РАЗНЫЕ значения маркера; молчаливого
  преобразования и автоматического повышения версии нет.
  `add_close_order()` пишет прежний поддерживаемый маркер версии
  (без изменений).
* **Дефект №2 (main.py)**: приоритет 3 в `_restore_close_requested_at()`
  теперь использует ТОЛЬКО подтверждённый альтернативный cursor — перед
  взятием `requested_at` вызывается `_alt_cursor_identity_conflict()`:
  корректная версия маркера, отсутствие противоречий trade_id/FIGI/side
  снимку и order_id ключу (для нового формата — строгая обязательность
  полей), положительная привязка trade_id (== снимку) и order_id
  (== ключу). Любой отказ — timestamp НЕ используется (в т.ч. никогда не
  берётся время cursor'а другой сделки того же FIGI); срабатывает
  приоритет 4: None и существующая явно обозначенная legacy-политика
  записи CSV. Приоритет времени не изменён: 1) существующий валидный
  pos.close_requested_at; 2) свой валидный per-order cursor; 3)
  подтверждённый альтернативный cursor той же заявки; 4) None +
  legacy-политика. updated_at_utc/timestamp_utc реестра и datetime.now()
  внутрь восстановления не подставляются. Новых типов закрытия нет,
  семантика CSV не менялась.

## 4. Тестирование

Окружение: Python 3.12.16, pytest 9.0.2, Linux sandbox. Команда прогонов:

```
python3 -m pytest -p no:cacheprovider --continue-on-collection-errors -q
```

### 4.1 Baseline (точный код v6, до изменений v7)

**74 failed, 643 passed, 1 error** — лог `appendix_BASELINE_FULL_PYTEST.txt`.
FAILED/ERROR-набор ПО ИМЕНАМ: `appendix_baseline_failed_names.txt`
(74 FAILED + 1 collection error `test_execution.py` — pre-existing, не
связан с B2; набор совпадает с финальным набором v6).
Baseline старых B2-тестов v1–v6 (6 файлов): **77 passed** (61 прежних +
16 тестов V6-A..P) — на чистой копии v6 до изменений; лог
`appendix_BASELINE_B2_TESTS_OUTPUT.txt`.

### 4.2 Final (после изменений v7)

**74 failed, 662 passed, 1 error** — лог `appendix_FINAL_FULL_PYTEST.txt`.
Разница с baseline: **+19 passed** (новые pytest-итемы V7; 13 тестовых
функций, V7-E параметризована на 7 вариантов маркера).
Старые B2-тесты v1–v6 на коде v7: **77 passed** —
`appendix_OLD_B2_TESTS_V1_V6_OUTPUT.txt`.

### 4.3 Сравнение по КОНКРЕТНЫМ ИМЕНАМ (не по количеству)

```
diff appendix_baseline_failed_names.txt appendix_final_failed_names.txt
=> пусто
```

Ни одного нового или исчезнувшего FAILED; ERROR/collection errors сравнены
отдельно: единственный ERROR — pre-existing collection error корневого
`test_execution.py`, идентичен в baseline и final. Дополнительно: final
FAILED-набор v7 ПОБАЙТОВО совпадает с финальным набором v6. Совпадение
количеств не использовалось как доказательство отсутствия регрессий —
сравнивались точные имена.

### 4.4 Прежние B2-тесты v1–v6 на коде v7 — 77 passed (61 + 16)

```
test_b2_close_accounting.py             20 passed
test_b2_csv_recovery.py                 14 passed
test_b2_terminal_metadata_recovery.py    8 passed
test_b2_v4_accounting_consistency.py     9 passed
test_b2_v5_identity_and_timestamp.py    10 passed
---------------------------------------------
ИТОГО прежних (v1–v5 файлы)             61 passed
test_b2_v6_timestamp_identity_close_reason.py  16 passed
---------------------------------------------
ИТОГО ВСЕ старые B2 v1–v6               77 passed
```
Логи: `appendix_B2_TESTS_OUTPUT.txt` (61), `appendix_OLD_B2_TESTS_V1_V6_OUTPUT.txt`
(77).

### 4.5 Исправление расхождения отчётности V6 (51 -> 61)

В пакете V6 обнаружено расхождение: `appendix_B2_TESTS_OUTPUT.txt`
фактически содержит **61 passed**, а MERGE_REPORT.md/README.md v6 ошибочно
указывали **51 passed** с неверными количествами по файлам
(test_b2_csv_recovery.py указан как 10 вместо фактических **14**;
test_b2_terminal_metadata_recovery.py — как 12 вместо фактических **8**).
Фактическое разбиение 61 по pytest output: 20 + 14 + 8 + 9 + 10 = 61.
В V7 все документы используют фактические количества, сверенные с
pytest output; сами тесты НЕ менялись «под количество» — исправлена
только отчётная цифра. Прямая сверка: `appendix_B2_TESTS_OUTPUT.txt` v7 —
`collected 61 items`, `61 passed`.

### 4.6 Новые тесты V7-A..M на коде v7 — 19 passed

Файл `test_b2_v7_cursor_version_and_alt_timestamp.py`; лог
`appendix_V7_TESTS_OUTPUT.txt`:

| Тест | Сценарий | Результат |
|---|---|---|
| V7-A | cursor БЕЗ ключа identity_version -> LEGACY, существующая legacy-проверка проходит (legacy_limited), восстановление завершается | PASSED |
| V7-B | cursor с поддерживаемой версией -> строгая проверка проходит (full), число/строка эквивалентны | PASSED |
| V7-C | identity_version="abc" -> БЛОКИРУЕТСЯ: cursor_invalid_identity_version, режим invalid_version (НЕ legacy), задача с конфликтом, маркер не «повышается» | PASSED |
| V7-D | identity_version=1 и 999 -> БЛОКИРУЮТСЯ (fail-closed, НЕ legacy, без автоповышения) | PASSED |
| V7-E | присутствующий, но пустой/нулевей/некорректный маркер (None, "", 0, "0", False, "2.0", "  ") — 7 вариантов -> БЛОКИРУЮТСЯ, НЕ legacy_limited | PASSED |
| V7-F | интеграция: некорректная версия после import/restart — конфликт персистентен; брокер не опрашивается, CSV не обновляется, задача не удаляется | PASSED |
| V7-G | альтернативный cursor с теми же trade_id/FIGI/side/order_id -> ПРИНИМАЕТСЯ; timestamp 09:05 восстанавливается (юнит + полный B2 reconcile, CSV exit_time=09:05) | PASSED |
| V7-H | альтернативный cursor с чужим trade_id -> ОТВЕРГАЕТСЯ (cursor_trade_id_mismatch) | PASSED |
| V7-I | альтернативный cursor с чужим FIGI -> ОТВЕРГАЕТСЯ (cursor_figi_mismatch) | PASSED |
| V7-J | неправильный side / чужой order_id / cursor вообще без идентификаторов -> ОТВЕРГАЕТСЯ (side_mismatch / order_id_mismatch / unconfirmed_identity) | PASSED |
| V7-K | альтернативный cursor с identity_version="abc" и 999 -> ОТВЕРГАЕТСЯ, даже при совпадающих идентификаторах | PASSED |
| V7-L | конфликт альтернативного cursor'а в ПОЛНОМ reconcile: чужое время и datetime.now() НЕ подставляются; None + legacy-политика (exit_time=момент записи, timestamp_utc пуст) | PASSED |
| V7-M | ДВЕ сделки ОДНОГО FIGI: timestamp второй не перетекает в первую и наоборот; подтверждённый альтернативный cursor СВОЕЙ сделки принимается | PASSED |

### 4.7 Негативная валидация (V7-тесты на коде v6, до исправлений)

**18 failed, 1 passed** — лог `appendix_NEGATIVE_VALIDATION_OLD_CODE.txt`.
На коде v6 падают ВСЕ тесты, ловящие дефекты:
* дефект №1: V7-C/D/E(×7)/F — старый код трактовал некорректную версию как
  legacy (конфликта нет: `assert None == 'cursor_invalid_identity_version'`);
  V7-A/B падают на отсутствии трёхсостоянийого API (`_cursor_identity_state`)
  в v6 — поведение «некорректная версия == legacy» в v6 покрыто падениями
  C/D/E/F;
* дефект №2: V7-H/I/J/K/L/M — старый код БРАЛ чужой timestamp без проверки
  (`close_requested_at == '2026-11-20T10:05:00+00:00'` — ровно описанный
  дефект).
Единственный проходящий на старом коде тест — V7-G (положительный путь:
безусловное принятие альтернативного cursor'а в v6 тоже даёт корректный
результат на ПОЛНОСТЬЮ согласованных данных; негативные варианты тех же
механизмов — H–M — на старом коде падают). Это не скрывается.

## 5. Сохранность v1–v6 (проверено тестами, без регрессий)

* B2 close accounting (per-order cursor, идемпотентность, fail-closed) —
  test_b2_close_accounting.py: 20 passed;
* terminal duplicate enrichment / late metadata —
  test_b2_terminal_metadata_recovery.py: 8 passed;
* CSV late metadata recovery, атомарная запись, chronological cumulative
  P&L, deterministic tie-breaker, cross-contamination —
  test_b2_csv_recovery.py: 14 passed;
* persistent pending recovery, перезапуск, стабильный trade_id, requested/
  executed lots, отсутствие CSV-дубликатов —
  test_b2_v4_accounting_consistency.py: 9 passed;
* сохранение времени запроса SELL и fail-closed идентичность v5 —
  test_b2_v5_identity_and_timestamp.py: 10 passed;
* timestamp integrity + strict recovery identity + empty close reason v6 —
  test_b2_v6_timestamp_identity_close_reason.py: 16 passed;
* полный pytest: FAILED/ERROR-набор по именам идентичен baseline (и
  финальному набору v6).

## 6. Проверка отрицательных сценариев и идентичности (сводка)

* неизвестная/некорректная/пустая/нулевая версия маркера — НЕ legacy:
  V7-C, V7-D, V7-E(×7), V7-F, V7-K;
* альтернативный timestamp без подтверждённой идентичности не
  используется: V7-H, V7-I, V7-J, V7-K, V7-L, V7-M;
* смешивание сделок одного FIGI невозможно: V7-M (обе стороны) + V6-D
  (regression);
* fail-closed протокол recovery-задач (не опрашивать брокера / не менять
  CSV / не удалять задачу / диагностическая причина): V7-C, V7-F;
* отсутствие подмены времени (datetime.now(), updated_at_utc,
  timestamp_utc): V7-L (exit_time=момент записи, timestamp_utc пуст),
  V6-A/V6-C (regression).

## 7. Проверка diff на изменения вне scope

Изменены ТОЛЬКО main.py и execution.py (+ новый тест-файл). logger.py,
конфигурация, стратегия, сигналы, BUY, SL/TP, RiskManager, screener,
фильтры/пороги, отправка заявок, B3 — НЕ тронуты (см. FULL_DIFF.patch —
11 hunks: только `_cursor_identity_state`/`_cursor_is_new_format`/
`_cursor_identity_conflict_checked`/`cursor_validation_mode`/
`archive_pending_csv_recovery`/`validate_recovery_identity` в execution.py;
только `_alt_cursor_identity_conflict` + `_restore_close_requested_at`
(докстринг, шаг 3) + комментарий места вызова в main.py).
Формат state.json и legacy-совместимость сохранены; публичные интерфейсы
не переименовывались.

## 8. Ограничения и неизменность (подтверждения)

* **V1–V6 не перезаписаны и не изменены**: все операции записи выполнялись
  ТОЛЬКО в `work/b2_v7/` (env_v7, samsung_merge_candidate_v7, логи) и
  `download/`; SHA256 исходников v6 и старых тестов сверены до и после
  работы — совпадают побайтово; папки v2–v6 не открывались на запись.
* **Samsung READ-ONLY**: SHA256 файлов Samsung-копий зафиксированы до
  работы (`SAMSUNG_READONLY_BASELINE.txt`) и сверены после — совпадают;
  коммитов и загрузок в Samsung нет; GitHub-плагин не использовался.
* **Торговые операции не выполнялись**: брокер не вызывался, BUY/SELL не
  отправлялись (в тестах торговые методы fake-клиентов бросают
  AssertionError и фиксируются только списки вызовов); реальные
  state.json/order_ledger.jsonl не редактировались (все тесты —
  fake-объекты и tmp_path); обращений к реальному брокеру нет.
* **Секреты**: пакет проверен сканированием на токены/ключи/пароли —
  не содержит (см. TEST_RESULTS.txt).
* **ZIP**: `Tsclp_B2_V7_candidate.zip` проверен на целостность (unzip -t),
  полный список файлов сверен с отчётом, SHA256 архива зафиксирован в
  итоговом сообщении (сам архив не может содержать собственный хэш).

## Подтверждение

STRATEGY LOGIC: UNCHANGED

RESEARCH ONLY

NO THRESHOLD IS OPTIMIZED

NO FILTER IS INSTALLED

NO LIVE ORDERS

OOS SEALED / H4 EXECUTION NOT AUTHORIZED
