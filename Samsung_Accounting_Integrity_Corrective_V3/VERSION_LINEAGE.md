# VERSION_LINEAGE.md — происхождение версий (ТЗ V3 §0)

**Дата:** 2026-11-25
**Мандаты:** `STRATEGY LOGIC: UNCHANGED` · `RESEARCH ONLY` · `NO THRESHOLD IS OPTIMIZED` · `NO FILTER IS INSTALLED` · `NO LIVE ORDERS`
**GitHub:** READ-ONLY (никаких commits/branches/PR/uploads)

---

## 1. Источники и момент фиксации

| Репозиторий | Фиксация | Commit SHA | Tree SHA | Коммит-дата | Получен (UTC) |
|---|---|---|---|---|---|
| Основной Samsung source repository `cristal-hub/cristal-hub-Tsclp_v2.1_volatile_Samsung` | `HEAD`, `refs/heads/main` | `051b10f095d45c053492ca333449a9a9f518f33f` | `e83290cf6719020a568b59da2a5417b5f6ab68aa` | 2026-11-23 22:49:11 +0300 | 2026-11-25 18:35:40 |
| Staging repository `cristal-hub/temp` | `origin/main` | `4ff781ccce86cd0e8e3f413f088553d4847ab3c2` | `5e83a8c3703d90e4c6dafe4c440d219519e46d70` | 2026-11-25 20:17:53 +0300 | 2026-11-25 18:35:40 |
| `temp` ветка `buy-accounting-audit-75090` | snapshot | `03cb92d81823c77594fc9431ffc3114e7784da67` | `dc70280ebcb5d2cc5b9a3b4724e5814d90c4c461` | 2026-11-25 11:26:33 +0000 | 2026-11-25 18:35:40 |
| `temp` ветка `buy-accounting-audit-v2` | snapshot | `2ff53e871df2234a1da1f6ea224d6f8753db8b58` | `7766cdfcc057d19e0df3ea4422d6a76a949d7829` | 2026-11-25 14:41:40 +0300 | 2026-11-25 18:35:40 |

Способ получения: `git clone` (read-only), фиксация `git log -1 --format=...`, инвентаризация `SHA256` скриптом
`v3_source_discovery.py` (инвентарь: `evidence/source_inventory.json`).

Сопоставление с ТЗ: SHA256 `main.py` базового коммита (`8ed2293bb88b…`) и `execution.py` (`72b19783d1d1…`)
совпадают с заявленными в предыдущем ТЗ — pristine-база подтверждена.

## 2. Артефакты предыдущих итераций (проверка по содержимому, не по названию)

Ключевые производственные файлы (SHA256, первые 8 символов):

| Артефакт | main.py | execution.py | order_ledger.py | logger.py | Базис |
|---|---|---|---|---|---|
| **A0** main repo @ `051b10f` (pristine) | `8ed2293b` | `72b19783` | `766e1f37` | `266c937e` | — |
| **A1** temp: `samsung_merge_candidate` (B2 v1) | `053b289e` | — | — | — | A0 |
| **A2** temp: `samsung_merge_candidate_v2` (B2 v2) | `053b289e` | `1f1a93b4` | — | — | A1 |
| **A3** temp: `samsung_merge_candidate_v3` (B2 v3) | `7ae303f5` | `1f1a93b4` | — | `2e003a4a` | A2 |
| **A4** temp: `samsung_merge_candidate_v4` (B2 v4) | `d50e66e7` | `7e347f0c` | — | `df22ed91` | A3 |
| **A5** temp: `samsung_merge_candidate_v5` (B2 v5) | `00d7fdfc` | `2b4ca67f` | — | `df22ed91` | A4 |
| **A6** temp: `samsung_merge_candidate_v6` (B2 v6) | `2fcd992a` | `db62dd12` | — | `df22ed91` | A5 |
| **A7** temp: `samsung_merge_candidate_v7` (B2 v7) | `fac787ac` | `6fd0ed19` | `766e1f37` | `df22ed91` | A6 |
| **B** temp: `samsung_B2_integrated_v1_v7` | `fac787ac` | `6fd0ed19` | `766e1f37` | `df22ed91` | = A7 (байт-в-байт) |
| **C** temp: `Samsung_BUY_Accounting_Audit_V1` | `9cad7d50` | `03cec03b` | `0bdb3423` | `df22ed91` | B |
| **D** temp: `Samsung_BUY_Accounting_Corrective_Audit_V2/candidate` | `2a2dd3f8` | `03cec03b` | `0bdb3423` | `df22ed91` | C |
| **E** temp: `Samsung_Independent_Audit` | (отчёты/evidence, production-файлов в корне нет) | | | | отчётный пакет |
| Локальный `audit/samsung_baseline` (прошлый аудит) | `8ed2293b` | `72b19783` | `766e1f37` | `266c937e` | = A0 байт-в-байт |
| Локальный `audit_v2/ORIGINAL` (=BASELINE V2) | `9cad7d50` | `03cec03b` | `0bdb3423` | `df22ed91` | = C байт-в-байт |
| Локальный `audit_v2/FINAL` и доставленный V2 ZIP candidate | `2a2dd3f8` | `03cec03b` | `0bdb3423` | `df22ed91` | = D байт-в-байт |

Полный инвентарь: `evidence/source_inventory.json`; деревья — `evidence/tree_diffs.json`.

`strategя/config/риски/фильтры` (strategy.py `43906866`, config.py `6c4df6e4`, risk_manager.py `d1c72c2e`,
screener.py `6db12eb1`, tinkoff_client.py `fe69b045`, telegram_bot.py `8a98ab4c`) — **байт-в-байт одинаковы
во всех артефактах** от pristine до V2. Никаких откатов/конфликтов стратегической логики не обнаружено.

## 3. Доказательство аддитивности цепочки (diff-анализ)

Полные diff-файлы: `evidence/diffs/`.

| Переход | Файл | Изменения | Содержание | Вывод |
|---|---|---|---|---|
| A0→B | main.py | +1201/−34 | B2 close accounting v1–v7 | аддитивно |
| A0→B | execution.py | +633/−6 | B2: apply_close_execution, per-order cursor, CURSOR_IDENTITY_VERSION=2, close_applications | аддитивно |
| A0→B | logger.py | +408/−2 | B2-события | аддитивно |
| A0→B | order_ledger.py | 0/0 | без изменений | — |
| B→C | main.py | +105/−1 | BUY V1: FIX-4 (needs_poll + entry_commission), единая точка регистрации | аддитивно; −1 = заменённая строка needs_poll |
| B→C | execution.py | +5/−1 | BUY V1 FIX-3 (`_extract_commission`: 0.0 — достоверное значение) | аддитивно; B2-код не тронут |
| B→C | order_ledger.py | +68/−7 | BUY V1 FIX-1/FIX-2 (commission в реестре, metadata-guard) | аддитивно; секция B2 per-order protocol сохранена |
| C→D | main.py | +75/−18 | BUY V2 FIX-1 (`_enrich_buy_entry_metadata` validate→stage→commit) | аддитивно |
| C→D | execution.py, order_ledger.py, logger.py | 0/0 | байт-в-байт | FIX-1 локализован в main.py |

**Откатов ранее принятой логики не обнаружено** (проверены все пары переходов по содержимому diff).

## 4. VERSION_LINEAGE (итоговая таблица, ТЗ §0.3)

| Артефакт | Исходный commit/tree SHA | Основа | Производственные файлы | B2 v1–v7 | BUY V1 | BUY V2 | Статус |
|---|---|---|---|---|---|---|---|
| main repo @ `051b10f` | `051b10f` / `e83290cf` | — | 8ed2293b/72b19783/766e1f37/266c937e | НЕТ | НЕТ | НЕТ | **VERIFIED** |
| `samsung_merge_candidate_v1..v7` (temp) | рабочие папки без git-истории в коммите | A0..A6 последовательно | см. §2 | частично→да | НЕТ | НЕТ | **VERIFIED** (v7) / PARTIAL (v1–v6: промежуточные) |
| `samsung_B2_integrated_v1_v7` (temp @ main) | tree `0d6e257a` | A7 | fac787ac/6fd0ed19/766e1f37/df22ed91 | **ДА** | НЕТ | НЕТ | **VERIFIED** |
| `Samsung_BUY_Accounting_Audit_V1` (temp @ main) | tree `731eb7fa` | B | 9cad7d50/03cec03b/0bdb3423/df22ed91 | **ДА** (доказано diff B→C) | **ДА** | НЕТ | **VERIFIED** |
| `Samsung_BUY_Accounting_Corrective_Audit_V2/candidate` (temp @ main) | tree `72651442` | C | 2a2dd3f8/03cec03b/0bdb3423/df22ed91 | **ДА** | **ДА** | **ДА** | **VERIFIED** |
| `Samsung_Independent_Audit` (temp @ main) | tree `465956f2` | отчётный пакет (без production-файлов) | — | — | — | — | **VERIFIED** (отчёты) |
| ветка `buy-accounting-audit-75090` | `03cb92d8`/`dc70280e` | snapshot temp-содержимого (содержит `samsung_BUY_accounting_audit_v1`, удалённую в ветке v2) | совпадает с temp main | ДА | частично | НЕТ | **PARTIAL** (снапшот рабочей сессии) |
| ветка `buy-accounting-audit-v2` | `2ff53e87`/`7766cdfc` | snapshot temp main − папка v1 | совпадает с temp main | ДА | НЕТ (папка удалена) | НЕТ | **PARTIAL** (снапшот) |
| Локальные `audit_v2/ORIGINAL`, `BASELINE`, `FINAL`, V2 ZIP | локальные копии | C, D | совпадают по SHA | ДА | ДА | ДА | **VERIFIED** |

## 5. Единая каноническая база V3 (ТЗ §0.4–§0.5)

**Каноническая база = `Samsung_BUY_Accounting_Corrective_Audit_V2/candidate`** (tree `72651442`,
165 файлов), т.к. доказано, что она содержит:

1. последнюю полную Samsung source base (pristine @ `051b10f`);
2. B2 v1–v7 — production diff B→D супермножество diff A0→B (B2-код присутствует; B2-тесты 96 шт. в комплекте);
3. BUY V1 — diff B→C полностью входит в D;
4. BUY V2 FIX-1 — diff C→D присутствует (`validate → stage → commit`, main.py:3312+);
5. никаких неподтверждённых изменений не включено; runtime-файлы/опасные скрипты V2-пакета
   не входят в candidate (корректно по ТЗ V2 §7).

Фиксация базы (неизменяемая точка сравнения):

* `SOURCE_BASELINE_MANIFEST_SHA256.txt` — SHA256 всех 165 файлов;
* `SOURCE_BASELINE_TREE.txt` — дерево файлов;
* `BASELINE_DIFF.patch` (evidence/) — накопительный diff pristine → каноническая база (11 870 строк);
* воспроизводимость: контрольный SHA-прогон после всех тестовых циклов — **165 файлов байт-в-байт
  совпадают с манифестом** (тестовые прогоны не изменили базу).

Все исправления V3 выполнялись только в отдельной папке кандидата (`work/CANDIDATE`);
Samsung source repository не изменялся.

## 6. VERSION BLOCKER — не требуется

Противоречий происхождения не обнаружено; VERSION BLOCKER REPORT не выдавался. Несоответствий
фактической структуры заявленной в ТЗ нет: все 4 папки-артефакта найдены в `temp` repo `origin/main`,
их производственное содержимое соответствует ожиданиям.
