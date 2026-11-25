# VERIFIED_CHANGES.md — точный список подтверждённых изменений

Независимый аудит, 2026-11-25. Все факты установлены самостоятельно: клонирование
репозиториев (read-only), собственные `diff -u`, собственные SHA256, собственные
прогоны pytest. Утверждения из README/отчётов кандидата НЕ принимались как
доказательства.

Мандаты:

```
STRATEGY LOGIC: UNCHANGED
RESEARCH ONLY
NO THRESHOLD IS OPTIMIZED
NO FILTER IS INSTALLED
NO LIVE ORDERS
OOS SEALED / H4 EXECUTION NOT AUTHORIZED
```

---

## 1. Контроль версий (установлено независимо)

| Источник | Факт | Проверка |
|---|---|---|
| Baseline: `cristal-hub/cristal-hub-Tsclp_v2.1_volatile_Samsung` | HEAD = `051b10f095d45c053492ca333449a9a9f518f33f` — **совпадает с контрольным коммитом ТЗ** | `git ls-remote` до клонирования; `git rev-parse HEAD` после |
| B2-кандидат: `cristal-hub/temp/samsung_B2_integrated_v1_v7` | каталог в репозитории `cristal-hub/temp`, HEAD репо = `bdd423a` | клонирование `temp.git` |
| BUY-кандидат: `cristal-hub/temp/Samsung_BUY_Accounting_Audit_V1` | каталог в том же репозитории | клонирование `temp.git` |
| ZIP `Samsung_B2_Integrated_V1_V7.zip` | содержимое **байт-в-байт совпадает** с каталогом `samsung_B2_integrated_v1_v7/` (единственное отличие — сам ZIP-файл внутри каталога) | `diff -rq` распакованного ZIP и каталога |
| ZIP `Samsung_BUY_Accounting_Audit_V1.zip` | содержимое **байт-в-байт совпадает** с каталогом `Samsung_BUY_Accounting_Audit_V1/` (единственное отличие — сам ZIP-файл) | `diff -rq` |
| ZIP `AUDIT_9_FAILURES.zip` | присутствует во всех трёх деревьях, SHA256 идентичен во всех трёх (исторический артефакт предыдущих аудитов) | SHA256 |

Исходники клонированы в рабочую папку аудита; исходные каталоги НЕ изменялись;
все прогоны и проверки выполнены на отдельных копиях.

---

## 2. Состав production-файлов (установлено независимо)

Сравнение SHA256 по трём деревьям (baseline 051b10f / B2 / BUY):

| Файл | baseline | B2 | BUY | Изменения |
|---|---|---|---|---|
| `main.py` | 8ed2293b… | fac787ac… | 9cad7d50… | B2: пакет В1–В7 CLOSE ACCOUNTING; BUY: FIX-4 |
| `execution.py` | 72b19783… | 6fd0ed19… | 03cec03b… | B2: close-механика; BUY: FIX-3 (одна функция) |
| `order_ledger.py` | 766e1f37… | **= baseline** | 0bdb3423… | только BUY: FIX-1/FIX-2 |
| `logger.py` | 266c937e… | df22ed91… | **= B2** | только B2 (CSV recovery v2.3.6/7) |
| `config.py` | 6c4df6e4… | **= baseline** | **= baseline** | НЕ менялся (профиль FORCE_TRADE — как в baseline) |
| `strategy.py` | 43906866… | = | = | НЕ менялся |
| `risk_manager.py` | d1c72c2e… | = | = | НЕ менялся |
| `tinkoff_client.py` | fe69b045… | = | = | НЕ менялся |
| `screener.py`, `telegram_bot.py`, `conftest.py` | — | = baseline | = baseline | НЕ менялись |
| `state.json` | 78a9eeb8… | **= baseline** | **44c9f9ab… (СБРОС, 169 байт)** | BUY: сброшен (см. UNVERIFIED_AND_RISKS.md, U-1) |
| `order_ledger.jsonl` | cc474807… | **= baseline** | **= baseline** | НЕ менялся (единый артефакт во всех трёх) |
| `research_trades.csv` | 32d37aa0… | = | = | НЕ менялся |
| `research_events.jsonl` | f8a8acbc… | **= baseline** | **0aaa9431… (+160 событий тестов)** | BUY: дозаполнен тестовыми прогонами (U-2) |
| `sandbox_pnl.csv` | f0399d32… | = | = | НЕ менялся |

Полный рекурсивный `diff -rq baseline → B2`: production-код — ровно 3 файла
(`main.py`, `execution.py`, `logger.py`); добавлены 7 новых корневых B2-тестов
(`test_b2_close_accounting.py`, `test_b2_csv_recovery.py`,
`test_b2_terminal_metadata_recovery.py`, `test_b2_v4_accounting_consistency.py`,
`test_b2_v5_identity_and_timestamp.py`,
`test_b2_v6_timestamp_identity_close_reason.py`,
`test_b2_v7_cursor_version_and_alt_timestamp.py`) и документация.

Полный рекурсивный `diff -rq B2 → BUY`: production-код — ровно 3 файла
(`main.py`, `execution.py`, `order_ledger.py`); runtime — `state.json`,
`research_events.jsonl`; тесты — обновлены `test_commission.py` и
`tests/test_commission.py`, добавлен `test_buy_accounting_audit.py`; остальное —
документация. **Никаких изменений, не описанных ниже, не обнаружено**, кроме
двух исключений, зафиксированных в UNVERIFIED_AND_RISKS.md (U-1, U-2: runtime-
файлы, изменённые вопреки тексту CHANGED_FILES.md §4).

---

## 3. Изменения, унаследованные от B2 (baseline → B2)

Подтверждено собственным `diff -u` (baseline vs B2):

* `main.py` (diff 1483 строки): пакет В2 CLOSE ACCOUNTING — `apply_close_execution`
  с per-order cursor'ом (`close_orders[oid]`: `confirmed_executed_lots`,
  `applied_lots`, `status`, `avg_exec_price`, `commission`, `requested_at`,
  `identity_version`), заморозка терминальных отчётов, `_close_request_ts`
  (единый `close_requested_at`), B2-закрытие по реестру (`LEDGER_CLOSE`),
  `_recover_late_csv_metadata` + `pending_csv_recoveries` (V4/V5), строгая
  валидация идентичности cursor'ов (V6/V7), INTENT/SENT-протокол SELL.
* `execution.py` (diff 753 строки): `apply_close_execution`, `resolve_closing`
  (опрос SELL по EXCHANGE/REQUEST), `resolve_uncertain` (защита от повторного
  открытия при живой SELL), `add_close_order`, блокировки повторной SELL.
* `logger.py` (diff 457 строк): `find_trade_row`/`update_trade_row` (fail-closed
  по trade_id), атомарная перезапись CSV, `_recompute_cumulative`
  (хронологический cumulative по `exit_time`).
* 7 новых B2-тестов (корень) — B2 v1–v7.

## 4. Изменения BUY Accounting (B2 → BUY) — подтверждены собственным diff

### 4.1 `order_ledger.py` — FIX-2 + FIX-1

1. `RECORD_FIELDS`: в КОНЕЦ добавлено поле `commission` (обратная совместимость
   со старыми журналами).
2. `append()`: `commission` включён в копируемые поля; добавлен блок FIX-1 —
   повторный отчёт той же заявки (тот же order_id):
   * конфликт FIGI/side → статус UNCERTAIN, подлинные значения сохраняются;
   * `avg_exec_price`/`commission` = None в повторе НЕ затирают ранее
     подтверждённые значения (обогащение, не потеря);
   * конфликт цены/комиссии учитывается ТОЛЬКО для повтора УЖЕ ТЕРМИНАЛЬНОЙ
     записи; между нетерминальными отчётами уточнение кумулятивной цены
     принимается (частичные исполнения по разным ценам).
3. `record_sent`/`record_status`/`record_uncertain`: kwarg `commission`
   (необязательный; существующие вызовы совместимы).

Монотонность `executed_lots`, идемпотентность INTENT, `open_orders`,
`figi_blocks_buy`, протокол APPLY_PREPARED/COMMITTED — НЕ изменялись
(проверено diff: эти блоки отсутствуют в diff).

### 4.2 `execution.py` — FIX-3 (ровно одна функция)

`_extract_commission()`: достоверный ноль (0.0) больше НЕ конвертируется в
None. Прежнее `value if value > 0 else None` теряло факт «комиссия реально
нулевая» и подменяла её модельной.

ВНИМАНИЕ (фиксируется в UNVERIFIED_AND_RISKS.md, R-1): функция ОБЩАЯ для BUY и
SELL — `resolve_closing` (SELL-путь B2) использует её для комиссии закрытия.
Семантическое изменение затрагивает и SELL-путь (для случая реально нулевой
комиссии закрытия). Это документированное, направленное на точность изменение,
но формально оно меняет поведение B2-механики в частном случае.

### 4.3 `main.py` — FIX-4

1. Новая функция `_enrich_buy_entry_metadata()` (перед `register_executed_buy`):
   заполняет ТОЛЬКО отсутствующие (None) `entry_actual_commission` и
   `execution_price` существующей записи позиции; перезапись запрещена; лоты,
   entry_price, SL/TP, состояние не меняются; событие
   `BUY_ENTRY_METADATA_ENRICHED`; немедленный `_save_state_checked`.
2. `register_executed_buy`, guard-ветка закрытых позиций (обе ветки
   `evidence_applied` и `evidence_closed_entry`): обогащение закрытой записи
   перед `return None` («воскрешение» по-прежнему запрещено).
3. `register_executed_buy`, активная ветка: противоречивая комиссия повторного
   отчёта (два достоверных разных значения) → `client.uncertain_state = True` +
   UNCERTAIN-запись реестра + сохранение state, БЕЗ перезаписи, `return existing`
   (fail-closed); затем — обогащение отсутствующих метаданных.
4. 4 вызова `ledger.record_status(...)` в `register_executed_buy` (позднее
   применение; разрешение неопределённости сверкой; идемпотентность; первичная
   регистрация): передаётся `commission=entry_commission`.
5. `_recover_late_csv_metadata`, условие `needs_poll`: строка CSV дополнительно
   считается неполной, когда обогащённая в позиции entry-комиссия ещё не
   отражена в `entry_commission_rub` строки (обогащение доходит до CSV и
   пересчитывает накопительный P&L). Сам механизм B2 не изменялся — только
   условие запуска опроса.

### 4.4 Тесты

* НОВЫЙ `test_buy_accounting_audit.py` — 23 теста (сценарии 01–20,
  синтетический WUSH-сценарий с явной пометкой «СИНТЕТИЧЕСКИЙ», 2 ledger-теста
  целостности). Все брокерские объекты — fake/stub, файлы — во временных
  каталогах, сеть не используется.
* `test_commission.py` и `tests/test_commission.py` — ОБНОВЛЕНЫ (FIX-5):
  `test_extract_commission_zero_returns_none` →
  `test_extract_commission_zero_returns_zero` (ожидание 0.0 по семантике
  FIX-3). Число тестов в файле сохранено (10 = 10); остальные 9 тестов файла
  не менялись; ни один тест не удалён.

### 4.5 Стратегия и торговая логика

`strategy.py`, `config.py`, `risk_manager.py`, `screener.py`, `telegram_bot.py`,
`tinkoff_client.py` — SHA256-идентичны baseline во всех трёх деревьях.
Порядок отправки заявок (`trading_cycle`), `close_position`, `poll_open_orders`,
`startup_recovery`, `reconcile`, `promote_recovery_positions`, `process_closing`
(кроме `needs_poll`) — не входят в diff B2 → BUY. SL/TP, риск-менеджмент,
скринер, фильтры, пороги — не изменялись.

---

## 5. Отнесение изменений по этапам (ТЗ §3, п.3–6)

| Этап | Изменения | Где подтверждено |
|---|---|---|
| B2 (v1–v7 CLOSE ACCOUNTING) | `main.py`, `execution.py`, `logger.py` + 7 B2-тестов (унаследованы BUY байт-в-байт, кроме 3 файлов FIX) | diff baseline→B2; appendix-копии байт-идентичны (проверено `diff -q` по 5 файлам) |
| BUY Accounting | FIX-1/2 (`order_ledger.py`), FIX-3 (`execution.py`), FIX-4 (`main.py`), FIX-5 (test_commission ×2), новый тест | diff B2→BUY |
| P0-3/P0-4/P0-5 | в составе baseline 051b10f уже присутствуют (комментарии «Партия P0-2/3/4/5» в main.py, файлы `test_p0_*.py`, отчёты `ОТЧЁТ_P0-3/4/5.md`); B2 и BUY их не меняли (diff не содержит правок этих блоков) | diff-анализ |
| SELL Safety / Stage 3 | в составе baseline 051b10f (ЭТАП 5Б §4.x, `ОТЧЁТ_ЭТАП3_SAFETY_FIX_SELL.md`, `test_v232_close_defects.py`, `test_v233_partial_sell_reopen_defect.py`, `test_stage1_*.py`); B2 и BUY не меняли (diff чист) | diff-анализ |
| Не описанные в отчётах | `state.json` (сброс) и `research_events.jsonl` (+160 событий) в BUY-кандидате — описаны в CHANGED_FILES.md §4 КАК идентичные baseline, что не соответствует фактам | собственные SHA256 (см. UNVERIFIED_AND_RISKS.md U-1/U-2) |
