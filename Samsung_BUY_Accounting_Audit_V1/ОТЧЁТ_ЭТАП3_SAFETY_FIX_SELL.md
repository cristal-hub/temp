# ОТЧЁТ — ЭТАП 3: SAFETY FIX ДЛЯ NOT_FOUND 50005, SELL CONFIRMATION И ЗАЩИТА ОТ ДУБЛИРУЮЩИХ ЗАЯВОК

Проект: `Tsclp_v2.1_volatile_Samsung` · Рабочая копия: `work/Samsung`
Дата: 2026-11-22 · Режим: SANDBOX ONLY / NO LIVE ORDERS · Только unit-тесты с FakeClient
Основание: отчёт «ЭТАП 2 — READ-ONLY АУДИТ NOT_FOUND 50005» от 2026-11-22 и ТЗ ЭТАПА 3.

---

## 1. Исходное состояние (зафиксировано до изменений)

1. Работа велась в `/home/z/my-project/work/Samsung` (проверено по содержимому и мtime).
2. Изменения ЭТАПА 1 подтверждены до начала работ:
   - `ExecutionMonitor.extract_price_from_post_order_response` (execution.py);
   - `ExecutionMonitor.extract_price_from_order_state` (execution.py);
   - `tests/test_extract_price_types.py` (597 строк, SHA256 `0082300f…` — не менялся).
3. Резервные копии изменяемых файлов: `work/_stage3_originals/{main.py, execution.py, order_ledger.py}`.
4. SHA256 до изменений (`work/_stage3_originals/SHA256SUMS_stage3_before.txt`):
   - `main.py` — `7bd59ac6363a976d89d91d8938b02e708d6fb9d93857e891fceed183f5f3a3f3`
   - `execution.py` — `b791667e09fc3f3c6f1708c451d3adc5df2dd3928f1ed66e8b73462593f2186a`
   - `order_ledger.py` — `cc6c5768079afb4501779790ce3b5983c9f157bf5d9cf275060504235eb82d3d`
5. Baseline тестов: `python -m pytest tests -q` → **326 passed** (все тесты, существовавшие до ЭТАПА 3).
6. Незавершённых изменений владельца, отсутствующих в отчётах, не обнаружено: файлы
   `strategy.py`, `config.py`, `risk_manager.py`, `order_ledger.py`, `tinkoff_client.py`,
   `state.json`, `order_ledger.jsonl`, `research_events.jsonl`, `research_trades.csv`
   имеют mtime 2026-11-19 (до сессии) и не изменялись.

---

## 2. Исходная причина каждого исправленного сценария (по аудиту ЭТАПА 2)

| № | Опасный сценарий | Причина (аудит ЭТАП 2) |
|---|---|---|
| 1 | Локальная позиция закрывается без подтверждения SELL | `resolve_uncertain` (execution.py:572–585 до правки): `broker is None` → безусловно `quantity=0, state=CLOSED`. `NOT_FOUND`/`None`/timeout не доказывают исполнение SELL, но учёт закрывался |
| 2 | Вторая SELL по тому же FIGI после неопределённой первой | `resolve_uncertain` возвращал позицию в OPEN → SL/TP срабатывали снова → `close_position` отправлял новую SELL; защита `figi_blocks_buy` (order_ledger.py:392–398) блокирует только BUY |
| 3 | Фиктивный P&L при неизвестной цене выхода | `process_closing`: `exit_price = pos.execution_price or 0.0` → при `execution_price=None` подставлялся 0.0 (или цена входа оставалась в `pos.execution_price` от входа) → строка сделки с выдуманным результатом |
| 4 | SELL-заявки не получают полноценного опроса | `poll_open_orders` опрашивал только `side="BUY"` и `side=None`; незавершённые SELL оставались в реестре без последующего опроса |
| 5 | Расхождение позиции и реестра | Следствие пунктов 1 и 4: позиция закрывалась локально, SELL-запись реестра оставалась нетерминальной без разрешения |

Первопричина `NOT_FOUND 50005` не выяснялась и не исправлялась (вне рамок ТЗ, причина не доказана).

---

## 3. Точные изменённые функции и строки (номера в текущих файлах)

### `execution.py` (3 hunk'а, +110/−5 строк)
| Строки | Что изменено |
|---|---|
| 77–93 | Шапка: блок «ИЗМЕНЕНИЯ (SAFETY FIX ЭТАП 3…)» |
| 112–140 | **Новое**: константа `SELL_TERMINAL_STATUSES` и функция `has_unresolved_sell(pos)` — признак незавершённой/неопределённой SELL (курсор `close_order_id` или нетерминальная запись `close_orders`), fail-closed |
| 621–676 | **`resolve_uncertain`**: ветка `broker is None` разделена: (а) при `has_unresolved_sell(pos)` позиция остаётся `UNCERTAIN`, исход `"SELL_CLOSURE_UNCONFIRMED"`; (б) без незавершённой SELL — внешнее закрытие `CLOSED` + `close_reason="EXTERNAL_CLOSE"` + `logged=True`, исход `"EXTERNAL_CLOSE"`. Функция возвращает строку исхода (`"OPEN"`/`"UNCERTAIN"` — ветки с брокером без изменений) |

### `main.py` (8 hunk'ов, +388/−7 строк)
| Строки | Что изменено |
|---|---|
| 4–45 | Шапка: блок «ИЗМЕНЕНИЯ (SAFETY FIX ЭТАП 3…)» |
| 361–363 | Импорт `has_unresolved_sell` из execution |
| 479–488 | **Новое**: множества-дедупликаторы `_price_unknown_reported`, `_sell_unconfirmed_alerted` |
| 951–980 | **Новое**: `_sell_blocked_reason(pos, ledger)` — причина запрета SELL (реестр `figi_has_open_order(figi, "SELL")`; позиция `UNCERTAIN`; `has_unresolved_sell(pos)`) |
| 983–1001 | **`close_position`**: guard непосредственно перед отправкой SELL — при `blocked_reason` возврат ДО генерации `order_id`/записи INTENT/сетевого вызова; событие `SELL_DUPLICATE_BLOCKED` |
| 1087–1140 | **`process_closing`**: обработка исхода `resolve_uncertain` — событие+уведомление `SELL_CLOSURE_UNCONFIRMED` (дедуп на (FIGI, trade_id, order_id)) и `POSITION_EXTERNAL_CLOSE` |
| 1153–1196 | **`process_closing`** (CSV-блок): guard `PRICE_UNKNOWN` — при `execution_price` None/≤0 строка сделки с P&L не формируется, событие `PRICE_UNKNOWN` (дедуп на (FIGI, trade_id)); позиция остаётся `CLOSED` c `logged=False` для записи после появления достоверной цены |
| 2368–2540 | **`poll_open_orders`**: новый третий цикл — полноценный опрос `open_orders(side="SELL")` (см. раздел 4) |

Новые файлы: `tests/test_sell_confirmation.py` (15 тестов).
`order_ledger.py` **не менялся** (SHA256 совпадает с backup) — существующего API реестра
(`figi_has_open_order`, `open_orders(side=...)`, `record_status`, `record_uncertain`,
`latest`) оказалось достаточно; расширение не потребовалось.
`tinkoff_client.py` **не менялся** (потеря типа gRPC-ошибки остаётся отдельной задачей).

---

## 4. Новая логика состояний BUY/SELL

### 4.1 `resolve_uncertain` (исправление №1 + №8)
- Позиция UNCERTAIN, у брокера её нет, есть незавершённая/неопределённая SELL
  (`close_order_id` или нетерминальная запись `close_orders`) → позиция **остаётся
  UNCERTAIN**: количество/FIGI/entry price/order_id SELL сохранены, заявка доступна
  опросу, P&L не формируется (`state != CLOSED` — CSV-блок не выполняется).
  Reconcile продолжает показывать расхождение «есть локально, нет у брокера» —
  неопределённость явно видима.
- Позиции нет в портфеле, незавершённой SELL нет → `EXTERNAL_CLOSE`: `quantity=0`,
  `CLOSED`, `logged=True` (без CSV-строки и P&L), событие `POSITION_EXTERNAL_CLOSE`.
- Ветки «брокер показывает позицию» (`OPEN`/`UNCERTAIN`) не менялись.

### 4.2 Опрос SELL в `poll_open_orders` (исправление №2)
Цикл по `ledger.open_orders(side="SELL")` (нетерминальные + терминальные с
residual-исполнением), состояние — существующий `get_sandbox_order_state(order_id)`:
- **A. FILL/частичное/PARTIALLYFILL/le>0** — привязка проверяется по FIGI + order_id
  (запись в `close_orders` или курсор `close_order_id`, направление BUY); применение —
  штатный `apply_close_execution` (идемпотентный cumulative-delta, частичное исполнение
  списывает ровно подтверждённые лоты и НЕ закрывает позицию целиком); цена —
  **только** `extract_price_from_order_state` (Этап 1), новое преобразование не создано;
  `FILL` с `le<requested` — противоречие неполного рыночного исполнения → `UNCERTAIN`
  (как в `resolve_closing`). Разрешённая заявка записывается в реестр терминальным
  статусом; частичное терминальное исполнение остаётся residual-записью для повторной
  сверки (как у BUY, партия P0-2).
- **B. None/NOT_FOUND/timeout/ошибка** — заявка НЕ считается исполненной: позиция не
  закрывается, запись не удаляется из реестра, блокировка повторной SELL сохраняется,
  опрос продолжается в следующих циклах.
- **C. NEW (le=0)** — наблюдение (`record_status NEW`); позиция не закрывается,
  вторая SELL запрещена (исправлением №3).
- **D. CANCELLED/REJECTED/EXPIRED с le=0** — только по фактическому терминальному
  статусу брокера: исполнение не выдумывается, остаток позиции сохранён, курсор снят
  штатно (`apply_close_execution` с cumulative=0 → OPEN), запись реестра закрывается.
- FILL с `le=0` — противоречие (дефект №8) → `UNCERTAIN`-запись, не подтверждение.
- Идемпотентность: терминальная запись реестра с `le ≤ recorded` повторно не
  применяется и не перезаписывается (аналог защиты P0-2 у BUY — нет двойного списания
  и бесконечных записей). Непривязанная заявка (позиция учёта не знает order_id):
  терминальный статус брокера разрешает запись по факту (как `startup_recovery`);
  признаки исполнения при непривязке — `UNCERTAIN` для оператора.
- Семантика BUY-поллинга и ветки `side=None` **не менялись**.

### 4.3 Защита от повторной SELL (исправление №3)
`_sell_blocked_reason(pos, ledger_ref)` проверяется в `close_position` непосредственно
перед отправкой (не только при формировании сигнала). Запрещено, пока:
- в реестре есть нетерминальная/UNCERTAIN SELL по FIGI (включая `NOT_FOUND`→UNCERTAIN,
  `state=None`, INTENT после сбоя);
- позиция в `UNCERTAIN` (остаток не подтверждён; в т.ч. когда портфель временно
  показывает прежнее количество);
- в учёте позиции есть незавершённая SELL (курсор/журнал `close_orders`) — в т.ч.
  после перезапуска (сериализуются в `state.json`).
Разрешение — только достоверный терминальный статус предыдущей заявки, снятый курсор
и подтверждённый остаток. Новая причина закрытия (SL/TP) сама по себе разрешением не
является. Автоматической повторной отправки старой заявки нет. Контрольный тест
подтверждает: первая SELL не блокируется.

### 4.4 Неизвестная цена выхода (исправление №4)
В CSV-блоке `process_closing`: лоты подтверждены, но `execution_price` None/≤0 →
обычная строка сделки с P&L не формируется; цена входа не подставляется как цена
выхода; последняя котировка не используется; фиктивный нулевой P&L не пишется;
событие `PRICE_UNKNOWN` фиксируется (дедуп). Позиция остаётся `CLOSED` с `logged=False`:
при появлении достоверной цены (`apply_close_execution` обновляет `execution_price`)
сделка записывается штатным путём. Прежний `exit_price = … or 0.0` устранён.

---

## 5. Новые тесты и результаты

`tests/test_sell_confirmation.py` — 15 тестов, все на FakeClient/dummy-объектах,
без сети:

| ТЗ № | Тест | Результат |
|---|---|---|
| — | `test_has_unresolved_sell_semantics` | PASSED |
| 1 | `test_01_sell_state_none_position_stays_uncertain` | PASSED |
| 2 | `test_02_not_found_empty_portfolio_no_confirmed_close_no_pnl` | PASSED |
| 3 | `test_03_not_found_portfolio_shows_position_no_second_sell` | PASSED |
| 4 | `test_04_uncertain_sell_blocks_close_position` (+ контроль «первая SELL разрешена») | PASSED |
| 5 | `test_05_confirmed_full_fill_closes_position` | PASSED |
| 6 | `test_06_confirmed_partial_fill_partial_close` (+ дозаполнение до FILL) | PASSED |
| 7 | `test_07_new_status_waits_no_second_sell` | PASSED |
| 8 | `test_08_cancelled_rejected_no_invented_execution` | PASSED |
| 9 | `test_09_price_unknown_no_pnl_row_price_unknown_event` (+ идемпотентность события) | PASSED |
| 10 | `test_10_confirmed_price_from_order_state_not_entry_not_quote` | PASSED |
| 11 | `test_11_external_close_without_sell_no_robot_pnl` | PASSED |
| 12 | `test_12_buy_not_found_stage1_no_regression` (54.15 @ 945 лот., НЕ 0.0573) | PASSED |
| 13 | `test_13_repeated_poll_applies_fill_once` (+ один CSV-ряд) | PASSED |
| 14 | `test_14_restart_preserves_uncertain_sell_block` | PASSED |

---

## 6. Полный результат pytest

- Baseline до изменений: `python -m pytest tests -q` → **326 passed** (10.89s).
- Финал: `python -m pytest tests/ -v` → **`341 passed in 11.04s`** (326 старых + 15 новых).
- Ни один старый тест не удалён, не ослаблен и не изменён
  (`test_extract_price_types.py` SHA256 `0082300f…` — без изменений; остальные тесты
  не редактировались — проверено diff-сверкой: в diff попадают только `main.py`,
  `execution.py`, новый файл тестов).

## 7. Diff summary

- `execution.py`: 3 hunks, +110/−5 (шапка, `SELL_TERMINAL_STATUSES`+`has_unresolved_sell`, `resolve_uncertain`).
- `main.py`: 8 hunks, +388/−7 (шапка, импорт, дедуп-множества, `_sell_blocked_reason`,
  guard в `close_position`, обработка исходов в `process_closing`, guard `PRICE_UNKNOWN`,
  SELL-цикл в `poll_open_orders`).
- `tests/test_sell_confirmation.py`: новый файл, ~615 строк, 15 тестов.
- Полные diff'ы: `work/_stage3_originals/izmenenija_etap3_execution.diff`,
  `work/_stage3_originals/izmenenija_etap3_main.diff` (копии — в `download/`).
- `order_ledger.py`, `tinkoff_client.py`, `strategy.py`, `config.py`, `risk_manager.py`,
  `telegram_bot.py`, `logger.py`, `screener.py` — без изменений.

## 8. SHA256 до/после

| Файл | До (ЭТАП 3) | После |
|---|---|---|
| main.py | `7bd59ac6363a976d…183f5f3a3f3` | `64fc21dfd05c319a62d1f65b5619e52d67c09493e306ebb83ef56d562d9de9a3` |
| execution.py | `b791667e09fc3f3c…93f2186a` | `349f714688815c6499e967c3c875ab7cacffa86e4d76492981454e71deddadda` |
| order_ledger.py | `cc6c5768079afb45…235eb82d3d` | `cc6c5768079afb45…235eb82d3d` (**без изменений**) |
| tests/test_extract_price_types.py | `0082300fb5c95f65…c3243c1a` | `0082300fb5c95f65…c3243c1a` (**без изменений**) |
| tests/test_sell_confirmation.py | — (новый) | `de5f55a825001cd7a29762081392e80aa728620310b30efaa9b4934bc22808b5` |

## 9. Подтверждение отсутствия API-запросов и заявок

- Запускались только `py_compile` и `pytest` (cwd `work/Samsung`,
  `PYTHONPATH=/home/z/my-project/scripts/stubs` — SDK-заглушка; реальный
  `t_tech.invest.AsyncClient` недоступен и конструктор-заглушка запрещает сеть).
- Все тесты используют FakeClient/dummy-объекты; сетевых обращений нет.
- `main.py` как модуль не запускался (`python main.py` не выполнялся), торговый цикл
  не стартовал, `trading.flag` в корне рабочей копии не создавался, FORCE_TRADE не
  включался.
- Реестр/журналы владельца не тронуты: `state.json`, `order_ledger.jsonl`,
  `research_events.jsonl`, `research_trades.csv` — mtime 2026-11-19, содержимое
  не менялось (conftest.py перенаправляет журналы тестов в tmp_path).
- `.env`, токены, account_id, секреты: файл `.env` в `work/Samsung` отсутствует,
  ничего не выводилось и не изменялось.
- git-операции (commit/push/reset/checkout) не выполнялись.

## 10. Оставшиеся риски и нерешённые вопросы

1. **NOT_FOUND 50005 — первопричина не выяснена** (вне рамок ЭТАПА 3). Потеря типа
   gRPC-ошибки в `tinkoff_client.py` (различение NOT_FOUND/timeout) остаётся отдельной
   диагностической задачей; сейчас любой недоступный статус трактуется как
   неопределённость (fail-closed).
2. **NOT_FOUND без разрешения** — если статус SELL-заявки недоступен бесконечно,
   позиция остаётся UNCERTAIN, а повторная SELL по FIGI блокирована до
   оператора/восстановления статуса. Это осознанное fail-closed поведение ТЗ;
   автоматического вывода из неопределённости нет.
3. **Крайний случай**: INTENT-запись SELL, который так и не был отправлен (крах между
   INTENT и POST) — опрос получает NOT_FOUND и сохраняет запись (неопределённость);
   разблокировка только оператором. Купировано малой вероятностью окна.
4. **Дедуп-множества** (`_price_unknown_reported`, `_sell_unconfirmed_alerted`) живут
   в памяти процесса: после перезапуска событие/уведомление может быть записано
   повторно один раз. CSV-guard от этого не зависит (идемпотентен по `trade_id`).
5. **PRICE_UNKNOWN без появления цены** — если цена не появится ни в одном последующем
   отчёте брокера, сделка останется без CSV-строки (CLOSED, `logged=False`), видимой в
   `state.json` и по событию; решение — за оператором/сверкой. Автоподстановки цены нет.
6. Неопределённость семантики `OrderState.executed_order_price` при `lot_size > 1`
   сохранена и задокументирована на ЭТАПЕ 1 — не решалась и на этом этапе.

## 11. Критерий приёмки

Подтверждён тестами 1–14: ни один неопределённый ответ брокера (None/NOT_FOUND),
отсутствие позиции в портфеле или отсутствие цены не приводит к ложному подтверждению
исполнения SELL, повторной SELL по неопределённой заявке или записи выдуманного P&L.

**Статус: работы ЭТАПА 3 завершены. `main.py` не запускался, FORCE_TRADE не включался,
sandbox-торговля не проводилась — ожидание проверки и согласования владельца.**
