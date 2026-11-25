# AUDIT REPORT — BUY ACCOUNTING (ЭТАП 1)

Проект: Tsclp_v2.1_volatile_Samsung. Каталог аудита: `temp/samsung_BUY_accounting_audit_v1/`.
База: Samsung `051b10f095d45c053492ca333449a9a9f518f33f` + кандидат B2 v1–v7
(`temp/samsung_B2_integrated_v1_v7`, сохранён без изменений).

```
STRATEGY LOGIC: UNCHANGED
RESEARCH ONLY
NO THRESHOLD IS OPTIMIZED
NO FILTER IS INSTALLED
NO LIVE ORDERS
OOS SEALED / H4 EXECUTION NOT AUTHORIZED
```

Все ссылки на строки — файлы каталога аудита (код кандидата B2 + BUY-фиксы v1).

---

## 1. Полный путь BUY (направление A ТЗ)

| # | Шаг | Функция / файл | Условия перехода |
|---|---|---|---|
| 1 | Сигнал BUY | `main.trading_cycle` → `sm.get_signal(df, price)` (main.py, раздел «7. Входы») | только при `reconcile_done`, отсутствии позиции по FIGI, `ledger.figi_blocks_buy(figi)==False`, отсутствии незавершённых заявок без FIGI |
| 2 | Размер позиции | `rm.calculate_position_size` | `lots > 0`, иначе пропуск |
| 3 | Идентификаторы | `trade_id = uuid4().hex[:12]`, `order_id = str(uuid4())` | order_id генерируется ДО записи SIGNAL и до сетевого вызова (клиентский UUID = ключ идемпотентности) |
| 4 | SIGNAL в журнал | `research_logger.log_event("SIGNAL", …)` | append-only, `research_events.jsonl` |
| 5 | INTENT в реестр ДО отправки | `ledger.record_intent` (order_ledger.py) | fail-closed: запись не удалась — заявка НЕ отправляется; повторный INTENT с тем же order_id помечает реестр недостоверным |
| 6 | Отправка брокеру | `client.post_market_order(figi, lots, BUY, order_id=order_id)` | `order_id` — клиентский UUID |
| 7 | Ответ получен | `result.state` | `state is None` → `ledger.record_uncertain` + `client.uncertain_state=True` (BUY_UNKNOWN); повторная отправка запрещена |
| 8 | SENT + биржевой ID | `ledger.record_sent(…, status_hint, executed_lots, exchange_order_id, order_request_id=order_id)` | FILL без `executed_lots>0` → record_uncertain |
| 9 | Ветвление по статусу | `trading_cycle`: PARTIALLYFILL / не-FILL / FILL | PARTIALLYFILL → отмена остатка по REQUEST + регистрация исполненного; не-FILL → запрос фактического состояния (`get_sandbox_order_state(order_id, type=REQUEST)`) → исполнено>0 → регистрация; FILL → регистрация (state недоступен → регистрация по post-ответу) |
| 10 | Исполненные лоты/цена/комиссия | `le = int(state.lots_executed)`; `ExecutionMonitor._extract_price(state, le, lot)`; `_extract_commission(state)` (execution.py) | FILL при `le<=0` → противоречие → UNCERTAIN |
| 11 | Единая точка регистрации | `register_executed_buy(client, monitor, rm, ledger, …)` (main.py) | все источники (post-ветки, poll, startup) сходятся сюда |
| 12 | Запись в order ledger | `ledger.record_status(order_id, ledger_status, …, reason="позиция зарегистрирована")` | пишется ТОЛЬКО после успешного `_save_state_checked` |
| 13 | Создание/обновление позиции | `monitor.register(...)` → OPEN при цене и SL/TP; иначе `monitor.register_recovery(...)` → RECOVERY (exec_price None / нет df / ошибка расчёта SL/TP / сбой register) | RECOVERY не закрывается автоматически; промоция — `promote_recovery_positions` |
| 14 | Сохранение state.json | `_save_state_checked` → `_save_state` (атомарно: tmp + `os.replace`) | при ошибке: `state_save_failed=True`, новые входы блокированы, подтверждение в реестр НЕ пишется |
| 15 | Реестр активных позиций | `monitor.positions[figi]` (одна запись на FIGI) + `closed_entry_order_ids` (персистентен) | перезапись активной позиции запрещена |
| 16 | Последующий контроль | `poll_open_orders` (каждый цикл) | опрос по REQUEST для заявок робота; терминальные с остатком остаются доступными сверке (`_pending_residual_execution`) |
| 17 | Сверка с брокером | `reconcile` + `startup_recovery` (3 прохода) + `process_closing` | см. раздел 7 |

### 1.1 Где возможна ситуация «BUY исполнен, ledger считает учтённым, позиция не создана»

1. **`record_sent` (шаг 8) → крах до `register_executed_buy`.** Ledger содержит
   FILL с `executed_lots`, позиции нет. Покрытие: `startup_recovery`, проход 1.5
   — терминальные FILL-заявки с `executed_lots>0` без маркера «позиция
   зарегистрирована» доводятся до регистрации. Маркеры-причины защищают от
   повторного применения.
2. **Guard «воскрешения»**: повторная регистрация подавляется ТОЛЬКО при
   положительном доказательстве применения (`entry_order_id == order_id` +
   `entry_applied_lots >= executed_lots`, либо `order_id in
   closed_entry_order_ids`). Отсутствие позиции доказательством НЕ является.
3. **Активная позиция уже есть** — идемпотентность (`apply_late_entry_lots` /
   `record_recovery_entry_lots`): дельта только сверх учтённого.
4. **Окно между `monitor.register()` в памяти и `_save_state_checked`** —
   подтверждение не пишется до успешного сохранения state → при перезапуске
   проход 1.5 повторит регистрацию идемпотентно. Окно закрыто.
5. **Порядок state ↔ ledger**: дельта сначала в state, затем подтверждение в
   ledger. Разрыв при исключении безопасен.

**Вывод A:** в текущем кандидате сценарий «ledger считает учтённым, позиция
не создана и не восстановится» не найден. Доказательство: тесты 05, 06, 14, 18,
WUSH.

### 1.2 Порядок записи ledger ↔ state

INTENT — до сетевого вызова (fail-closed); SENT — после ответа; state.json —
при регистрации позиции, ДО подтверждения в ledger; «позиция
зарегистрирована» — только после успешного сохранения state. При
`_save_state_checked=False`: подтверждение не пишется, `STATE_SAVE_FAILED`,
новые входы блокированы, notify не заявляет надёжного сохранения (тест ТЗ-16).

---

## 2. Order identity и FIGI (направление B)

- Ключ реестра — клиентский UUID (`record_intent` фиксирует
  `order_request_id == order_id`); биржевой ID — отдельно
  (`exchange_order_id`); опрос строго по REQUEST для записей робота
  (`_poll_ledger_order_state`).
- Две заявки одного FIGI: OPEN — `order_id != entry_order_id` → неопределённость
  (лоты не применяются); RECOVERY — привязка только при совпадении trade_id.
  Тест ТЗ-12.
- Два отчёта с одинаковым order_id: до фиксов реестр молча принимал
  противоречивые identity/метаданные (дефект D1/D2). После FIX-1: противоречие
  FIGI/стороны → UNCERTAIN с сохранением подлинных значений; ранее
  подтверждённая цена не затирается отсутствием данных; противоречивая цена/
  комиссия в повторе ТЕРМИНАЛЬНОЙ заявки → UNCERTAIN (между нетерминальными —
  средняя цена легитимно уточняется). Тесты 22, 23, ТЗ-11.
- Запрошенное vs исполненное: `append` не даёт cumulative убывать или
  превысить requested; FILL при `executed < requested` остаётся доступен
  опросу (residual).
- Неизвестный/противоречивый статус: не теряется; FILL без лотов → UNCERTAIN;
  сторона None — опрос без авторегистрации.

**Доказанные дефекты B**: D1 (identity-перезапись), D2 (затирание цены) —
исправлены FIX-1.

---

## 3. Partial BUY и повторная обработка (направление C)

- PARTIALLYFILL: исполненное регистрируется ДО отмены остатка; в позицию идёт
  только `le` (тест ТЗ-3).
- Несколько частичных: рост cumulative через `apply_late_entry_lots` (OPEN) /
  `record_recovery_entry_lots` (RECOVERY, `already_seen_lots` из реестра) —
  только реально новые лоты (тест ТЗ-4: 3 → 7 → 7 → 10).
- Повтор отчёта идемпотентен (тесты ТЗ-2, ТЗ-18).
- Терминальный отчёт после частичного: CANCELLED/EXPIRED с `le>0` регистрируют
  исполненную часть, статус заявки сохраняется отдельно; поздний рост после
  терминала — неопределённость/сверка, не авторегистрация.
- Перезапуск между частичными: заявка остаётся в `open_orders()` → poll/
  startup продолжают (тесты ТЗ-5/6/18).

---

## 4. Persistence и restart recovery (направление D)

**Файлы и роли**: `state.json` — источник истины позиций (атомарная запись);
`order_ledger.jsonl` — источник истины заявок (append-only, fsync, повреждение
→ `_mark_unreliable` → BUY запрещены, журнал не обрезается автоматически);
активные позиции — `monitor.positions`; `research_events.jsonl` /
`research_trades.csv` — журналы наблюдений/сделок (не источник истины учёта).

| Сценарий | Поведение | Тест |
|---|---|---|
| Крах после подтверждения BUY до сохранения позиции | startup pass 1.5 доводит до регистрации | ТЗ-5, WUSH |
| Ledger сохранён, state нет | позиция восстанавливается из отчёта заявки; state сохраняется немедленно | ТЗ-6 |
| State сохранён, ledger нет | позиция жива из state; дублей нет | ТЗ-7 |
| Повторный запуск | идемпотентно (маркеры-причины, guard-и) | ТЗ-18 |
| Повторная сверка после восстановления | reconcile не дублирует | ТЗ-14/15 |
| Активная позиция + повторный отчёт | идемпотентность | ТЗ-2 |
| Позиция у брокера без локального учёта | адопция RECOVERY ровно один раз | ТЗ-14 |

Дубли при восстановлении не обнаружены ни в одном окне.

---

## 5. Commission и execution price (направление E)

### Доказанные дефекты (негативная валидация, до фиксов)

| ID | Дефект | Доказательство |
|---|---|---|
| D3 | `_extract_commission` превращал достоверный ноль (0.0) в `None` — ноль неотличим от «нет данных», подменялся модельной в CSV/P&L | `NEGATIVE_VALIDATION_BUY_TESTS.txt::test_tz09` |
| D4 | поздний отчёт BUY с комиссией не обогащал активную позицию (`entry_actual_commission` оставался None навсегда) | `::test_tz08` |
| D4b | поздняя цена исполнения не обогащала RECOVERY-запись | `::test_tz10` |
| D5 | повторный отчёт с противоречивой комиссией не был fail-closed на уровне позиции | `::test_tz11` |
| D6 | поздняя BUY-комиссия закрытой сделки не доходила до CSV: строка не обновлялась, накопительный P&L последующих сделок не пересчитывался | `::test_tz20` |
| D1 | реестр: повторный отчёт той же заявки молча перезаписывал FIGI/сторону | `::test_ledger_identity_conflict_figi_change_fail_closed` |
| D2 | реестр: поздний отчёт без цены затирал ранее подтверждённую `avg_exec_price` | `::test_ledger_price_not_wiped_by_later_record` |

### Исправления

- FIX-3: `_extract_commission` возвращает значение при присутствии поля
  (включая 0.0); None — только при отсутствии/некорректности.
- FIX-4: `_enrich_buy_entry_metadata` — позднее заполнение ТОЛЬКО отсутствующих
  `entry_actual_commission`/`execution_price` (активная позиция и закрытая
  запись в обеих guard-ветках); противоречивая комиссия → `uncertain_state` +
  UNCERTAIN-реестр, без перезаписи; событие `BUY_ENTRY_METADATA_ENRICHED`;
  немедленное сохранение state.
- FIX-4 (CSV): `needs_poll` дополнительно считает строку неполной, когда
  обогащённая entry-комиссия не отражена в CSV — штатный B2-механизм
  восстановления обновляет существующую строку и пересчитывает cumulative
  (механизм B2 не изменялся — только условие опроса).
- FIX-2: комиссия persists в реестре (`RECORD_FIELDS += commission`, сигнатуры,
  запись в `register_executed_buy`).
- FIX-1: наследование цены/комиссии при отсутствии в повторном отчёте;
  конфликт — только для повтора терминальной заявки.

### Семантика цены

`avg_exec_price` реестра — средняя цена КУМУЛЯТИВНОГО исполнения; между
нетерминальными отчётами легитимно уточняется. Для терминальной заявки
исполнение заморожено: противоречивая цена/комиссия в повторном отчёте →
UNCERTAIN (семантика B2 `apply_close_execution`). Тесты ТЗ-11, 22, 23.

---

## 6. BUY → CSV → P&L (направление F)

- Строка создаётся при переходе позиции в CLOSED (полный цикл BUY→SELL);
  связь с BUY через стабильный `trade_id` и `figi`; столбец `order_id` —
  клиентский UUID SELL-заявки закрытия (схема CSV не менялась).
- Отсутствие повторных строк: `_trade_id_already_logged` + `pos.logged`;
  восстановление метаданных обновляет СУЩЕСТВУЮЩУЮ строку атомарно
  (fail-closed на ambiguous trade_id). Тест ТЗ-19.
- `entry_commission_rub` — фактическая или модельная с пометкой
  `commission_source`; с FIX-4 позднее уточнение BUY-комиссии попадает в
  существующую строку.
- Exit-поля — только при `exit_price_confirmed` (инвариант ТЗ-5 B2 сохранён);
  фиктивный P&L запрещён (PRICE_UNKNOWN).
- `cumulative_net_pnl_rub` канонизируется хронологически (B2 V4, сохранён);
  позднее уточнение BUY-данных пересчитывает все последующие накопительные
  значения. Тест ТЗ-20.

---

## 7. Сверка с брокером и fail-closed (направление G)

- RECOVERY создаётся: (а) адопция позиции брокера без локального учёта
  (`reconcile` / `startup_recovery` pass 3); (б) регистрация исполненного BUY
  с неполными данными (единая точка).
- Идентичность RECOVERY: направление/количество сверяются с достоверным
  снимком; привязка к заявке — по подтверждённой принадлежности; автопривязка
  `_try_bind_recovery_entry` (единственный BUY по FIGI с
  `executed == quantity`, не REJECTED/INTENT, не в `closed_entry_order_ids`).
- Дубли исключены: `register_recovery`/`register` отказывают при активной
  позиции; повторная сверка не создаёт дубль (ТЗ-15); адопция после
  восстановления по заявке не выполняется (ТЗ-14).
- Недостоверный снимок (`get_positions()==None`) — учёт не меняется;
  направление UNKNOWN — адопция невозможна; расхождения → `RECONCILE_MISMATCH`
  + `uncertain_state` + блокировка новых входов.
- RECOVERY-позиция без позиции у брокера закрывается как внешнее закрытие по
  ДОСТОВЕРНОМУ снимку (CSV не пишется) — поведение B2/Samsung сохранено.

---

## 8. Сводка дефектов

### Доказанные (код + воспроизводимый тест)

| ID | Файл/место | Дефект | Фикс | Тест |
|---|---|---|---|---|
| D1 | `order_ledger.append` | молчаливая перезапись FIGI/стороны повторным отчётом | FIX-1 | `test_ledger_identity_conflict_figi_change_fail_closed` |
| D2 | `order_ledger.append` | затирание подтверждённой цены отсутствием данных | FIX-1 | `test_ledger_price_not_wiped_by_later_record` |
| D3 | `execution._extract_commission` | 0.0 → None | FIX-3 | `test_tz09` |
| D4 | `main.register_executed_buy` (активная ветка) | поздняя комиссия/цена не обогащают запись | FIX-4 | `test_tz08`, `test_tz10` |
| D5 | `main.register_executed_buy` | противоречивая комиссия не fail-closed | FIX-4 | `test_tz11` |
| D6 | `register_executed_buy` (guard-ветки) + `_recover_late_csv_metadata` | поздняя BUY-комиссия закрытой сделки не доходит до CSV/P&L | FIX-4 | `test_tz20` |

### Потенциальные (зафиксированы, НЕ исправлялись — вне минимальной области BUY)

1. `trading_cycle` partial-ветка: `le = pos_data.lots` (остаток портфеля) как
   «исполненные лоты этой заявки» при живом снимке; при внешней позиции по
   FIGI между проверкой входа и post лоты могли бы смешаться. Вероятность
   низкая; изменение затрагивает порядок ветки входа — не выполнялось.
2. `closed_entry_order_ids` без ограничения размера — осознанно (безопасность
   важнее памяти; короткие order_id).
3. `_poll_ledger_order_state` для legacy-записей опрашивает без явного типа
   идентификатора (решение ЭТАП 5Б — не менять без подтверждения типа).
4. `research_events.jsonl` — best-effort журнал (потеря события не влияет на
   учёт).
5. Средняя цена из `executed_order_price / (lots*lot_size)` предполагает
   кумулятивную денежную сумму исполнения; семантика проверена только на
   заглушках SDK.

### Не удалось проверить

- Реальные отчёты брокера (нет доступа — ЗАПРЕЩЕНО ТЗ).
- Многопроцессный доступ к файлам (вне архитектуры).
- Долгоживущий поток тысяч заявок (производительность `latest_all()`).

---

## 9. Соответствие обязательным формулировкам

```
STRATEGY LOGIC: UNCHANGED        # strategy.py/risk_manager.py/config.py не изменены (SHA256 сверены)
RESEARCH ONLY                    # все тесты — mock/stub, локальные, без сети
NO THRESHOLD IS OPTIMIZED        # ни один порог не менялся
NO FILTER IS INSTALLED           # ни один фильтр не добавлялся
NO LIVE ORDERS                   # заявок не отправлялось
OOS SEALED / H4 EXECUTION NOT AUTHORIZED
```
