# CHANGED FILES — BUY ACCOUNTING AUDIT v1

База: кандидат `temp/samsung_B2_integrated_v1_v7` (Samsung `051b10f095d45c053492ca333449a9a9f518f33f` + B2 v1–v7 CLOSE ACCOUNTING).
B2-часть изменений в этом каталоге унаследована БЕЗ изменений
(см. `appendix_CHANGED_FILES_B2_v1_v7.md`, `appendix_FULL_DIFF_B2_v1_v7.patch`).
Ниже — только изменения, внесённые ЭТИМ аудитом (BUY ACCOUNTING).

Принципы: минимальность, только BUY ACCOUNTING, fail-closed, обратная
совместимость state.json/order_ledger.jsonl/CSV, сохранение B2 v1–v7.
Точный diff — `BUY_DIFF_vs_B2_candidate.patch`.

---

## 1. Production-файлы

### 1.1 `order_ledger.py` — FIX-1 + FIX-2

Изменения (3 участка):

1. **`RECORD_FIELDS`**: в КОНЕЦ добавлено поле `commission`
   (обратная совместимость: у старых записей значение None).
   Обоснование: фактическая комиссия BUY-исполнения ранее НЕ персистилась
   в реестре вовсе (терялась при перезапуске вместе с state.json);
   ТЗ-E требует различать 0 / позднее появление / отсутствие.
2. **`append()`**: поле `commission` включено в список копируемых полей записи;
   добавлен блок «BUY ACCOUNTING AUDIT (v1, FIX-1)»:
   - противоречие FIGI/стороны повторного отчёта той же заявки (тот же
     order_id) → статус UNCERTAIN с СОХРАНЕНИЕМ подлинных значений (раньше —
     молчаливая перезапись `_latest[oid]` — дефект D1);
   - `avg_exec_price`/`commission` повторного отчёта без значения НЕ затирают
     ранее подтверждённые (обогащение, не потеря — дефект D2);
   - противоречие цены/комиссии является конфликтом ТОЛЬКО для повтора
     УЖЕ ТЕРМИНАЛЬНОЙ заявки (исполнение заморожено — семантика B2
     `apply_close_execution`); между нетерминальными отчётами средняя цена
     кумулятивного исполнения легитимно уточняется (частичные исполнения по
     разным ценам) — уточнение принимается.
3. **`record_sent` / `record_status` / `record_uncertain`**: добавлен
   kwarg `commission` (передача в append). Существующие вызовы совместимы
   (kwarg необязательный).

Монотонность `executed_lots`, идемпотентность INTENT, протокол
APPLY_PREPARED/COMMITTED, `open_orders`/`figi_blocks_buy` — НЕ изменялись.

### 1.2 `execution.py` — FIX-3 (одна функция)

`_extract_commission()`: возвращается значение при ПРИСУТСТВИИ поля
`executed_commission`, включая достоверный НОЛЬ (0.0); None — только при
отсутствии/некорректности поля. Прежнее `value if value > 0 else None`
трактовало нулевую комиссию как «нет данных» (дефект D3, ТЗ-E).

Не изменялись: TrackedPosition, PositionState, register/register_recovery,
apply_close_execution, resolve_uncertain, validate_recovery_identity,
import/export_state — B2 v1–v7 CLOSE ACCOUNTING сохранён полностью.

### 1.3 `main.py` — FIX-4

1. **Новая функция `_enrich_buy_entry_metadata`** (перед
   `register_executed_buy`): позднее заполнение ТОЛЬКО отсутствующих
   `entry_actual_commission` / `execution_price` существующей записи позиции;
   значения не перезаписываются; лоты/entry_price/SL/TP/состояние не меняются;
   событие `BUY_ENTRY_METADATA_ENRICHED`; немедленное `_save_state_checked`.
2. **`register_executed_buy`, guard-ветка закрытых позиций** (обе ветки
   `evidence_applied` и `evidence_closed_entry`): перед `return None`
   вызывается обогащение закрытой записи отсутствующими метаданными входа
   (ТЗ-E; «воскрешение» по-прежнему запрещено).
3. **`register_executed_buy`, активная ветка** (OPEN/RECOVERY/CLOSING/UNCERTAIN):
   - противоречивая комиссия повторного отчёта (два достоверных разных
     значения) → `uncertain_state` + UNCERTAIN-запись реестра + сохранение
     state, БЕЗ перезаписи (fail-closed, ТЗ-B/11);
   - затем — обогащение активной позиции отсутствующими комиссией/ценой.
4. **`register_executed_buy`, 4 вызова `ledger.record_status`** (позднее
   применение, разрешение неопределённости сверкой, идемпотентность,
   первичная регистрация): передаётся `commission=entry_commission` —
   комиссия BUY персистится в реестре (FIX-2).
5. **`_recover_late_csv_metadata`, условие `needs_poll`**: строка CSV
   дополнительно считается неполной, когда обогащённая в позиции
   entry-комиссия ещё не отражена в `entry_commission_rub` строки → штатный
   B2-механизм восстановления обновляет СУЩЕСТВУЮЩУЮ строку и пересчитывает
   накопительный P&L (дефект D6; сам механизм B2 не изменялся — только
   условие опроса; поведение B2-тестов не изменилось).

Не изменялись: trading_cycle (порядок и логика отправки заявок),
close_position, poll_open_orders, startup_recovery, reconcile,
promote_recovery_positions, process_closing (кроме needs_poll), B2/B3-
механизмы, SL/TP, риск-менеджмент, скринер, фильтры, BUY-сигналы.

---

## 2. Тестовые файлы

### 2.1 `test_buy_accounting_audit.py` — НОВЫЙ (23 теста)

Полный BUY-набор по ТЗ раздела 3: сценарии 01–20, синтетический WUSH-сценарий
(помечен «СИНТЕТИЧЕСКИЙ») и 2 ledger-теста целостности (identity-конфликт,
нестирание цены). Все брокерские объекты — fake/stub; файлы — во временных
каталогах; без сети и без операций по счёту. Запуск:
`PYTHONPATH=. pytest test_buy_accounting_audit.py --import-mode=importlib`.

### 2.2 `test_commission.py` и `tests/test_commission.py` — ОБНОВЛЕНЫ (FIX-5)

Единственное изменение СУЩЕСТВУЮЩЕГО теста, обоснование: тест
`test_extract_commission_zero_returns_none` фиксировал дефектное поведение
«commission=0 → None» — прямое противоречие обязательному требованию ТЗ-E
(«наличие commission = 0 должно отличаться от отсутствующего значения»).
Тест переименован в `test_extract_commission_zero_returns_zero` и ожидает
достоверный 0.0 (поведение FIX-3). Остальные 8 тестов файла не менялись.
Копия `tests/test_commission.py` синхронизирована (оба файла участвуют в
прогоне). Ни один тест не удалён.

---

## 3. Отчётные файлы (новые, этот аудит)

`README.md`, `AUDIT_REPORT.md`, `ROOT_CAUSE_ANALYSIS.md`, `CHANGED_FILES.md`
(этот файл), `REGRESSION_COMPARISON.md`, `FULL_DIFF.patch` (diff Samsung →
каталог аудита, .py), `BUY_DIFF_vs_B2_candidate.patch` (точный diff этого
аудита), `BUY_TEST_RESULTS.txt`, `NEGATIVE_VALIDATION_BUY_TESTS.txt`,
`B2_TEST_RESULTS.txt`, `FULL_PYTEST_BASELINE.txt`, `FULL_PYTEST_FINAL.txt`,
`SHA256SUMS.txt`, `Samsung_BUY_Accounting_Audit_V1.zip`.

B2-документация кандидата сохранена без изменений под именами
`appendix_README_B2_v1_v7.md`, `appendix_CHANGED_FILES_B2_v1_v7.md`,
`appendix_FULL_DIFF_B2_v1_v7.patch`, `appendix_SHA256SUMS_B2_v1_v7.txt`,
`appendix_TEST_RESULTS_B2_v1_v7.txt` (переименованы, содержимое байт-в-байт).

---

## 4. Файлы, НЕ изменённые (сверка SHA256 с Samsung 051b10f)

`config.py`, `strategy.py`, `risk_manager.py`, `screener.py`,
`tinkoff_client.py`, `telegram_bot.py`, `close_all_positions.py`,
`conftest.py`, `tests/` (кроме `tests/test_commission.py`), `tools/`,
`requirements.txt`, runtime-файлы (`state.json`, `order_ledger.jsonl`,
`research_trades.csv`, `research_events.jsonl`, `sandbox_pnl.csv`) —
побайтово идентичны Samsung `051b10f`.

Изменённые production-файлы относительно Samsung (B2 + этот аудит):
`main.py`, `execution.py`, `logger.py` (только B2), `order_ledger.py`
(только этот аудит). `logger.py` этим аудитом НЕ менялся.

---

## 5. Обоснование соответствия ограничениям ТЗ

- B2 v1–v7 CLOSE ACCOUNTING: сохранён (96/96 B2-тестов без изменений тестов).
- Стратегическая логика, BUY-сигналы, SL/TP, риск-менеджмент, фильтры,
  скринер, порядок отправки заявок, B3: не затронуты (файлы не менялись).
- `strategy.py`, `risk_manager.py`, `config.py`: НЕ изменялись.
- Существующие тесты: не удалены; обновлён один тест-контракт (FIX-5) с
  обоснованием в разделе 2.2.
- Все изменения — только BUY ACCOUNTING; потенциальные дефекты вне области
  (AUDIT_REPORT §8) зафиксированы, но НЕ исправлялись.
