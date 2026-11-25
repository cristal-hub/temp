# README.md — Samsung Accounting Integrity Audit & Corrective V3

**Проект:** Tsclp_v2.1_volatile_Samsung
**Дата:** 2026-11-25
**Режим:** OFFLINE / LOCAL / RESEARCH ONLY

---

## Дословные мандаты (ТЗ §1)

```
STRATEGY LOGIC: UNCHANGED
RESEARCH ONLY
NO THRESHOLD IS OPTIMIZED
NO FILTER IS INSTALLED
NO LIVE ORDERS
```

GitHub — READ-ONLY: никаких commits/branches/PR/uploads; результат передан одним ZIP
непосредственно пользователю в чате GLM.

## Что это за пакет

Комплексный аудит целостности всей цепочки учёта (Broker report → Order Ledger →
Execution Monitor → Position → State Persistence → CSV → Recovery → Final Accounting) с
исправлением подтверждённых дефектов на **единой доказанной канонической базе**:

* происхождение каждой итерации (B2 v1–v7 → BUY V1 → BUY V2) доказано SHA256 и diff-ами
  (VERSION_LINEAGE.md);
* каноническая база заморожена манифестом 165 файлов (SOURCE_BASELINE_MANIFEST_SHA256.txt);
* исправления выполнены только в отдельном кандидате V3;
* полная регрессия: baseline 21 failed/756 passed/1 error → final **0 failed / 746 passed /
  0 errors** (поимённое сравнение — REGRESSION_COMPARISON.md);
* закрыт NOT VERIFIED пункт V2: интеграционный P0-тест исправлен на уровне
  производственного контракта (семантика цены 0.0 vs None), без изменения его утверждений.

## Структура архива

| Путь | Содержание |
|---|---|
| `README.md` | этот файл |
| `FINAL_VERDICT.md` | итоговый вердикт PASS/PARTIAL/FAIL с обоснованием |
| `VERSION_LINEAGE.md` | доказательство происхождения версий (ТЗ §0) |
| `SOURCE_BASELINE_MANIFEST_SHA256.txt` | SHA256 всех 165 файлов канонической базы |
| `SOURCE_BASELINE_TREE.txt` | дерево файлов канонической базы |
| `ACCEPTED_FIXES_MATRIX.md` | сохранность принятых исправлений (16/16) |
| `AUDIT_REPORT.md` | полный аудит по направлениям §5.1–§5.16 |
| `FIXES.md` | V3-исправления (production + тестовая инфраструктура) |
| `TEST_RESULTS.md` | результаты всех прогонов |
| `REGRESSION_COMPARISON.md` | поимённое сравнение baseline vs final |
| `UNVERIFIED_AND_RISKS.md` | честный список NOT VERIFIED и рисков |
| `OUT_OF_SCOPE_FINDINGS.md` | дефекты вне объёма (не исправлялись) |
| `DANGEROUS_SCRIPTS.md` | карантин опасных скриптов с обоснованием |
| `SHA256SUMS.txt` | SHA256 всех файлов архива |
| `FULL_DIFF.patch` | полный diff каноническая база → кандидат V3 |
| `candidate/` | кандидат V3: каноническая база + исправления (безопасная структура) |
| `tests/` | V3-дельта тестов (новые и изменённые файлы; полный набор — в candidate/) |
| `quarantine_NOT_FOR_EXECUTION/` | опасные скрипты + их mock-тесты (NOT FOR EXECUTION) |
| `evidence/` | логи прогонов, списки FAILED поимённо, manifests, diff-ы, трассировка дефекта |

## Быстрый старт (проверка кандидата)

```bash
cd candidate
python3 -m pytest -q            # полный набор: ожидается 746 passed, 0 failed
PYTHONPATH=. python3 -m pytest test_corrective_audit_v3.py -v   # 17 новых V3-тестов
```

Зависимости — `candidate/requirements.txt` (pandas-ta-classic и прочее — PyPI;
t-tech-investments — приватный пакет, при отсутствии подхватываются штатные
conftest-заглушки — это проверенный CI-режим проекта).

## Ключевые исправления V3 (детали в FIXES.md)

| ID | Что | Где |
|---|---|---|
| V3-1 | Цена исполнения = конечная и положительная, иначе None (0.0 — не цена) | execution.py `_extract_price` |
| V3-2 | Metadata-guard реестра: конфликт только между достоверными значениями; 0.0-цена не блокирует позднее обогащение; fail-closed сохранён | order_ledger.py `append` + валидаторы |
| V3-3 | NaN/±Inf: явная isfinite-валидация; невалидное значение = целостный отказ без мутации | main.py enrichment, execution.py `_extract_commission` |
| V3-T1 | Восстановлен отсутствовавший tests/conftest.py (subprocess-заглушки) | tests/conftest.py |
| V3-T2 | 8 устаревших tests/-копий синхронизированы с каноническими корневыми версиями | tests/ |
| V3-T3 | Устойчивое разрешение пути execution.py (снята collection-ошибка) | test_execution.py |

## Безопасность

* Опасные скрипты (закрытие позиций, сетевые запросы к брокеру, патч production-файлов)
  — только в `quarantine_NOT_FOR_EXECUTION/`, в кандидате отсутствуют (DANGEROUS_SCRIPTS.md).
* Секретов, токенов, реальных runtime-данных (state.json/order_ledger.jsonl/CSV) в архиве нет.
* Ни один опасный скрипт в ходе аудита не запускался; ни одного запроса к брокеру не было.
