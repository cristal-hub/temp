# FIXES.md — описание каждого исправления

Мандаты: `RESEARCH ONLY` · `NO LIVE ORDERS` · `STRATEGY LOGIC: UNCHANGED` ·
`NO THRESHOLD IS OPTIMIZED` · `NO FILTER IS INSTALLED`.

---

## FIX-1 — атомарность `_enrich_buy_entry_metadata()` (main.py)

### Дефект (подтверждён предыдущим аудитом и настоящей проверкой кода)

Функция изменяла поля объекта позиции по мере валидации и возвращала True,
не проверяя результат `_save_state_checked()`:

1. **Частичная мутация:** при валидной комиссии и невалидном `exec_price`
   комиссия уже записывалась в объект позиции, затем `float(exec_price)`
   бросал исключение → `return False` — объект оставался изменённым при
   формальном отказе операции.
2. **Непроверяемое сохранение:** `_save_state_checked(monitor, rm)` вызывался
   без контроля результата → функция возвращала True даже при незаписанном
   state.json; вызывающий код получал ложное подтверждение; последующая
   запись реестра могла закрепить метаданные при устаревшем state.json
   (на перезапуске позиция перезагружалась БЕЗ комиссии — а
   `entry_actual_commission` участвует в расчёте net P&L).

### Реализация (validate → stage → commit → checked save)

Файл `candidate/main.py`, функция `_enrich_buy_entry_metadata` (один hunk;
прежние правила заполнения только None-полей, семантика нуля, запрет
перезаписи известных значений, неизменность identity/FIGI/side/order_id и
B2 close accounting — сохранены; сигнатура и публичный интерфейс не менялись):

1. **ВАЛИДАЦИЯ** (до любого изменения объекта): оба значения
   (`entry_commission`, `exec_price`) конвертируются в float локально;
   неинтерпретируемое значение → `return False` целиком (частичная мутация
   невозможна).
2. **ПОДГОТОВКА** (`staged`): новые значения формируются локально; в staged
   попадают только поля, требующие обогащения (прежнее значение None).
   Отрицательная комиссия (не валидное значение) игнорируется как прежде,
   при этом валидная цена по-прежнему обогащается (семантика сохранена).
3. **ПРИМЕНЕНИЕ** одним блоком с сохранением прежних значений в `previous`.
4. **СОХРАНЕНИЕ С КОНТРОЛЕМ:** `if not _save_state_checked(...)` →
5. **FAIL-CLOSED:** откат применённых значений (память == несохранённому
   state.json), `logging.error`, диагностическое событие
   `BUY_ENTRY_METADATA_SAVE_FAILED`, `return False`. Событие-подтверждение
   `BUY_ENTRY_METADATA_ENRICHED` пишется ТОЛЬКО после подтверждённого
   сохранения (в журнале не появляется ложное свидетельство).
   Дублирование архитектурной защиты сохранено: `_save_state_checked`
   выставляет `state_save_failed` (блокировка новых входов).

### Цепочка вызовов и обоснование отсутствия изменений вызывающего кода

Все места вызова (проверены по всему дереву, `grep`):
1. `main.register_executed_buy`, ветка `evidence_applied` (закрытая позиция,
   повторная регистрация запрещена) — после вызова `return None`; запись
   реестра после обогащения отсутствует.
2. `main.register_executed_buy`, ветка `evidence_closed_entry` — после
   вызова `return None`; `record_uncertain` (при позднем росте) выполняется
   ДО обогащения.
3. `main.register_executed_buy`, ветка активной позиции — возвращаемое
   значение не используется; последующие подтверждения реестра в этой ветке
   уже gated собственным `_save_state_checked` (`state_saved_after_apply`,
   партия P0-5: при несохранённом state пишется UNCERTAIN, а не
   терминальный статус).

Ни один вызов не читал возвращаемое значение и не строил на нём решений →
изменение семантики возврата (True только при подтверждённой записи)
не требует правок вызывающего кода. Минимальный объём изменения = одна
функция. Интеграционный тест цепочки: `test_fix1_g_…` (поздний отчёт через
`register_executed_buy` → обогащение → подтверждённая запись в state.json).

### Обязательные тесты FIX-1 (ТЗ §3) — все реализованы в
`candidate/test_corrective_audit_v2.py`

| Тест ТЗ | Тест | Проверяет |
|---|---|---|
| A. Ошибка сохранения | `test_fix1_a_save_failure_no_false_confirmation` | save=False → функция False; значения откатены; ENRICHED-события нет; SAVE_FAILED-событие есть; реестр не изменён; после «восстановления» хранилища state.json подтверждает прежние (None) значения |
| B. Некорректный exec_price | `test_fix1_b_invalid_exec_price_no_partial_mutation` | валидная комиссия + «мусор»/объект в exec_price → False, оба поля None (частичной мутации нет) |
| C. Некорректная комиссия | `test_fix1_c_invalid_commission_no_mutation` | «мусор»/объект в комиссии (в т.ч. при валидной цене) → False, поля не изменены |
| D. Нормальное обогащение | `test_fix1_d_normal_enrichment_and_idempotent_repeat` | оба поля сохранены в state.json; повторный вызов — False, без дублей событий, без перезаписи противоречивыми значениями |
| E. Нулевая комиссия | `test_fix1_e_zero_commission_is_confirmed_value` | 0.0 сохраняется именно как подтверждённый ноль (в памяти, в state.json, в событии); повтор не трактует его как отсутствие; None не затирает |
| F. Повтор после ошибки сохранения | `test_fix1_f_retry_after_save_failure_no_double_apply` | первая попытка (save=False) — False/откат/без подтверждения; вторая после восстановления — True/одно применение/одно подтверждение |
| (доп.) C2 — фиксация семантики | `test_fix1_c2_negative_commission_ignored_price_enriched` | отрицательная комиссия игнорируется (не подменяется), цена обогащается — прежнее поведение |
| (доп.) G — цепочка вызовов | `test_fix1_g_caller_chain_register_return_uses_checked_save` | интеграция через register_executed_buy |

**Негативная валидация:** прогон нового файла на неизменённом кандидате
(BASELINE) — `3 failed, 15 passed`: падают именно A, B, F (fail-режимы,
которые старый код не обеспечивал) — `evidence/negative_validation_old_code.txt`.
Тесты D/E/C/C2 и все SELL-тесты проходят на обоих кодах — подтверждают
сохранение прежней семантики.

---

## FIX-2 — 12 P0-тестов и FakeClient

### Диагностика (все 12 — поимённо, трейсбеки в `evidence/p0_12_failures_on_pristine_candidate.log`)

Прогон на НЕИЗМЕННОМ кандидате: `12 failed, 58 passed` на трёх корневых
P0-файлах (воспроизведение заявленной картины ТЗ).

| # | Тест | Место ошибки | Причина |
|---|---|---|---|
| 1–11 | `test_p0_batch2_late_execution.py`: n1_no_premotion, n1_promotion, n4_late_growth, integration_trading_cycle, p03_1, p03_2, p04_reconcile, p05_1…p05_4 | main.py:708 / 4624 / 5299 (в вызовах `get_sandbox_order_state(…, order_id_type=…)`, `cancel_order(…, order_id_type=…)`) | `TypeError: FakeClient.get_sandbox_order_state() got an unexpected keyword argument 'order_id_type'` — тесты импортируют FakeClient из `tests/test_p0_defect_fixes.py`, чья заглушка не обновлена под контракт ЭТАП 5Б (корневая копия `test_p0_defect_fixes.py` обновлена, tests/-копия — нет) |
| 12 | `test_p0_sell_id_fixes.py::test_16_request_lookup_unavailable_fails_closed` | test_p0_sell_id_fixes.py:699 | `AttributeError: module 'tinkoff_client' has no attribute 'Order_id_type'` — тест патчит несуществующий атрибут; production импортирует enum как `OrderIdType` (from t_tech.invest.schemas) |

**Подтверждение гипотезы ТЗ:** да, для 11 из 12 причина — устаревшая
сигнатура тестовой заглушки; для 1 из 12 — ошибочное имя атрибута в тесте
(родственная ошибка тестовой инфраструктуры, но НЕ сигнатура заглушки).
Production-контракт корректен (fail-closed при недоступном enum,
документирован в tinkoff_client.py) — production НЕ менялся.

### Исправления (только тестовая инфраструктура)

1. `tests/test_p0_defect_fixes.py`: `get_sandbox_order_state(self, order_id,
   order_id_type=None)` и `cancel_order(self, order_id, order_id_type=None)`
   — ЯВНЫЕ именованные параметры (не `**kwargs`), семантика поиска по
   order_id сохранена (зеркально корневой копии).
2. `test_p0_sell_id_fixes.py`: `Order_id_type` → `OrderIdType` (3 места:
   чтение, подмена, восстановление в finally). Смысл проверки 16a (fail-closed
   без сетевого вызова при недоступном SDK-enum) полностью сохранён.

**Результат:** 11 из 12 проходят (P0-файлы корня: 69 passed / 1 failed).
12-й — см. NOT VERIFIED ниже.

### NOT VERIFIED: `test_integration_trading_cycle_partial_cancel_recovery_open_late_lots`

После обновления заглушки тест ВЫПОЛНЯЕТСЯ и проходит 8 из 9 утверждений
(RECOVERY, идемпотентность, промоция, рост 2→5 к позиции, неизменность
entry_price/SL/TP, отсутствие дубликатов и новых BUY). Последнее
утверждение (`rec["status"] == "CANCELLED"`) фиксирует производственный
конфликт: первый терминальный отчёт заявки записал в реестр
`avg_exec_price=0.0` (нулевая цена «нет данных», не нормализованная BUY-путём),
metadata-guard реестра (FIX-1 кандидата в order_ledger.append) корректно
распознал изменение 0.0→100.0 в повторном отчёте терминальной заявки и
перевёл запись в UNCERTAIN. Полное досье с трассировкой и вариантами
исправления: `evidence/not_verified_integration_evidence.md`.
Production-код не исправлялся (ТЗ §4 п.7). Статус теста: **NOT VERIFIED
(блокирован производственным контрактом)**.

Каскад обновления заглушки (зафиксирован и объяснён): 26 ранее падавших
тестов tests/-копий получили возможность выполняться; 24 проходят;
2 вскрывают предсуществующий «дрейф копий» (tests/-копии устаревших
версий тестов, чьи корневые канонические версии обновлялись проектом:
`tests/test_p0_batch2::test_n3_…`, `tests/test_p0_defect_fixes::test_defect4_…`)
— утверждения этих копий НЕ изменялись.

---

## FIX-3-tests — регрессия нулевой комиссии SELL (`_extract_commission`)

Изменение FIX-3 кандидата сделало `0.0` достоверным значением комиссии для
BUY и SELL. ТЗ требует 7 обязательных сценариев — все реализованы
(`candidate/test_corrective_audit_v2.py`, инфраструктура B2 v4 переиспользована):

| Сценарий ТЗ §5 | Тест | Результат |
|---|---|---|
| 1. SELL с подтверждённой 0.0 | `test_sellzc_1_confirmed_zero_commission_stored` | cursor и позиция хранят 0.0; CSV: `actual_commission_rub="0.00"` (не пустая строка), `commission_source="mixed"`, net P&L с фактическим нулём |
| 2. SELL с положительной комиссией | `test_sellzc_2_positive_commission_stored` | 2.50 в CSV, net P&L корректен |
| 3. SELL с отсутствующей комиссией | `test_sellzc_3_missing_commission_stays_none` | None остаётся None (не превращается в 0.0); CSV: пустая `actual_commission_rub`, выходная — модельная |
| 4. Повторный отчёт с нулевой комиссией | `test_sellzc_4_repeat_zero_commission_report_idempotent` | повтор терминального отчёта (0.0 vs 0.0) — без конфликта, лоты не применяются повторно, значения стабильны |
| 5. Позднее получение после отсутствия | `test_sellzc_5_late_zero_commission_after_absence_enriched_once` | обогащение None→0.0 ровно один раз; CSV-строка обновляется атомарно (дублей нет); net/cumulative пересчитаны; повторный проход — файл байт-в-байт неизменен |
| 6. Нет бесконечного polling | `test_sellzc_6_zero_commission_no_infinite_repoll` | неполная строка опрашивается; после записи «0.00» опросы прекращаются |
| 7. Комиссия не применяется дважды | `test_sellzc_7_commission_not_applied_twice_pnl_stable` | 3 повторных цикла: net P&L и cumulative стабильны, строк одна |
| (доп.) семантика BUY/SELL | `test_sellzc_8_extract_commission_zero_none_semantics` | единая функция: 0.0→0.0, None→None; BUY и SELL используют один и тот же метод |

Согласованность с B2 close accounting: идемпотентность повторов —
`_report_value_conflict(0.0, 0.0) == False` (проверено тестом 4); правило
P&L не менялось (тесты 1/2/5 фиксируют текущую формулу).

---

## §6 — проверка `or ""` на числовых метаданных

Проверены ВСЕ вхождения `or ""` в main.py/execution.py/order_ledger.py
(≈60 мест) на предмет «0.0 → пустая строка»:

* **Чтение CSV (`old_row/rec_row` из `find_trade_row` → csv.DictReader):**
  все значения — СТРОКИ. Реальный ноль пишется в CSV как «0.00»
  (`f"{entry_commission:.2f}"` в путях записи main.py:2493/2974), «пусто» —
  только при отсутствии подтверждённого значения (PRICE_UNKNOWN-ветка).
  Поэтому `str(row.get("entry_commission_rub") or "")` для нуля даёт
  «0.00» (truthy) — ноль НЕ теряется. Проверено местами:
  needs_poll (main.py:2649-2659), завершение recovery-задач (3261-3262).
* **Пути записи:** `entry_commission_str = f"{entry_commission:.2f}"`
  (подтверждённая цена) vs `""` (PRICE_UNKNOWN) — семантика ноль/отсутствие
  сохранена; `actual_commission_str` — то же.
* **Остальные `or ""`** — строковые поля (order_id, figi, trade_id, status,
  reason, timestamps, error_note) или ID-строки: ноль не имеет смысла.
* **execution.py:323-324** `d.get("sl_price") or 0.0` — нулевой SL
  семантически эквивалентен «не задан» (валидные цены > 0) — не дефект.

**Вывод: подтверждённых дефектов нет; массовый рефакторинг не проводился
(по ТЗ).** Добавлены 2 обязательных регрессионных теста:
`test_needspoll_zero_entry_commission_no_repoll` (нулевая entry-комиссия в
строке «0.00» → без повторного опроса) и
`test_needspoll_pending_task_zero_commission_completes` (строка с «0.00»
завершает recovery-задачу без опроса брокера).

---

## Сводка изменённых/добавленных файлов

| Файл | Тип | Изменение | Причина | Дефект | Исправленное поведение | Подтверждающий тест |
|---|---|---|---|---|---|---|
| candidate/main.py | production | функция `_enrich_buy_entry_metadata` (1 hunk) | FIX-1 ТЗ §3 | частичная мутация + непроверяемый результат сохранения (ложный True) | validate→stage→commit→checked save; откат и False при ошибке записи; ENRICHED-событие только после подтверждённого сохранения | A–F/G (18/18), негативная валидация |
| candidate/tests/test_p0_defect_fixes.py | тест-инфра | 2 сигнатуры заглушки + комментарии | FIX-2 ТЗ §4 | заглушка без `order_id_type` (контракт ЭТАП 5Б) | заглушка принимает явный именованный параметр; семантика поиска сохранена | 11 P0-тестов корня + каскад tests/ |
| candidate/test_p0_sell_id_fixes.py | тест-инфра | имя атрибута enum (3 места) | FIX-2 ТЗ §4 | тест патчил несуществующий `tinkoff_client.Order_id_type` | патч фактического `OrderIdType`; смысл проверки сохранён | test_16 |
| candidate/test_corrective_audit_v2.py | тесты | НОВЫЙ файл, 18 тестов | FIX-1 тесты A–F; FIX-3-tests §5; §6 needs_poll | — | — | сам файл |

Никакие другие файлы не изменялись. Ни один тест не удалён, ни одно
утверждение не ослаблено. Стратегия/сигналы/фильтры/риски/SL/TP — без
изменений (SHA256 execution.py/logger.py/order_ledger.py/config.py/
strategy.py/risk_manager.py/screener.py/tinkoff_client.py — без изменений).
