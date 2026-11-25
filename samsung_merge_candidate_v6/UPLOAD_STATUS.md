# UPLOAD_STATUS — samsung_merge_candidate_v6 (GitHub-папка vs ZIP)

Дата: 2026-11-24. Папка `samsung_merge_candidate_v6/` в `cristal-hub/temp`
загружается ПОФАЙЛОВО подключённым GitHub-плагином (create_or_update_file,
ветка main). Полный пакет (22 файла) — в `Tsclp_B2_V6_candidate.zip`
(SHA256 `0de1af732b193a9bb49743427a2513a44d7f982d359ae219ed8f50f08d11330c`).

## Почему не все файлы пакета загружены в GitHub-папку напрямую

Загрузчик этой папки — MCP-инструмент `create_or_update_file` с параметром
`content` (текст файла целиком в ОДНОМ вызове инструмента). В этой среде
размер одного вызова ограничен: файлы крупнее ~90-100 КБ передать за один
вызов нельзя (обрывается генерация вызова). Ограничение СРЕДЫ ВЫЗОВА
инструмента, а не GitHub (API GitHub допускает до 100 МБ).

Поэтому файлы пакета разделены так:

## A. Загружено в GitHub-папку (побайтово, blob SHA-1 сверен с локальным)

| Файл | Размер | git blob SHA-1 |
|---|---|---|
| README.md | 5 777 | `1611625fd6992abb2e4df55f137f4b3ad84a0617` |
| TEST_RESULTS.txt | 4 226 | `fa96944cf92d0782e68154afadb637ab1ce13061` |
| appendix_V6_TESTS_OUTPUT.txt | 2 660 | `93c1f4d7655af46559b00dcace6571e9c6f2cc82` |
| appendix_baseline_failed_names.txt | 6 207 | `60308190a10b47be0c8f1e85755d0c5f200144b2` |
| appendix_final_failed_names.txt | 6 207 | `60308190a10b47be0c8f1e85755d0c5f200144b2` (идентичен baseline — это и есть результат сравнения) |
| appendix_B2_TESTS_OUTPUT.txt | 6 986 | `6efb880129ec0c41e2e290921ef4e698a4e8eb7d` |
| CHANGED_FILES.md | 11 821 | `5bde46be60a0bbb3e2a94b45cf01def08c52a907` |
| MERGE_REPORT.md | 12 137 | `58301eb524af2b1c71afd78a328465702bcd1f18` |
| FULL_DIFF.patch | 32 552 | `1c04ec342f168a69c18b78e0472f39db930f5b1b` |
| test_b2_v6_timestamp_identity_close_reason.py | 62 515 | `6aa99f807f1b777aa8584907bc62cc1c420920c9` |
| SHA256SUMS.txt | 1 935 | `e270db75c4cfbf6e320b395aaedde7244e8fde57` |

## B. Только в ZIP (превышают лимит одного вызова / дублируют v5)

| Файл пакета | Размер | Причина | Где взять / как проверить |
|---|---|---|---|
| main.py | 367 688 | 367 КБ — намного выше лимита вызова | ZIP. Или собрать: main.py из `samsung_merge_candidate_v5/` @ commit `faee75d53176ce7d1dad5f648950811d3cbe0b69` + `FULL_DIFF.patch` (git apply). Результат обязан иметь SHA256 `2fcd992a691947ad8afba7d4bf336d828b1ab6fd5cf8c4ba3acebc5450338aae` |
| execution.py | 109 658 | 110 КБ — выше лимита вызова | ZIP. Та же сборка: execution.py из v5 + FULL_DIFF.patch -> SHA256 `db62dd127e4ac06acd7061cbb90bcfb6e29187119fc59d2540dd1039d5f5cd8f` |
| logger.py | 32 411 | БЕЗ ИЗМЕНЕНИЙ vs v5 | Идентичен `samsung_merge_candidate_v5/logger.py` (SHA256 `df22ed916cb2eda10473cb78c2f93846d0be00c8a7ad5913a6bab8d9ee8ad4c5` — обе версии совпадают) |
| test_b2_close_accounting.py | 56 627 | БЕЗ ИЗМЕНЕНИЙ vs v5 | Идентичен файлу из `samsung_merge_candidate_v5/` |
| test_b2_csv_recovery.py | 50 121 | БЕЗ ИЗМЕНЕНИЙ vs v5 | Идентичен файлу из `samsung_merge_candidate_v5/` |
| test_b2_terminal_metadata_recovery.py | 28 793 | БЕЗ ИЗМЕНЕНИЙ vs v5 | Идентичен файлу из `samsung_merge_candidate_v5/` |
| test_b2_v4_accounting_consistency.py | 52 006 | БЕЗ ИЗМЕНЕНИЙ vs v5 | Идентичен файлу из `samsung_merge_candidate_v5/` |
| test_b2_v5_identity_and_timestamp.py | 46 676 | БЕЗ ИЗМЕНЕНИЙ vs v5 | Идентичен файлу из `samsung_merge_candidate_v5/` |
| appendix_BASELINE_FULL_PYTEST.txt | 361 663 | 361 КБ — выше лимита | ZIP. Полный baseline-лог прогона; краткая сводка — в TEST_RESULTS.txt п.1 |
| appendix_FINAL_FULL_PYTEST.txt | 361 663 | 361 КБ — выше лимита | ZIP. Полный final-лог прогона; краткая сводка — в TEST_RESULTS.txt п.2 |
| appendix_NEGATIVE_VALIDATION_OLD_CODE.txt | 86 764 | 87 КБ — выше лимита вызова в этой среде | ZIP. Итог: 15 failed, 1 passed (V6-O — регрессионный guard) |

## C. Целостность цепочки (аудит без ZIP)

Каждый SHA256 из `SHA256SUMS.txt` проверяем:
* маленькие файлы — прямо в этой папке (`sha256sum -c SHA256SUMS.txt`
  ругнётся только на отсутствующие крупные, перечисленные выше);
* `main.py` / `execution.py` v6 = соответствующий файл v5-папки
  (blob-хэши в git-дереве @ `faee75d...`) + `FULL_DIFF.patch`;
* «БЕЗ ИЗМЕНЕНИЙ»-файлы — побайтовое равенство с v5-папкой;
* полный пакет одним архивом — `Tsclp_B2_V6_candidate.zip`
  (SHA256 `0de1af732b193a9bb49743427a2513a44d7f982d359ae219ed8f50f08d11330c`).

## Подтверждение

STRATEGY LOGIC: UNCHANGED
RESEARCH ONLY
NO THRESHOLD IS OPTIMIZED
NO FILTER IS INSTALLED
NO LIVE ORDERS
OOS SEALED / H4 EXECUTION NOT AUTHORIZED
