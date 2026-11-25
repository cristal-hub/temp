# FIXES.md — исправления V3 (ТЗ V3 §6)

Порядок для каждого исправления: воспроизведение → минимальная правка → тесты на дефект →
отрицательные/граничные тесты → профильные тесты → полная регрессия → diff/SHA256.

---

## V3-1. `_extract_price()`: цена исполнения = конечная и положительная, иначе None

* **Файл:** `execution.py` (ExecutionMonitor._extract_price)
* **Дефект:** нулевая сообщённая цена (executed_order_price=0 при lots_executed>0 — штатная
  ситуация для CANCELLED-остатков) давала расчётную цену 0.0, которая записывалась в реестр как
  `avg_exec_price=0.0` и считалась «подтверждённой». Поздняя реальная цена вызывала ложный
  конфликт guard'а → UNCERTAIN (ТЗ §5.1). Побочно: переполнение давало ±Inf.
* **Воспроизведение:** трассировка ledger в интеграционном сценарии P0
  (`evidence/p0_trace_baseline_evidence.txt`): запись [2] `CANCELLED avg=0.0` → запись [3]
  `UNCERTAIN …avg_exec_price 0.0->100.0`; assert `UNCERTAIN == 'CANCELLED'` падал на строке 470.
* **Правка (минимальная):** после вычисления `price = total / (lots_executed * lot_size)`
  добавлено: `if not math.isfinite(price) or price <= 0: return None`.
* **Тесты:** test_v3_price_extract_zero_reported_price_is_none, test_v3_price_extract_negative_nonfinite_is_none;
  интеграционное закрытие §5.14 — корневой P0-тест (PASS без изменения утверждений).
* **Скоп изменений:** 1 hunk; `import math` добавлен.

## V3-2. Metadata-guard реестра: конфликт распознаётся только между ДОСТОВЕРНЫМИ значениями

* **Файл:** `order_ledger.py` (append(), блок BUY AUDIT v1 FIX-1) + 2 новых модульных валидатора.
* **Дефект:** guard трактовал любое числовое различие как конфликт: legacy-запись с avg=0.0
  блокировала позднее обогащение реальной ценой (та же цепочка §5.1 на уровне реестра);
  новое невалидное значение (0.0-цена, NaN, ±Inf) могло затереть подтверждённое.
* **Правка:** `_valid_execution_price(v)` = конечное и > 0; `_valid_commission(v)` = конечное и ≥ 0
  (**0.0-комиссия остаётся подтверждённым значением** — семантика BUY V1 FIX-3 не изменена).
  Логика guard'а: новое None/невалидное → сохранить прежнее валидное (само невалидное не
  записывается); прежнее отсутствует/невалидно или отчёт нетерминальный → обогащение новым
  валидным значением; два различных валидных на терминальной заявке → UNCERTAIN + сохранение
  прежнего (fail-closed не ослаблен).
* **Тесты:** V3-тесты 3–9, 11–12 (legacy-0.0 обогащение, настоящее противоречие fail-closed,
  0.0-цена не затирает подтверждённую, P0-сценарий реестра, идемпотентность повтора, SELL-зеркало,
  комиссия 0.0 → конфликт, None не затирает 0.0).
* **Скоп:** 1 hunk в append() + блок валидаторов после констант статусов; `import math`.

## V3-3. NaN/±Infinity: явная валидация конечности

* **Файлы:** `main.py` (`_enrich_buy_entry_metadata`, шаг 1 валидации), `execution.py`
  (`_extract_commission`).
* **Дефект:** `float("inf")` проходил `> 0`/`>= 0` → инф-комиссия/цена могли попасть в State;
  `_extract_commission` мог вернуть ±Inf (попал бы в ledger/CSV); NaN отсекался только неявно.
* **Правка:** `math.isfinite` в валидации enrichment (невалидное значение → операция ЦЕЛИКОМ
  неудачна, объект не изменяется — семантика FIX-1 V2 сохранена) и в `_extract_commission`
  (неконечное → None = отсутствие подтверждённого значения).
* **Тесты:** V3-тесты 13–17.
* **Скоп:** 2 hunks; `import math` в main.py.

## V3-T1. tests/conftest.py — отсутствующий shim SDK-заглушек

* **Дефект (§5.15):** subprocess-скрипты test_persistence.py (root и tests/) выполняют
  `import tests.conftest` + `_install_stubs()`, но файла `tests/conftest.py` в дереве не было
  (заглушки — только в корневом conftest.py, чья шапка самоидентифицируется как
  «tests/conftest.py»). Оба subprocess-теста падали с ModuleNotFoundError('t_tech') независимо
  от проверяемой логики.
* **Правка:** создан `tests/conftest.py`, реэкспортирующий `_install_stubs` из корневого
  conftest (единственный источник истины; дублирования логики нет; установка идемпотентна —
  sys.modules.setdefault). Утверждения тестов не менялись.
* **Тесты:** 4 persistence-теста (2 root + 2 tests/) — PASS.

## V3-T2. Синхронизация 8 устаревших tests/-копий с каноническими корневыми версиями

* **Доказательство устаревания:** для каждой пары root↔tests/ diff показал, что копия — старый
  снапшот корневой версии (root длиннее; различия = обновления, внесённые более поздними
  итерациями: ЭТАП 5Б `order_id_type` в FakeClient, pytest-изоляция monkeypatch вместо
  прямых присваиваний, ТЗ-5 `exit_price_confirmed` в setup, ADX config-моки). Корневые версии
  проходят на текущем production — они и есть канонический контракт.
* **Правка:** `tests/{test_strategy, test_main_helpers, test_fail_closed, test_p0_defect_fixes,
  test_p0_batch2_late_execution, test_main, test_persistence}.py` := корневая версия
  (байт-в-байт); ни одно утверждение не ослаблено; ни один тест не удалён.
* **Результат:** 15 тестов tests/-копий перестали падать (6 main_helpers + 1 fail_closed +
  1 p0_defect_fixes + 2 p0_batch2 + 3 strategy + 1 main + 1 persistence-копия с shim).

## V3-T3. test_execution.py: устойчивое разрешение пути к execution.py

* **Дефект:** `ROOT = Path(__file__).parent.parent` работал только для tests/-копии; корневая
  копия падала на collection с FileNotFoundError (path над каталогом проекта) — 10 тестов
  не собирались (ERROR).
* **Правка:** ROOT = ближайший каталог, где лежит execution.py (`_HERE if (_HERE/'execution.py').is_file()
  else _HERE.parent`). Утверждения не менялись. Root (10 тестов) и tests/-копия (10) — PASS.

## Ограничения и отказы от правок

* B2 accounting-код не изменялся (см. AUDIT_REPORT §5.3): причина изменений только в
  `_extract_price`/`_extract_commission`/append-guard, общих для BUY/SELL путей.
* Стратегия/фильтры/риски/пороги — без изменений (SHA256 совпадают с pristine).
* Ни один интерфейс production-функций не изменён (сигнатуры прежние; `import math` — единственное
  импортное добавление).
* Дефекты вне согласованного объёма — в OUT_OF_SCOPE_FINDINGS.md (production-код по ним не менялся).
