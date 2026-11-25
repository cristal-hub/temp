# MERGE_REPORT.md — samsung_merge_candidate_v5 (v2.3.8-stage1)
# B2 V5: CLOSE TIMESTAMP + RECOVERY IDENTITY VALIDATION

STRATEGY LOGIC: UNCHANGED
RESEARCH ONLY
NO THRESHOLD IS OPTIMIZED
NO FILTER IS INSTALLED
NO LIVE ORDERS
OOS SEALED / H4 EXECUTION NOT AUTHORIZED

---

## 1. Точная база v4

- Репозиторий: `cristal-hub/temp`, ветка `temp-merge-candidate-v4`,
  коммит **`a4c2491`** («samsung_merge_candidate_v4: B2 chronological
  cumulative + persistent late CSV recovery (v2.3.7-stage1) …»).
- Папка базы: `samsung_merge_candidate_v4/` внутри дерева temp
  (= копия в download). SHA256 базы:
  - `main.py` = `d50e66e7fcf95d0963b5d75b6039fe37f0b1d5dcba76fd95b1cd9a6d5ae535a0`
  - `execution.py` = `7e347f0c6d162aa2add55f2d0ec68af0358c3125bf5c86d0d200a54ce4a1d7eb`
  - `logger.py` = `df22ed916cb2eda10473cb78c2f93846d0be00c8a7ad5913a6bab8d9ee8ad4c5`
- Все исправления v1–v4 сохранены (см. §7). Папки
  `samsung_merge_candidate/`, `_v2/`, `_v3/`, `_v4/` в дереве temp
  не перезаписывались.
- Samsung-репозиторий: origin/main @ `051b10f` — READ-ONLY, не изменён
  (никаких коммитов/пушей; рабочие копии Samsung-коммита, использовавшиеся
  как тестовые стенды в предыдущих этапах, не являются изменением
  Samsung-источника).

## 2. Изменённые файлы (v5)

| Файл | Статус | SHA256 (v5) |
|---|---|---|
| `main.py` | изменён | `00d7fdfc813f4a98672790314e2a3e530e34471a73a40836220a93c7a471fe07` |
| `execution.py` | изменён | `2b4ca67f61e816457f66f4d75a3b25dcecc2672815637be0febc300bc219b7fd` |
| `logger.py` | без изменений | `df22ed916cb2eda10473cb78c2f93846d0be00c8a7ad5913a6bab8d9ee8ad4c5` |
| `test_b2_close_accounting.py` | без изменений | `9fa798bda539bbb1d8386f9836d64d3e9cf892c630a676257eced8078a347bc3` |
| `test_b2_csv_recovery.py` | без изменений | `8de760c885dc147c660767fe59b2ba0f7058173db78087059ae6eaa8e29a6e77` |
| `test_b2_terminal_metadata_recovery.py` | без изменений | `2f4ab482030e37808fcee4eca217f59b75dd27d084b542e8560fb717409be0f2` |
| `test_b2_v4_accounting_consistency.py` | без изменений | `6b75e5d501c6a653ca769ee17cd3cd99b33de49cb70f800737966ab0a387a93e` |
| `test_b2_v5_identity_and_timestamp.py` | НОВЫЙ | `1c793deb40920da3232f473ebaf0b447cdd00ac00befa5f236014a523816f3fc` |

Полный diff: `FULL_DIFF.patch` (только main.py/execution.py; logger.py
не менялся). Детали — `CHANGED_FILES.md`.

## 3. Defect A — потеря времени запроса закрытия при потерянном ответе SELL

### Причина (обнаружена в v4 main.py, `close_position()`)
1. Клиентский UUID создавался до отправки SELL.
2. `monitor.add_close_order()` сохранял `requested_at` (отдельный вызов
   `datetime.now()`) до сетевого вызова.
3. `pos.close_requested_at` устанавливался ТОЛЬКО после
   `post_market_order()` при `result.state != None` (ещё один отдельный
   вызов `datetime.now()`).
4. При `result.state is None` функция выходила, НЕ сохранив
   `close_requested_at`. Позиция позднее закрывалась по восстановленному
   отчёту, и CSV получал `exit_time = datetime.now()` (момент
   восстановления) — хронология cumulative P&L искажалась.

### Исправление
- Единый timestamp `close_requested_at` создаётся ОДИН раз до
  `post_market_order()`; то же значение передаётся в
  `monitor.add_close_order(...)` (→ `close_orders[request_id]["requested_at"]`)
  и сохраняется в `pos.close_requested_at` ПОСЛЕ успешной регистрации
  intent + per-order cursor'а, ДО сетевого вызова.
- При `result.state is None` timestamp сохранён; при получении ответа
  брокера НЕ перезаписывается (второй `datetime.now()` v4 удалён).
- Запись CSV (`process_closing`): `timestamp_utc` и `exit_time` — через
  новый helper `_close_request_ts(pos)`.
- Старые state.json: при отсутствии `close_requested_at`, но наличии
  собственного cursor'а close-заявки, время восстанавливается из
  `cursor["requested_at"]`; время текущего запуска НЕ подставляется
  вместо доступного timestamp из cursor'а (fallback до момента записи
  строки остался только для закрытий B3 без своей заявки и полностью
  легаси-позиций — как в v4, явно документировано).

### Семантика времени (важное уточнение ТЗ)
`requested_at` — время ЗАПРОСА SELL, а НЕ подтверждённое время
фактического исполнения. Оно используется как ЯВНО обозначенный
детерминированный proxy времени закрытия.

**Проверка T-Invest API:** используемый в контуре закрытия/восстановления
API-вызов `sandbox.get_sandbox_order_state` (через `tinkoff_client.py`)
возвращает OrderState со статусом, cumulative исполнением, ценой и
комиссией — подтверждённого времени исполнения сделки он НЕ содержит;
`get_order_trades`/operations API клиентом не вызываются. Достоверного
времени исполнения у текущей поверхности API нет, поэтому время
исполнения НЕ выдумывается: восстанавливается время запроса. Если в
будущем появится подтверждённое время исполнения (например, через
operations-отчёты), `_close_request_ts` — единственная точка замены
источника (fallback-цепочка расширяема).

### Хронология cumulative (совместимость с v4)
Авторитетное поле для хронологии — столбец CSV `exit_time` (fallback
`timestamp_utc` → `order_send_time` → `signal_time`, фиксированный якорь
`_CHRONO_UNKNOWN_TS`, tie-breaker `trade_id`+индекс строки — логика
`logger.py` не менялась). v5 меняет только источник значения: теперь это
сохранённое время запроса закрытия, которое переживает потерю ответа
брокера и перезапуск, поэтому хронологический пересчёт cumulative
опирается на фактический порядок отправки SELL, а не на моменты
восстановления/запуска.

## 4. Defect B — fail-closed проверка идентичности recovery-задачи

### Причина (обнаружена в v4)
`ExecutionMonitor.import_state()` восстанавливал снимок задачи через
`TrackedPosition.from_dict()`, но не проверял согласованность внешней
записи и снимка. В `process_closing()` внешний `rec["trade_id"]`
использовался для проверки завершения, а `_recover_late_csv_metadata()`
— `task_pos.trade_id` из снимка. При несовпадении задача могла обновить
одну строку CSV, а завершиться по состоянию другой.

### Исправление
- **Валидатор** `ExecutionMonitor.validate_recovery_identity(rec)`
  (execution.py) возвращает None или причину конфликта:
  `trade_id_mismatch`, `figi_mismatch`, `no_trade_id`, `no_figi`,
  `no_close_order_ref`, `cursor_trade_id_mismatch`, `cursor_figi_mismatch`,
  `cursor_side_mismatch`, `snapshot_unrestorable`, `no_snapshot`, `not_dict`.
  Проверяются: `rec.trade_id == snapshot.trade_id`; `rec.figi ==
  snapshot.figi`; наличие стабильного trade_id/FIGI; наличие СВОЕЙ
  close-заявки (`close_order_request_id`/`close_order_id`); соответствие
  идентификаторов заявки и per-order cursor'а (cursor[trade_id]/[figi]/
  [side] против сделки). Отсутствующий cursor (легаси-снимок) НЕ конфликт
  — штатный no_cursor-путь recovery (опрос невозможен, но подмены
  идентичности нет). trade_id / клиентский UUID / биржевой order ID —
  РАЗНЫЕ идентификаторы: смешение контролируется привязкой cursor'а
  (cursor создаётся `add_close_order` с данными СВОЕЙ сделки).
- **При импорте каждой задачи** (`_import_pending_recoveries`):
  противоречивая задача НЕ опрашивается, НЕ изменяет CSV, НЕ обновляет
  другую позицию, НЕ удаляется как «успешно завершённая» — ОСТАЁТСЯ в
  очереди с персистентным маркером `"conflict"` (причина сохраняется в
  state.json и читается обратно); диагностическое событие
  `CSV_RECOVERY_TASK_CONFLICT` (в `_load_state`, stage=import_state).
  Только структурно нечитаемые записи (не dict) отбрасываются —
  сохранять нечего (журнал fail-closed).
- **Дубликаты trade_id при импорте**: полные дубликаты (идентичная
  каноническая форма) — детерминированный дедуп до одной записи (первая,
  информация не теряется); конфликтующие (разные снимки или разные
  close-ID при одном trade_id) — НЕ выбирается ни одна произвольно:
  ОБЕ остаются с маркером `duplicate_trade_id_conflicting`.
- **Перед каждым recovery-циклом** (main.py `process_closing`): валидатор
  запускается заново; учитывается и ранее установленный маркер
  (заблокированная задача не «разблокируется» повторной проверкой).
  Снимок, невосстановимый в памяти, больше НЕ удаляется — остаётся с
  маркером `snapshot_unrestorable` (событие с reason/detail).
- **Проверка CSV-строки перед обновлением** (main.py
  `_recover_late_csv_metadata`, шаг 1а): `row.figi == pos.figi` и
  `row.order_id` принадлежит close-заявке снимка; противоречие —
  обновление ЗАПРЕЩЕНО, чужая строка не изменяется, события
  `CSV_LATE_METADATA_CONFLICT` с причинами `row_figi_mismatch` /
  `row_order_id_mismatch`.

### Решение о хранении recovery-задач (изменение формата state.json)
Формат записей `pending_csv_recoveries` РАСШИРЕН необязательным ключом
`"conflict"` (строка-причина или отсутствие ключа). Миграция/совместимость:
- старый state.json без ключа → задачи без маркера, поведение как в v4;
- новый state.json читается старой версией: неизвестный ключ игнорируется
  (`rec.get(...)`-доступ), задачи остаются работоспособными;
- повреждённые записи: не dict → отбрасываются с журналом; противоречивая
  идентичность → сохраняется с маркером (fail-closed сохранение улики,
  вместо удаления в v4); ревалидация при каждом импорте идемпотентна —
  исправленная запись снова становится пригодной (маркер перезаписывается
  актуальным результатом проверки, отсутствие конфликта → маркер снят).

## 5. Тесты

### 5.1 Baseline (до изменений, код v4)
Полный pytest (`python3 -m pytest -p no:cacheprovider
--continue-on-collection-errors -q`), окружение = полная Samsung-основанная
дерево с кодом v4 в корне:
**74 failed, 617 passed, 1 error** (лог: `appendix_BASELINE_FULL_PYTEST.txt`).
FAILED/ERROR-набор по ИМЕНАМ совпадает с финальным набором v4
(74 FAILED + collection error корневого `test_execution.py` — pre-existing,
не связан с B2).

### 5.2 Final (после изменений, код v5)
**74 failed, 627 passed, 1 error** (лог: `appendix_FINAL_FULL_PYTEST.txt`).
+10 passed = новые тесты V5. Сравнение ПО КОНКРЕТНЫМ ИМЕНАМ FAILED и
ERROR/collection errors (не по количеству):
`diff baseline_names.txt final_failed_names.txt` → **пусто** (наборы
идентичны). Ни одного нового FAILED/ERROR; ERROR/collection error —
тот же единственный pre-existing `test_execution.py`.

### 5.3 Прежние B2-тесты (51)
`test_b2_close_accounting.py` + `test_b2_csv_recovery.py` +
`test_b2_terminal_metadata_recovery.py` + `test_b2_v4_accounting_consistency.py`
→ **51 passed** без правок тестов (лог: `appendix_B2_TESTS_OUTPUT.txt`).
Сохранность v4: chronological cumulative P&L, детерминированный
tie-breaker, late commission/price recovery, persistent pending recovery,
восстановление после перезапуска, отсутствие cross-contamination,
fail-closed при противоречиях, атомарная запись CSV, отсутствие
повторного применения лотов, отсутствие CSV-дублей — подтверждены тестами.

### 5.4 Новые тесты V5 (`test_b2_v5_identity_and_timestamp.py`)
**10 passed** (лог: `appendix_V5_TESTS_OUTPUT.txt`):
- V5-A: SELL отправлена, `result.state=None`, позднее закрытие по
  восстановленному отчёту → CSV `exit_time` = первоначальное время
  запроса (09:05), НЕ время восстановления (10:20); timestamp в позиции
  и в cursor'е — одно и то же значение.
- V5-B: два закрытия; первая заявка отправлена раньше (ответ потерян),
  вторая закрыта и записана раньше; после восстановления cumulative
  соответствует сохранённым timestamp запросов (хронология 09:05 → 10:00
  при порядке строк файла [2, 1] и времени восстановления 10:20).
- V5-C: перезапуск между потерянным ответом и восстановлением —
  timestamp сохраняется в state.json (прямая проверка JSON) и не меняется;
  после рестарта exit_time = время запроса.
- V5-D: старый state.json без `close_requested_at`, но с
  `close_orders[request_id]["requested_at"]` — время восстанавливается из
  cursor'а (09:05), время текущего запуска (10:10) НЕ подставляется.
- V5-E: `rec.trade_id != snapshot.trade_id` → импорт помечает конфликт,
  брокер НЕ опрашивается (0 вызовов), CSV не изменён, задача не удалена;
  событие `CSV_RECOVERY_TASK_CONFLICT` (reason=trade_id_mismatch).
- V5-F: FIGI внешней задачи != FIGI снимка → figi_mismatch, fail-closed
  (аналогичные проверки).
- V5-G: cursor содержит другой trade_id (полный fail-closed цикл через
  перезапуск) / другой FIGI (валидатор) → cursor_trade_id_mismatch /
  cursor_figi_mismatch.
- V5-H: две задачи с одним trade_id и разными close order IDs → ОБЕ с
  маркером `duplicate_trade_id_conflicting`, никакого произвольного
  выбора, 0 вызовов брокера, CSV не изменён.
- V5-I: CSV-строка с противоречащим FIGI (вариант 1) или order_id
  (вариант 2) → обновление запрещено, чужая строка не изменяется,
  события `row_figi_mismatch`/`row_order_id_mismatch`; контроль:
  согласованная строка обновляется штатно, задача завершается.
- V5-J: корректная задача после перезапуска работает штатно (без ложной
  блокировки) — восстановление в СВОЮ строку, задача завершена и удалена.

### 5.5 Негативная валидация (тесты V5 на коде v4 ДО исправлений)
`appendix_NEGATIVE_VALIDATION_OLD_CODE.txt`: **9 failed, 1 passed** —
тесты V5-A..I падают на v4-коде (ловят дефекты); единственный прошедший
V5-J — регрессионный guard «валидная задача не должна блокироваться».

## 6. Обнаруженная сторонняя проблема (ТОЛЬКО описана, НЕ исправлена)

`main.py`, `_try_resolve_absent_position()` (пакет В2), строка
`close_reason = reason_text[len("close:"):].split()[0].upper() or close_reason`:
если запись реестра/синтезированная запись имеет `reason == "close:"`
(пустая причина закрытия, например `close_reason` позиции = None), вызов
`.split()[0]` поднимает `IndexError`. Путь достижим при UNCERTAIN-позиции,
отсутствующей у брокера, с собственной close-заявкой и пустым
`close_reason` (обнаружено при построении тестового сценария V5-B через
reconcile). Проблема существует в v1–v4 и не связана с изменениями v5;
исправление вне рамок ТЗ (пакет В2/reconcile не модифицируется) —
требует отдельного решения владельца. В тестах V5 путь не задействован
(отчёт подаётся на клиент монитора, позиция закрывается штатным
`resolve_closing` до reconcile).

## 7. Сохранность v4 (все пункты подтверждены)

- chronological cumulative P&L (V4-A/B, V5-B);
- детерминированный tie-breaker (V4-C);
- late commission recovery / late execution price recovery (v3-тесты);
- persistent pending recovery (V4-E/F/G, V5-J);
- восстановление после перезапуска (V4-G, V5-C/J);
- отсутствие cross-contamination между сделками одного FIGI (V4-F, V5-H);
- fail-closed при противоречиях (V4-H, V5-E..I);
- атомарная запись CSV (V4-I);
- отсутствие повторного применения лотов (v3-тесты, per-order cursor);
- отсутствие CSV-дублей (v3/V4/V5-тесты);
- requested_lots/executed_lots сохраняются (v1-тесты);
- пер-order cursor, ledger, идемпотентность — без изменений (v1-тесты).

## 8. Известные ограничения

1. `exit_time` для закрытий без собственной close-заявки (B3) и
   полностью легаси-позиций (нет ни `close_requested_at`, ни cursor'а) —
   момент записи строки (единственная доступная оценка; поведение v4
   сохранено, явно документировано).
2. `requested_at` — proxy времени ЗАПРОСА, не фактического исполнения
   (используемый API-контур времени исполнения не подтверждает; см. §3).
3. Конфликтные recovery-задачи остаются в очереди навсегда (с маркером
   и диагностикой) — разрешение только оператором; это осознанный
   fail-closed компромисс против «тихой» потери противоречивой задачи.
4. Полные (идентичные) дубликаты задач дедуплицируются до первой записи —
   записи идентичны, потери информации нет.
5. Сторонняя проблема `IndexError` при `reason == "close:"` (§6) —
   не исправлена (вне рамок ТЗ).

## 9. Артефакты

- `main.py`, `execution.py`, `logger.py` — код v5;
- `test_b2_close_accounting.py`, `test_b2_csv_recovery.py`,
  `test_b2_terminal_metadata_recovery.py`,
  `test_b2_v4_accounting_consistency.py` — прежние 51 B2-тест (без правок);
- `test_b2_v5_identity_and_timestamp.py` — новые тесты V5-A..J;
- `CHANGED_FILES.md` — пофайловые изменения и SHA256;
- `FULL_DIFF.patch` — полный diff v4→v5 (main.py, execution.py);
- `TEST_RESULTS.txt` — сводка результатов;
- `SHA256SUMS.txt` — контрольные суммы всех артефактов;
- `appendix_BASELINE_FULL_PYTEST.txt`, `appendix_FINAL_FULL_PYTEST.txt` —
  полные логи baseline/final;
- `appendix_B2_TESTS_OUTPUT.txt`, `appendix_V5_TESTS_OUTPUT.txt` —
  отдельные логи 51 B2 и 10 V5 тестов;
- `appendix_NEGATIVE_VALIDATION_OLD_CODE.txt` — V5-тесты на коде v4.

Внесение в Samsung НЕ выполнялось. Сначала независимый аудит v5.
