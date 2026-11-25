# MERGE_REPORT — samsung_B2_integrated_v1_v7

**B2 SAFE INTEGRATION V1–V7 INTO SAMSUNG**

Дата: 2026-11-25. Режим: RESEARCH ONLY. NO LIVE ORDERS. NO BROKER OPERATIONS.
Исходный Samsung-репозиторий READ-ONLY — не изменялся; ничего в него не
переносилось. Папки кандидатов v1–v7 (`cristal-hub/temp`) не изменялись.
Торговые операции не выполнялись: брокер не вызывался, BUY/SELL не
отправлялись, state.json/order_ledger.jsonl/research_trades.csv не
редактировались.

## 1. Цель и результат

Выполнена безопасная интеграция накопленных исправлений **B2 Close
Accounting v1–v7** в актуальный основной проект Samsung — БЕЗ замены файлов
целиком, с сохранением всех Samsung-specific изменений. Результат: отдельный
интегрированный кандидат `samsung_B2_integrated_v1_v7/`, готовый к
независимому аудиту.

## 2. Источники и фиксация базы (ДО изменений)

| Артефакт | Значение |
|---|---|
| SOURCE OF TRUTH | https://github.com/cristal-hub/cristal-hub-Tsclp_v2.1_volatile_Samsung, ветка `main` |
| Samsung commit | `051b10f095d45c053492ca333449a9a9f518f33f` (HEAD origin/main, 2026-11-23 22:49:11 +0300, «Add files via upload») |
| Samsung main.py | 4327 строк, SHA256 `8ed2293bb88bb96b196b451ff0dc468d9fdc96a856634907f5ee9191f2df6be6` |
| Samsung execution.py | 1083 строки, SHA256 `72b19783d1d1e811e51c7522ba60f524ecffb7b57f393c34efd2c033680d40d2` |
| Samsung logger.py | 159 строк, SHA256 `266c937e2946058e6255b6584aee5c26e4e34dadaffeffe755eca7435924f164` |
| Прочие производственные модули | config `6c4df6e4…`, strategy `43906866…`, risk_manager `d1c72c2e…`, order_ledger `766e1f37…`, tinkoff_client `fe69b045…` — зафиксированы (SHA256SUMS.txt), не изменялись |
| B2 reference candidate | https://github.com/cristal-hub/temp → `samsung_merge_candidate_v7` (v2.3.10-stage1; main `fac787ac…`, execution `6fd0ed19…`, logger `df22ed91…`) |
| История v1–v6 | `temp/samsung_merge_candidate_v1…v6` — использованы для точной атрибуции каждого исправления своей версии (MERGE_REPORT v1–v6, SHA256-цепочки баз) |

## 3. Ключевое доказательство корректности слияния

```
Samsung (051b10f) main.py/execution.py/logger.py  +  FULL_DIFF.patch
   == интегрированный кандидат        (побайтово, cmp)
   == temp/samsung_merge_candidate_v7 (производственные файлы, побайтово)
```

* Патч применён `patch --batch --fuzz=0` — чисто, без fuzz и reject
  (`.rej`/`.orig` не созданы).
* Round-trip: на СВЕЖЕЙ копии Samsung патч применён повторно — результат
  побайтово совпал с кандидатом.
* Это доказывает одновременно: перенесены ВСЕ B2-изменения; в кандидате НЕТ
  ни одного изменения вне перенесённого B2-диффа; ни одна Samsung-правка не
  потеряна и не подменена; wholesale replacement отсутствует — кандидат
  ПОСТРОЕН ИЗ Samsung-файлов, поверх которых применён только B2-патч
  (9338 строк патча против 5569 строк производственных файлов Samsung).
* Размеры согласуются с ТЗ: main.py 4328/5544, execution.py 1084/1735,
  logger.py 160/582 (счётчик ТЗ учитывает последнюю строку без перевода).

## 4. Интеграционный анализ (п.6 ТЗ)

Для каждого исправления v1–v7 выполнено: найдена исходная Samsung-функция →
найдено исправление в B2-кандидате → сопоставлены различия и зависимости →
перенесена только необходимая логика → сохранено Samsung-specific поведение →
проверена совместимость вызовов/интерфейсов. Полная таблица: TRANSFER_TABLE.md.

Инструменты анализа:
* **AST-сверка всех функций/классов** (main/execution/logger): в кандидате
  НЕТ ни одной отсутствующей Samsung-функции; список добавленных/изменённых
  ограничен B2-областями (детали: SAMSUNG_PRESERVED.md).
* **Модульный уровень**: не удалён ни один Samsung-элемент; изменения —
  только добавления (11 в logger, 2 в execution + 10 методов класса,
  11 в main) и расширение импорта `from execution import … , TrackedPosition`
  (superset).
* **Классы**: `PositionState` и все значения enum — без изменений;
  `TrackedPosition` — все 34 поля dataclass без изменений;
  `ExecutionMonitor` — только добавление `CURSOR_IDENTITY_VERSION` и 9
  B2-методов.
* **Построчная выверка полного диффа** Samsung→v7 (2693 строки diff по трём
  файлам): каждый hunk отнесён к конкретному исправлению v1–v7; hunks вне
  B2-областей не обнаружены.
* **Инвентаризация diff-ом всего дерева**: различаются ТОЛЬКО main.py,
  execution.py, logger.py (+7 новых тест-файлов); все остальные файлы,
  включая runtime (state.json, order_ledger.jsonl, research_trades.csv,
  research_events.jsonl, sandbox_pnl.csv), побайтово идентичны Samsung.

## 5. Что перенесено (v1–v7) — кратко

1. **v1** — В2-ветка `reconcile` закрывает учёт СТРОГО через штатный
   `ExecutionMonitor.apply_close_execution()` (per-order cursor,
   close_applications, цена, комиссия, идемпотентность); различение False
   (безопасный повтор vs противоречивый отчёт → fail-closed UNCERTAIN);
   синхронизация записи реестра; частичное исполнение: только
   брокер-подтверждённые лоты, запрошенные сохраняются, остаток закрывается
   внешне (без цены/P&L, явный error_note, FILL_PARTIAL). `_finalize_position_closed`
   остаётся только за В3.
2. **v2** — повторный терминальный отчёт: безопасное обогащение
   ТОЛЬКО отсутствующими ценой/комиссией (`_report_value_conflict`),
   противоречие — fail-closed; лоты повторно не применяются.
3. **v3** — late metadata CSV recovery: recovery-проход для CLOSED+logged
   позиций; опрос отчёта close-заявки; сверка с замороженным cursor'ом;
   атомарное обновление СУЩЕСТВУЮЩЕЙ строки CSV по стабильному trade_id
   (`logger.update_trade_row`); пересчёт финансовых полей по формулам
   штатной записи; PRICE_UNKNOWN убирается при подтверждении цены.
4. **v4** — chronological cumulative P&L (`recompute_cumulative_chronological`,
   авторитетное время — exit_time, детерминированный tie-breaker, строки
   не переставляются); персистентные pending CSV recovery задачи
   (`pending_csv_recoveries`, `archive_pending_csv_recovery`, export/import
   state) — переживают замену объекта позиции тем же FIGI и перезапуск.
5. **v5** — единое `close_requested_at` создаётся ДО сетевого вызова SELL и
   переживает потерю ответа (`result.state is None`); `_close_request_ts`
   как единый источник `timestamp_utc`/`exit_time`; валидация идентичности
   recovery-задач (`validate_recovery_identity`: rec↔снимок↔cursor, дедуп/
   блокировка конфликтных дубликатов, fail-closed протокол).
6. **v6** — timestamp integrity: существующий валидный `close_requested_at`
   не перезаписывается никогда; восстановление по приоритетам
   (`_valid_saved_ts`, `_restore_close_requested_at`);
   `updated_at_utc`/`timestamp_utc` реестра и `datetime.now()` не подменяют
   время SELL; строгая проверка обязательных полей cursor'а нового формата
   (`CURSOR_IDENTITY_VERSION`, `_cursor_identity_conflict`,
   `cursor_validation_mode`); пустой `close_reason` не роняет reconcile
   (IndexError устранён, типы закрытия не расширялись).
7. **v7** — строгая трихотомия `identity_version` (`_cursor_identity_state`:
   ключ отсутствует = LEGACY; равен поддерживаемой версии = NEW; присутствует
   и пуст/нулев/нечисловой/неизвестный = INVALID → fail-closed
   `cursor_invalid_identity_version`, режим `invalid_version`, НЕ
   legacy_limited; без broker polling, без обновления CSV, без удаления
   задачи, без автоповышения); `_alt_cursor_identity_conflict` —
   альтернативный cursor используется для timestamp ТОЛЬКО после
   подтверждения идентичности (trade_id, FIGI, side, order_id==ключу,
   положительная привязка к сделке и собственной close-заявке, корректная
   версия); чужой timestamp не попадает в другую сделку, включая две сделки
   одного FIGI (V7-M); `add_close_order()` пишет прежний поддерживаемый
   маркер — без изменений.

Обязательные функциональные требования ТЗ п.5 A–E — покрыты (см. п.8 тестов
и TRANSFER_TABLE.md).

## 6. Что перенесено НЕ было и почему

* Замена main.py/execution.py/logger.py целиком — ЗАПРЕЩЕНА ТЗ и не
  выполнялась (доказательство — п.3).
* Перенос рабочего каталога v7 поверх Samsung — не выполнялся.
* Изменения strategy/config/risk_manager/screener/order_ledger/
  tinkoff_client/telegram_bot/tests — не потребовались ни одному
  исправлению (побайтово идентичны Samsung).
* Дублирование уже существующих в Samsung механизмов (per-order cursor,
  fail-closed resolve_closing/resolve_uncertain, guard «воскрешения»,
  ЭТАП 5Б intent, извлечение цены/комиссии) — не выполнялось: исправления
  надстраиваются НАД ними (список: SAMSUNG_PRESERVED.md §«Уже имелось»).

## 7. Защита Samsung-specific кода (п.8 ТЗ)

* Сравнены ВСЕ функции Samsung main.py (39), execution.py (31), logger.py (6):
  ни одна не удалена, не переименована, не потеряна (SAMSUNG_PRESERVED.md §1).
* Публичные интерфейсы, связи между модулями, импортируемые классы/методы,
  состояния и переходы позиций, обработка заявок и recovery, конфигурация
  запуска — сохранены (§3–4 того же файла + smoke-импорт всех модулей).
* Наличие функций в v7 НЕ использовалось как основание для замены: замена
  выполнена только диффом, и итоговые файлы совпали с v7 побайтово именно
  потому, что v7 сам является Samsung+дифф (проверено независимо).
* Для каждой затронутой Samsung-функции подтверждено сохранение прежнего
  поведения вне конкретного исправляемого дефекта (построчная выверка
  hunks: SAMSUNG_PRESERVED.md §1).

## 8. Тестирование (п.7 ТЗ)

Окружение: Python 3.12.16, pytest 9.0.2, Linux; команда
`python3 -m pytest -p no:cacheprovider --continue-on-collection-errors -q`
(для B2-набора — без `--continue-on-collection-errors`).

### 8.1 Baseline — чистая копия Samsung 051b10f ДО интеграции

**74 failed, 566 passed, 1 error** — `appendix_BASELINE_FULL_PYTEST.txt`.
FAILED/ERROR по точным именам: `appendix_baseline_failed_names.txt`
(74 FAILED + 1 collection error корневого `test_execution.py` — pre-existing
FileNotFoundError, не связан с B2). Контроль воспроизводимости: список имён
ПОБАЙТОВО совпадает с baseline-списком v1-кандидата (среда идентична той,
на которой строилась линейка v1–v7).

### 8.2 Final — интегрированный кандидат

**74 failed, 662 passed, 1 error** — `appendix_FINAL_FULL_PYTEST.txt`.
Разница с baseline: ровно **+96 passed** — весь B2-набор v1–v7.

### 8.3 Сравнение по ТОЧНЫМ ИМЕНАМ (не по количествам)

```
diff appendix_baseline_failed_names.txt appendix_final_failed_names.txt  => пусто
```

Ни одного нового/исчезнувшего FAILED; collection errors сравнены отдельно
(единственный — pre-existing, идентичен в baseline и final).

### 8.4 B2-тесты v1–v7 на ИНТЕГРИРОВАННОМ Samsung-коде — 96 passed

| Файл | Тестов | Лог |
|---|---|---|
| test_b2_close_accounting.py (v1) | 20 | appendix_B2_V1_TESTS.txt |
| test_b2_terminal_metadata_recovery.py (v2) | 8 | appendix_B2_V2_TESTS.txt |
| test_b2_csv_recovery.py (v3) | 14 | appendix_B2_V3_TESTS.txt |
| test_b2_v4_accounting_consistency.py (v4) | 9 | appendix_B2_V4_TESTS.txt |
| test_b2_v5_identity_and_timestamp.py (v5) | 10 | appendix_B2_V5_TESTS.txt |
| test_b2_v6_timestamp_identity_close_reason.py (v6) | 16 | appendix_B2_V6_TESTS.txt |
| test_b2_v7_cursor_version_and_alt_timestamp.py (v7) | 19 | appendix_B2_V7_TESTS.txt |
| **ИТОГО** | **96 passed** | appendix_B2_TESTS_OUTPUT.txt |

Тесты взяты побайтово из v7-кандидата; адаптаций НЕ потребовалось — ни один
инвариант не ослаблен и не переписан (п.7 ТЗ). Тесты запускались именно на
интегрированном Samsung-коде (папка кандидата), не на исходном v7.

### 8.5 Негативная валидация критических B2-сценариев

Те же 96 тестов на НЕинтегрированном чистом Samsung: **93 failed, 3 passed**
— `appendix_NEGATIVE_VALIDATION.txt`. Тесты, ловящие дефекты B2, на старом
коде ПАДАЮТ (в т.ч. V7-C/D/E/F — некорректная версия трактовалась как legacy;
V7-H/I/J/K/L/M — чужой timestamp попадал в close_requested_at без проверки).
3 проходящих — инварианты-запреты («не перезаписывать», «не дублировать»,
«не применять повторно»), выполняемые на старом коде ВОКАЛЬНО из-за
отсутствия самого механизма; их положительная часть покрыта падающими
тестами. Ни один тест не подгонялся под результат.

### 8.6 Проверка импортов и совместимости остальных модулей

Smoke-импорт всех модулей кандидата (config, logger, execution, order_ledger,
risk_manager, screener, strategy, tinkoff_client, main) — успешен;
API-сверка вызываемых методов ExecutionMonitor/logger/main — все присутствуют.
Полный pytest Samsung-набора — FAILED-набор идентичен baseline (8.3).

## 9. Проверка diff на изменения вне scope (п.7 ТЗ)

FULL_DIFF.patch содержит ровно 10 секций: 3 изменённых производственных файла
+ 7 новых тест-файлов. Изменённые области строго B2: main.py —
`_try_resolve_absent_position`/`_finalize_position_closed` (docstring)/
`close_position`/`process_closing`/`_save_state`/`_load_state`/`reconcile`
(2 строки) + новые B2-функции; execution.py — `add_close_order`/
`apply_close_execution` (ветка повтора)/`register`/`register_recovery`
(по 1 строке)/`export_state`/`import_state`/`__init__` + новые B2-методы;
logger.py — `log_trade` (канонизация после append) + новые B2-функции.
СТРАТЕГИЯ, СИГНАЛЫ, ФИЛЬТРЫ, ПОРОГИ, BUY-цепочка, SL/TP, RiskManager,
screener, отправка заявок, B3, order_ledger.py, tinkoff_client.py, config.py —
НЕ ТРОНУТЫ. Публичные интерфейсы не переименовывались; формат state.json
обратно совместим; fail-closed режимы не ослаблены.

## 10. Ограничения

KNOWN_LIMITATIONS.md: pre-existing 74 FAILED + 1 collection error Samsung
(вне scope, идентичны baseline/final); заглушки SDK в песочнице (механизм
conftest самого Samsung, одинаков для baseline и final); семантика
requested_at (API не подтверждает время исполнения); состав папки (без
.git/__pycache__/.pytest_cache; runtime-файлы в исходном виде).

## 11. Подтверждения

* Исходный Samsung-репозиторий НЕ изменялся: работа велась в независимом
  клоне и рабочих копиях; в Samsung не сделано ни одного коммита/загрузки.
* Папки v1–v7 в temp не изменялись (использовались только на чтение для
  атрибуции исправлений и побайтового сравнения).
* Никаких торговых операций: брокер не вызывался, LIVE/sandbox ордера не
  отправлялись; тесты используют fake-клиентов (торговые методы fake'ов
  бросают AssertionError) и tmp_path; реальные state.json/CSV не
  редактировались.
* Секреты: пакет проверен сканированием на токены/ключи/пароли — не
  содержит (TEST_RESULTS.txt §6).
* ZIP `Samsung_B2_Integrated_V1_V7.zip` проверен: `unzip -t` OK, список
  файлов сверен, SHA256 зафиксирован в итоговом сообщении.

## Подтверждение

STRATEGY LOGIC: UNCHANGED

RESEARCH ONLY

NO THRESHOLD IS OPTIMIZED

NO FILTER IS INSTALLED

NO LIVE ORDERS

OOS SEALED / H4 EXECUTION NOT AUTHORIZED
