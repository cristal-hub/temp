# samsung_BUY_accounting_audit_v1 — BUY ACCOUNTING AUDIT (ЭТАП 1)

Дата: 2026-11-25. Режим: RESEARCH ONLY.

## Обязательные формулировки

```
STRATEGY LOGIC: UNCHANGED
RESEARCH ONLY
NO THRESHOLD IS OPTIMIZED
NO FILTER IS INSTALLED
NO LIVE ORDERS
OOS SEALED / H4 EXECUTION NOT AUTHORIZED
```

## Что это

Отдельный технический аудит **BUY ACCOUNTING** проекта Tsclp_v2.1_volatile_Samsung,
выполненный поверх **принятого кандидата интеграции B2 v1–v7**
(`temp/samsung_B2_integrated_v1_v7`). B2 CLOSE ACCOUNTING сохранён полностью
и без изменений; инцидент WUSH (BUY 495 лотов, исполнение подтверждено
брокером, локальная позиция отсутствовала, позднее появилась RECOVERY)
расследовался по коду и синтетическим тестам.

- **База (production-код)**: Samsung `cristal-hub-Tsclp_v2.1_volatile_Samsung`,
  ветка main, коммит `051b10f095d45c053492ca333449a9a9f518f33f`.
- **Основа аудита**: `temp/samsung_B2_integrated_v1_v7` — его CLOSE ACCOUNTING
  сохранён; фактическая интеграция B2 проверена файлами (diff дерева:
  изменены ровно `main.py`, `execution.py`, `logger.py` + 7 новых
  `test_b2_*.py`; остальные файлы побайтово идентичны Samsung `051b10f`),
  а не по README.
- **Samsung не изменён** (READ-ONLY). Все изменения — в этом каталоге
  staging-репозитория `cristal-hub/temp` (ветка `buy-accounting-audit-v2`).

## Что проверено (направления A–G ТЗ)

1. **A. BUY-исполнение → локальная позиция**: сигнал → INTENT → post →
   SENT → poll/partial/FILL-ветки → `register_executed_buy` (единая точка) →
   `monitor.register`/`register_recovery` → `_save_state_checked` →
   подтверждение в order_ledger. Все окна «ledger считает учтённым, позиция
   отсутствует» — `AUDIT_REPORT.md` §1.1.
2. **B. Идентичность заявки и FIGI**: client UUID vs биржевой ID, привязка
   order_id↔FIGI, две заявки одного FIGI, повторные/запоздавшие отчёты.
3. **C. Частичный BUY и повторная обработка**: частичные исполнения, рост
   cumulative, повторы, перезапуск между частичными.
4. **D. Persistence и restart recovery**: state.json × order_ledger.jsonl ×
   активные заявки брокера × позиции брокера; окна краха; источник истины.
5. **E. Комиссия и цена исполнения**: отсутствие / ноль / позднее появление /
   противоречие.
6. **F. BUY → CSV → P&L**: создание строки, trade_id/order_id, дубликаты,
   накопительный P&L при уточнении BUY-данных.
7. **G. Сверка с брокером и fail-closed**: адопция RECOVERY, дубли,
   неполные/противоречивые данные.

## Что изменено (минимальные BUY-фиксы, доказанные тестами)

| Fix | Файл | Дефект (доказан негативной валидацией) |
|---|---|---|
| FIX-1 | `order_ledger.py` (`append`) | повторный отчёт той же заявки молча перезаписывал FIGI/сторону и затирал ранее подтверждённую цену отсутствием данных |
| FIX-2 | `order_ledger.py` (RECORD_FIELDS, сигнатуры record_*) | фактическая комиссия BUY вообще не персистилась в реестре |
| FIX-3 | `execution.py` (`_extract_commission`) | комиссия 0.0 трактовалась как «нет данных» (подменялась модельной) |
| FIX-4 | `main.py` (`register_executed_buy`, `_recover_late_csv_metadata`) | поздняя BUY-комиссия/цена не обогащали существующую запись (активную и закрытую), противоречивая комиссия не была fail-closed |
| FIX-5 | `test_commission.py` (+ копия `tests/`) | существующий тест фиксировал дефектное поведение «0 → None»; обновлён на ожидание ТЗ-E (изменение существующего теста задокументировано в CHANGED_FILES.md) |

Полное обоснование — `CHANGED_FILES.md`; полный diff — `FULL_DIFF.patch`
(Samsung → каталог аудита; включает унаследованный B2-дифф);
точный diff этого аудита — `BUY_DIFF_vs_B2_candidate.patch`.

## Что НЕ изменено

- **B2 v1–v7 CLOSE ACCOUNTING** — без изменений: все 7 B2-тестовых файлов не
  модифицированы, 96/96 тестов проходят (см. `B2_TEST_RESULTS.txt`).
- `strategy.py`, `risk_manager.py`, `config.py`, `screener.py`,
  `tinkoff_client.py`, `telegram_bot.py`, `close_all_positions.py` —
  побайтово идентичны Samsung `051b10f` (SHA256 сверены, см. `SHA256SUMS.txt`).
- BUY-сигналы, условия входа, SL/TP, риск-менеджмент, фильтры/скринер,
  порядок отправки заявок, B3 — не затронуты.
- Реальные данные (`state.json`, `order_ledger.jsonl`, `research_trades.csv`,
  `research_events.jsonl`, `sandbox_pnl.csv`) — не изменялись (тесты
  изолированы во временные каталоги).

## Тестирование (сводка)

| Прогон | Результат |
|---|---|
| Baseline (кандидат B2, до BUY-фиксов), полный pytest | `74 failed, 662 passed, 1 error` |
| Негативная валидация: 23 новых BUY-теста на коде ДО фиксов | `7 failed, 16 passed` — доказаны 7 дефектных сценариев |
| Новые BUY-тесты ПОСЛЕ фиксов | `23 passed` |
| B2 v1–v7 (7 файлов, 96 тестов) ПОСЛЕ фиксов | `96 passed` (B2-тесты не изменялись) |
| Полный pytest ПОСЛЕ фиксов | `74 failed, 685 passed, 1 error` |
| Поимённое сравнение FAILED/ERROR с baseline | **0 новых, 0 исчезнувших** |
| Воспроизводимость baseline | поимённо идентичен `appendix_baseline_failed_names.txt` предыдущего исполнителя (после нормализации: 75 = 75, 0 расхождений) |

Примечания к окружению (задокументированы честно):
- прогон выполнялся `pytest --continue-on-collection-errors`: единственный
  `ERROR test_execution.py` (артефакт сбора корневой копии `test_execution.py`,
  резолвящей `ROOT = parent.parent`) присутствует и в baseline-прогоне
  предыдущего исполнителя (`appendix_FINAL_FULL_PYTEST.txt`: та же ошибка);
- из-за `__init__.py` в корне кандидата pytest поднимает `sys.path` до
  родительского каталога; при запуске внутри `temp/` родительский `temp/main.py`
  (старый артефакт прошлых слияний) затеняет `main.py` кандидата. Корректный
  запуск: `PYTHONPATH=<каталог кандидата> pytest --import-mode=importlib …`
  (флаг `--import-mode=importlib`).
- Окружение аудита: Python 3.12.16, pytest 9.0.2, pytest-asyncio 1.3.0,
  pandas 2.2.3 (SDK-зависимости подменяются штатными заглушками conftest).

## Результат расследования WUSH

**Первопричина инцидента НЕ подтверждена** реальными данными (их нет в
распоряжении аудита — см. `ROOT_CAUSE_ANALYSIS.md` §3 о требуемых данных).

Что показал аудит:
- в текущем кандидате все окна краха между подтверждением BUY брокером и
  регистрацией позиции покрыты восстановлением (startup_recovery проходы 1/1.5,
  адопция reconcile); позиция в таких сценариях появляется как RECOVERY, а не
  исчезает — это согласуется с фактом появления RECOVERY-позиции после
  инцидента;
- синтетический сценарий (`test_wush_synthetic_buy495_recovery`, помечен
  СИНТЕТИЧЕСКИЙ) воспроизводит: BUY 495 исполнен, ledger сохранён, state нет →
  ровно одна RECOVERY-позиция 495 лотов; повторные сверки и поздний повтор
  отчёта не дублируют и не удваивают;
- два наиболее согласованных кандидата первопричины — крах в окне
  «исполнение подтверждено → позиция не сохранена» на коде ДО введения
  восстановительного прохода 1.5, либо крах до `record_intent` (след в реестре
  отсутствует вовсе). Окончательный выбор требует реальных артефактов
  инцидента (order_ledger.jsonl, state.json, research_events.jsonl, логи).

**Не заявляется, что инцидент «решён».** Синтетический тест доказывает
поведение КАНДИДАТА, а не первопричину исторического инцидента.

## Состав каталога

| Файл | Назначение |
|---|---|
| `README.md` | этот файл |
| `AUDIT_REPORT.md` | полный анализ BUY-пути (A–G), дефекты, окна краха |
| `ROOT_CAUSE_ANALYSIS.md` | причины WUSH с уровнем доказанности каждой |
| `CHANGED_FILES.md` | список изменений и обоснование каждого файла |
| `REGRESSION_COMPARISON.md` | поимённое сравнение FAILED/ERROR с baseline |
| `FULL_DIFF.patch` | diff Samsung `051b10f` → каталог аудита (.py; включает унаследованный B2-дифф) |
| `BUY_DIFF_vs_B2_candidate.patch` | точный diff этого аудита (кандидат B2 → каталог) |
| `BUY_TEST_RESULTS.txt` | прогон 23 новых BUY-тестов (после фиксов) |
| `NEGATIVE_VALIDATION_BUY_TESTS.txt` | те же тесты на коде ДО фиксов (7 failed — доказательство дефектов) |
| `B2_TEST_RESULTS.txt` | прогон B2 v1–v7 (96 passed) |
| `FULL_PYTEST_BASELINE.txt` / `FULL_PYTEST_FINAL.txt` | полные логи pytest до/после |
| `SHA256SUMS.txt` | SHA256 изменённых файлов, тестов и отчётов |
| `test_buy_accounting_audit.py` | полный набор BUY-регрессионных тестов (23) |
| `main.py`, `execution.py`, `order_ledger.py`, `logger.py` | полный комплект production-файлов кандидата (для независимой проверки) |
| `test_commission.py`, `tests/test_commission.py` | обновлённые копии (FIX-5) |
| `appendix_*` | нетронутая документация пакета B2 v1–v7 |
| `Samsung_BUY_Accounting_Audit_V1.zip` | ZIP-архив всего каталога |

## Публикация в temp-репозитории (ограничение загрузки)

Git-push из среды аудита недоступен (в песочнице нет учётных данных git),
поэтому каталог выгружается в `cristal-hub/temp` через GitHub API (MCP) по
частям. Через API передаются ВСЕ отчёты, тесты и изменённые файлы, кроме
файлов, превышающих лимит размера вызова. Состав remote-каталога и способ
получить ПОЛНЫЙ каталог:

- **Полные изменённые production-файлы**: `order_ledger.py` — в составе патча
  (в составе патча); `main.py` и `execution.py` — восстанавливаются из
  remote-кандидата `samsung_B2_integrated_v1_v7/` применением
  `BUY_DIFF_vs_B2_candidate.patch` — патч в ZIP/локальном комплекте — (`patch -p1`; патч содержит полные diff'ы
  execution.py/main.py/order_ledger.py и новые тесты). `logger.py` этим
  аудитом не менялся (совпадает с кандидатом).
- **`BUY_DIFF_code_only_vs_B2_candidate.patch`** — компактный вариант патча
  (только production-код и обновлённые тест-контракты), выгружен в remote;
  новый тест-файл `test_buy_accounting_audit.py` выгружен отдельным полным
  файлом.
- **`FULL_DIFF.patch`** (623KB, Samsung → каталог) — в ZIP/локальном комплекте;
  B2-часть идентична `appendix_FULL_DIFF_B2_v1_v7.patch`.
- **Полные pytest-логи** (`FULL_PYTEST_BASELINE.txt`/`FULL_PYTEST_FINAL.txt`,
  по 362KB) — в ZIP/локальном комплекте; итоговые строки и ПОЛНЫЙ поимённый
  список 74 FAILED + 1 ERROR включены в `REGRESSION_COMPARISON.md`.
- **`Samsung_BUY_Accounting_Audit_V1.zip`** (полный каталог) — в локальном
  комплекте; SHA256 зафиксирован в `SHA256SUMS.txt`. Бинарные файлы (ZIP,
  PDF/DOCX предыдущих этапов, .7z) через текстовый протокол API не передаются;
  PDF/DOCX/.7z побайтово совпадают с копиями в `samsung_B2_integrated_v1_v7/`
  (SHA256 сверены).

## Ограничения

- Аудит выполнялся на коде и синтетических mock/stub-тестах (без сети,
  без реального брокера, без операций по счёту). Реальные отчёты брокера
  (семантика `executed_order_price` для частичных исполнений) не проверялись.
- Ни один порог, фильтр или параметр стратегии не оптимизировался и не
  устанавливался; торговая логика не изменялась.
