# AUDIT_REPORT.md — полный аудит целостности учёта (ТЗ V3 §3–§5)

**Дата:** 2026-11-25
**Мандаты:** `STRATEGY LOGIC: UNCHANGED` · `RESEARCH ONLY` · `NO THRESHOLD IS OPTIMIZED` · `NO FILTER IS INSTALLED` · `NO LIVE ORDERS`
**Объект:** каноническая база V3 (VERSION_LINEAGE.md §5) → кандидат V3
**Метод:** офлайн, pytest + mock/stub, временные каталоги; GitHub READ-ONLY; main.py как торговое приложение не запускался.

Цепочка проверки: Broker report → Order Ledger → Execution Monitor → Position → State Persistence → CSV → Recovery → Final Accounting.

---

## 1. Направления аудита и результаты (ТЗ §5.1–§5.16)

### 5.1 BUY execution price: 0.0 против None — **ДЕФЕКТ ПОДТВЕРЖДЁН, ИСПРАВЛЕН**

Дефект (воспроизведён трассировкой, `evidence/p0_trace_baseline_evidence.txt`):

1. Частичное исполнение BUY; терминальный CANCELLED, брокер возвращает `executed_order_price=0`
   при `lots_executed>0`.
2. `ExecutionMonitor._extract_price()` возвращал `0.0` (деление 0/(lots*lot)) — 0.0 попадал в реестр
   как `avg_exec_price` (5 вызовов `avg_exec_price=exec_price`: main.py:3485, 3951, 4027, 4037, 4220 —
   **все проверены по контексту**; каждый получает цену из `_extract_price`).
3. Поздний отчёт с реальной ценой (cumulative 5 лотов, средняя 100.0) → metadata-guard BUY V1 FIX-1
   распознаёт «conflict» `0.0→100.0` на терминальной записи → **заявка переводится в UNCERTAIN**
   (ложная неопределённость; статус NOT VERIFIED из V2 объяснён этим же конфликтом).
4. Трассировка: запись [2] `CANCELLED avg=0.0` → запись [3] `UNCERTAIN, reason=… avg_exec_price 0.0->100.0`.

Все 16 call sites `_extract_price` проверены: потребители уже корректно обрабатывают None
(ветки RECOVERY, `if not exec_price or exec_price <= 0: continue`, `promote_recovery` отвергает ≤0).
Исправление — FIX-ZERO-PRICE (FIXES.md V3-1/V3-2): цена = конечная и положительная, иначе None;
0.0 не является подтверждённой ценой ни на записи, ни на чтении. Защита от НАСТОЯЩИХ противоречий
(два различных достоверных значения на терминальной заявке) сохранена — тест
`test_v3_ledger_real_price_contradiction_still_fail_closed`.

### 5.2 Late BUY execution — **VERIFIED**

Сценарии P0-батча (частичное исполнение → CANCELLED → поздний рост → повторный отчёт):
19 тестов корневого файла проходят, включая интеграционный сценарий §5.14 (после исправления).
Потери лотов/двойного применения/ложного конфликта не обнаружено.

### 5.3 SELL price и B2 compatibility — **VERIFIED**

* B2 close accounting: 96/96; production-код B2 (`apply_close_execution`, per-order cursor,
  cursor identity, close_applications, CSV recovery) — байт-в-байт без изменений V3
  (evidence/diffs/v3_candidate_vs_baseline_*.diff).
* SELL zero-price зеркальный сценарий добавлен тестом `test_v3_sell_zero_price_then_real_price_no_uncertain`.
* Подтверждено: B2-cursor никогда не сохраняет 0.0 как цену (условие `execution_price > 0`
  в обеих ветках apply_close_execution) — тест `test_v3_sell_cursor_zero_price_not_stored_b2_semantics`.

### 5.4 NaN / Infinity / некорректные числа — **ДЕФЕКТ ПОДТВЕРЖДЁН, ИСПРАВЛЕН**

До V3: `float("inf")` проходил проверки `> 0` / `>= 0` в `_enrich_buy_entry_metadata` (FIX-1 V2)
и записывался в State; NaN отсекался сравнениями (но неявно); `_extract_commission` мог вернуть
±Inf; `_extract_price` мог вернуть ±Inf (переполнение). Исправлено (FIXES.md V3-1, V3-3):
явные `math.isfinite` на всех трёх функциях; невалидное значение делает операцию ЦЕЛИКОМ
неудачной без частичной мутации (структура FIX-1 сохранена); невалидные данные не попадают
в State/Ledger/CSV. Тесты: 13–17 test_corrective_audit_v3.py (inf commission, nan price,
inf price, последующий валидный вызов, extract-семантика).

### 5.5 Нулевая комиссия — **VERIFIED (семантика сохранена и кодифицирована)**

* None ≠ 0.0 ≠ положительное — различаются везде (FIX-3 BUY V1, FIX-1 V2 сохранены).
* needs_poll `or ""`: читаются CSV-строки (DictReader); реальный ноль пишется «0.00» (truthy) —
  ложного polling нет (V2-тесты 9–10 проходят; выражения проверены: main.py:2648–2664).
* V3-гвад: `_valid_commission` — валидно любое конечное неотрицательное; тесты 11–12 V3
  (0.0 → конфликт остаётся fail-closed; None не затирает 0.0).

### 5.6 Idempotency — **VERIFIED**

Повторы NEW/PARTIALLY_FILLED/FILL/CANCELLED/REJECTED, позднее обогащение, рестарт между
одинаковыми отчётами: покрыты B2 (96), P0-5 (4 теста), V3 тест 8 (`test_v3_ledger_repeat_terminal_report_idempotent`).
Повторный отчёт не меняет итоговый учёт.

### 5.7 Partial fills / CANCELLED / late fills — **VERIFIED**

Все комбинации покрыты P0-батчем (19) + интеграционным тестом §5.14 + B2. Cumulative quantity
применяется только через delta-механику (`record_observation`/`apply_close_execution`);
регресс/переполнение fail-closed (test_order_ledger.py::test_cumulative_execution_regression_fails_closed).

### 5.8 Order Ledger state machine — **VERIFIED (усилен)**

Допустимые/запрещённые переходы, identity (order_id/trade_id/figi/side/order_id_type),
cumulative lots, avg price, commission, terminal metadata, conflict detection → UNCERTAIN
с сохранением прежних значений, fail-closed: все присутствуют. V3-изменение guard'а:
конфликт распознаётся ТОЛЬКО между двумя ДОСТОВЕРНЫМИ значениями (валидность по типу поля);
отсутствующие/невалидные данные не становятся «подтверждёнными нулями» (тесты 3–6 V3).

### 5.9 State persistence — **VERIFIED**

`_save_state_checked`: 47 вызовов в main.py; FIX-1 V2 (проверка результата, откат, отсутствие
ложных подтверждений) сохранён. Persistence-тесты (8, включая subprocess-кейсы) проходят
после восстановления отсутствовавшего `tests/conftest.py` (FIXES.md V3-T1). Аварийное
завершение между операциями, рассинхронизация state/ledger, повторное сохранение — покрыты.

### 5.10 Metadata enrichment — **VERIFIED (FIX-1 сохранён, расширен)**

validate→stage→commit→checked save + rollback сохранены байт-в-байт (кроме добавленной
isfinite-валидации шага 1). Повторный вызов не дублирует данные; поздние сведения дополняют
существующую запись; событие BUY_ENTRY_METADATA_ENRICHED пишется только после подтверждённого
сохранения (тесты A–F/C2 V2 + V3 13–16).

### 5.11 Recovery / UNCERTAIN — **VERIFIED**

Отсутствующая локальная позиция при исполнении, восстановление, повторная сверка, несовпадение
FIGI/side, отсутствующий order_id, частичное закрытие, рестарт при UNCERTAIN, повторное появление
позиции: покрыты P0-2/P0-3/P0-4/P0-5 (19+11+2+4 тестов). Позиция недоступна для нового закрытия,
пока предыдущее не разрешено достоверно (FIGI-блокировки, UNCERTAIN-ветки) — fail-closed сохранён
(test_p05_3_failed_or_contradictory_reconcile_keeps_uncertain и др.).

### 5.12 CSV и P&L — **VERIFIED**

Создание/обновление строки, late price/commission, частичные/полные/множественные закрытия,
повторные отчёты, восстановление после рестарта, хронология, отсутствие двойного P&L:
B2-батч (96) + SELL Stage 3 (48). CSV отражает подтверждённое состояние; двойного P&L не обнаружено.

### 5.13 Cross BUY/SELL scenarios — **VERIFIED**

BUY частично исполнен → SELL; BUY CANCELLED → поздний BUY fill; восстановление через Recovery → SELL;
SELL частично → поздний fill; SELL частично → UNCERTAIN; рестарт между частичным и терминальным;
повторный reconciliation/enrichment — покрыты интеграционными P0 + B2 + Stage 3 тестами.
Все проходят на кандидате.

### 5.14 Незакрытый P0-тест из V2 — **ЗАКРЫТ НА УРОВВНЕ ПРОИЗВОДСТВЕННОГО КОНТРАКТА**

`test_p0_batch2_late_execution.py::test_integration_trading_cycle_partial_cancel_recovery_open_late_lots`:
* V2 статус: NOT VERIFIED (9-е утверждение вскрывало конфликт 0.0→цена; производство не трогалось).
* V3: корень дефекта воспроизведён трассировкой, исправлен на уровне production-контракта
  (семантика цены None/положительная; guard не считает 0.0 подтверждённой ценой). Тест
  **PASSES** на кандидате без изменения его утверждений (утверждения не ослаблялись —
  diff теста отсутствует: root-версия байт-в-байт совпадает с канонической базой).

### 5.15 Тестовый дрейф — **ДЕФЕКТ ПОДТВЕРЖДЁН, УСТРАНЁН**

Найдены 8 устаревших tests/-копий + отсутствующий `tests/conftest.py` + path-дефект корневого
`test_execution.py`. Доказано diff-ами, что копии — старые снапшоты канонических корневых версий
(root длиннее; различия = обновления ЭТАП 5Б order_id_type, pytest-изоляция, ТЗ-5 exit_price_confirmed,
ADX-конфиг-моки). Копии синхронизированы с корневыми версиями (утверждения сохранены —
корневая версия и есть канонический контракт); ни один тест не удалён и не ослаблен.
Детали — FIXES.md V3-T1/T2/T3.

### 5.16 Безопасность тестового окружения — **VERIFIED**

* Тесты не вызывают брокерские API: единственный сетевой модуль `tinkoff_client.py` в тестах
  подменяется fake/stub-объектами (проверено grep: ни один тест не импортирует requests/httpx/aiohttp,
  не создаёт реальных клиентов; `token="test-token"` — фиктивный аргумент mocked-конструктора).
* Реальные runtime-файлы не используются: STATE_FILE/EVENTS/TRADES изолируются в tmp_path
  (fixture env/env_v2/env_v3); runtime-файлы не входят в кандидат.
* Торговый цикл не запускается как приложение: только вызовы отдельных функций trading_cycle
  на fake-клиентах в тестах (это юнит-вызовы, не приложение).
* Опасные скрипты в исполняемую папку кандидата не включены (DANGEROUS_SCRIPTS.md, карантин).

## 2. Приоритеты дефектов (ТЗ §4)

| Уровень | Дефект | Статус |
|---|---|---|
| P0 | Ложный UNCERTAIN при поздней цене после «нулевой цены» (§5.1/§5.14) | **ИСПРАВЛЕН** (V3-1, V3-2) |
| P1 | NaN/±Inf в enrichment/extract (§5.4) | **ИСПРАВЛЕН** (V3-3) |
| P2 | Тестовая инфраструктура: отсутствующий tests/conftest.py, path-баг, 8 дрейф-копий (§5.15) | **ИСПРАВЛЕН** (V3-T1–T3) |
| P2 | Среда: pandas-ta-classic отсутствовал в аудиторском окружении (22 падения) | УСТРАНЁН установкой пакета из requirements.txt (легитимно; без изменения кода) |

P0-критерии: все обязательные P0-сценарии VERIFIED; ни один критический сценарий не остался NOT VERIFIED.

## 3. Проверка сохранности FIX-1 (ТЗ §5.10) — отдельное заключение

Сравнение `_enrich_buy_entry_metadata` канонической базы и кандидата: единственное изменение —
добавлены два isfinite-условия в шаг 1 (валидация). Все пять фаз (validate→stage→commit→checked
save→rollback) и семантика возвращаемых значений совпадают. Тесты A–F/C2 (18) проходят на кандидате.

## 4. Что НЕ менялось

* Стратегия/сигналы/индикаторы/фильтры/SL/TP/риск-параметры/пороги: strategy.py, config.py,
  risk_manager.py, screener.py, telegram_bot.py, tinkoff_client.py — **байт-в-байт с pristine**.
* B2 accounting-код: apply_close_execution, per-order cursor, cursor identity, close_applications —
  байт-в-байт с канонической базы.
* Ни один тест не удалён; ни одно утверждение не ослаблено.
