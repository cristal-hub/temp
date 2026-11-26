# VERSION_LINEAGE.md — происхождение сборки V4 (ТЗ V4 §1)

**Мандаты:** `STRATEGY LOGIC: UNCHANGED` · `RESEARCH ONLY` · `NO THRESHOLD IS OPTIMIZED` ·
`NO FILTER IS INSTALLED` · `NO LIVE ORDERS`
**LAPTOP SANDBOX TEST BUILD — BROKER ORDER SUBMISSION DISABLED BY DEFAULT**

---

## 1. База V4 — принятый кандидат V3

| Свойство | Значение |
|---|---|
| База V4 | `Samsung_Accounting_Integrity_Corrective_V3` (принятый кандидат, вердикт V3: PASS) |
| Артефакт базы | ZIP `Samsung_Accounting_Integrity_Corrective_V3.zip` |
| SHA256 ZIP базы | `a2aa6a699382e7056a16c67575e14224c262846ec3734b232413f1c0f1ceb6a1` |
| Файлов в ZIP | 236 (в т.ч. 144 в `candidate/`) |
| Соответствие | содержимое ZIP байт-в-байт совпадает с пакетом аудита V3 (проверено
полной инвентаризацией SHA256: zip-only=0, pkg-only=0, content-diff=0) |
| Итоговое состояние V3 | 746 passed / 0 failed / 0 errors (полный набор после карантина) |

V4 создана **из ZIP принятого кандидата V3**, а не повторным копированием старого
Samsung и не возвратом к V2 (ТЗ §1). Возврат к V2 не выполнялся ни в какой форме.

## 2. Корневая родословная (переносится из VERSION_LINEAGE.md V3)

| Слой | Статус в V3 | Комментарий |
|---|---|---|
| Pristine main repo `cristal-hub/Tsclp_v2.1_volatile_Samsung` @ commit `051b10f095d45c053492ca333449a9a9f518f33f`, tree `e83290cf6719020a568b59da2a5417b5f6ab68aa` | VERIFIED | исходная версия Samsung; GitHub — только чтение |
| B2 integrated v1–v7 | VERIFIED | per-order cursor, close_applications, strict recovery identity, fail-closed и др. — 96/96 тестов |
| BUY Accounting Audit V1 | VERIFIED | FIX-1..FIX-3 — 23/23 |
| BUY Accounting Corrective Audit V2 | VERIFIED | 12 P0-падений, BASELINE-FINAL — база V3 |
| Independent Audit | VERIFIED (част.) | PARTIAL только для git-снапшотов рабочих temp-веток, на цепочку не влияет |
| Corrective V3 | VERIFIED | V3-1/V3-2/V3-3 + T1/T2/T3; P0 12/12; 746p/0f/0e |

Детали первичной цепочки (SHA256/diff каждого артефакта) — в
`VERSION_LINEAGE.md` пакета V3; в V4 не пересматривались и не изменялись.

## 3. Проверка базы перед началом работ (ТЗ §1.1–1.4)

Выполнено до внесения ЛЮБЫХ изменений:

1. **SHA256 всех файлов V3 зафиксированы** — `evidence/manifests/v3_inventory.txt`
   (236 файлов).
2. **Список всех файлов кандидата сформирован** — 144 файла в `candidate/` V3;
   полный список — там же.
3. **Исходные изменения V3 присутствуют** — проверено по коду и тестам:
   * `execution.py` `_extract_price`: конечность+положительность (`import math`, V3-1) — присутствует;
   * `order_ledger.py`: `_valid_execution_price`/`_valid_commission`, guard «конфликт только
     между достоверными» (V3-2) — присутствуют;
   * `main.py` `_enrich_buy_entry_metadata`: `math.isfinite`-валидация целиком до мутации (V3-3) — присутствует;
   * `tests/conftest.py` shim (V3-T1), синхронные tests/-копии (V3-T2), path-fix test_execution (V3-T3) — присутствуют;
   * 17 тестов `test_corrective_audit_v3.py` — присутствуют и проходят (17 passed).
4. **Сохранность ранее принятых исправлений** — B2 v1–v7 (маркеры v2.3.4–v2.3.10 в
   `main.py`/`execution.py`), BUY V1/V2 (FIX-1/FIX-2/FIX-3), SELL Stage 3, P0 late execution —
   подтверждаются (а) по коду, (б) профильными прогонами на неизменённой базе:
   BUY 41, B2 96, SELL Stage 3 48, P0 70, V3 17 — все green и в BASELINE, и в V4
   (`reports/TEST_RESULTS.md`). production-файлы `strategy.py`, `config.py`,
   `risk_manager.py`, `screener.py`, `telegram_bot.py`, `tinkoff_client.py`,
   `logger.py`, `execution.py` — **байт-в-байт совпадают с V3** (проверено cmp).
5. **Рабочая копия V4 создана отдельно** — все изменения только в ней; исходный
   Samsung и пакет V3 не изменялись.

## 4. Изменения V4 относительно базы (сводка)

Полный diff — `evidence/diffs/FULL_DIFF_V3_to_V4.patch` (3 изменённых + 6 новых файлов).

| Тип | Файлы | Характер |
|---|---|---|
| Production (изменено) | `order_ledger.py` | V4-1: валидация финансовых значений при ПЕРВОЙ записи (P1, ТЗ §2); OOS-3: документирующий комментарий |
| Production (изменено) | `main.py` | V4-2: подключение guard'а заявок в `main()` (2 строки) + импорт `build_safety`; OOS-4: дублирующее множество терминальных SELL-статусов удалено (единый источник в `execution.py`) |
| Production (новый) | `build_safety.py`, `safe_start.py`, `enable_sandbox_execution.py` | LAPTOP SANDBOX TEST BUILD: Режим A по умолчанию, техническая блокировка отправки заявок, Режим B — только явная процедура (ТЗ §7) |
| Тест-инфра (изменено) | `conftest.py` | V4-3: autouse-фикстура изоляции runtime-путей (P2, ТЗ §5, OOS-1) |
| Тесты (новые) | `test_v4_order_ledger_first_append.py` (17), `test_v4_safety_build.py` (18), `test_v4_integration_integrity.py` (8) | 43 теста: P1-контракт, режимы сборки, группы 22/24 аудита §4 |

Статус происхождения V4: **VERIFIED** — база доказана SHA256/инвентаризацией,
изменения минимальны и полностью задокументированы, конфликтов версий и
необъяснимых файлов нет.

## 5. Неоднозначности/блокеры

Не обнаружены. VERSION BLOCKER REPORT не требовался: база V3 единственная
и доказанная, все принятые исправления на месте, конфликтов веток/откатов нет.
