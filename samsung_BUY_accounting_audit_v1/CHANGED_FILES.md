# CHANGED_FILES — реально изменённые и добавленные файлы

База: Samsung `cristal-hub-Tsclp_v2.1_volatile_Samsung` @ `051b10f095d45c053492ca333449a9a9f518f33f` (main).

## 1. Изменённые производственные файлы (3)

| Файл | Samsung baseline SHA256 | Интегрированный SHA256 | Строк (было → стало) |
|---|---|---|---|
| `main.py` | `8ed2293bb88bb96b196b451ff0dc468d9fdc96a856634907f5ee9191f2df6be6` | `fac787ac6d51b377efec35aff4122971ad681c3e9a463739e64e0c5938162777` | 4327 → 5543 |
| `execution.py` | `72b19783d1d1e811e51c7522ba60f524ecffb7b57f393c34efd2c033680d40d2` | `6fd0ed195392085c503d0d696e3a7d72d7cf0b691dd6bf29bf8f03a3be9ede00` | 1083 → 1734 |
| `logger.py` | `266c937e2946058e6255b6584aee5c26e4e34dadaffeffe755eca7435924f164` | `df22ed916cb2eda10473cb78c2f93846d0be00c8a7ad5913a6bab8d9ee8ad4c5` | 159 → 581 |

Интегрированные файлы побайтово равны производственным файлам B2-референса
`cristal-hub/temp/samsung_merge_candidate_v7` — то есть перенос содержит
ТОЛЬКО накопленный B2-дифф v1–v7 и ничего кроме.

## 2. Добавленные тест-файлы (7) — побайтово из temp/samsung_merge_candidate_v7

| Файл | SHA256 | Тестов |
|---|---|---|
| `test_b2_close_accounting.py` | `9fa798bda539bbb1d8386f9836d64d3e9cf892c630a676257eced8078a347bc3` | 20 |
| `test_b2_terminal_metadata_recovery.py` | `2f4ab482030e37808fcee4eca217f59b75dd27d084b542e8560fb717409be0f2` | 8 |
| `test_b2_csv_recovery.py` | `8de760c885dc147c660767fe59b2ba0f7058173db78087059ae6eaa8e29a6e77` | 14 |
| `test_b2_v4_accounting_consistency.py` | `6b75e5d501c6a653ca769ee17cd3cd99b33de49cb70f800737966ab0a387a93e` | 9 |
| `test_b2_v5_identity_and_timestamp.py` | `1c793deb40920da3232f473ebaf0b447cdd00ac00befa5f236014a523816f3fc` | 10 |
| `test_b2_v6_timestamp_identity_close_reason.py` | `4cc14ee9a8e2573b8f9384770375e696f68866000599c7e4c6d34660db6599df` | 16 |
| `test_b2_v7_cursor_version_and_alt_timestamp.py` | `13dad5593c15a17dd01b080c2f73c4a1b7e17a66ba653943f2bca915d5cbd7f4` | 19 |
| **ИТОГО** | | **96** |

## 3. Добавленная документация пакета

`README.md`, `MERGE_REPORT.md`, `TRANSFER_TABLE.md`, `SAMSUNG_PRESERVED.md`,
`KNOWN_LIMITATIONS.md`, `CHANGED_FILES.md`, `SHA256SUMS.txt`,
`TEST_RESULTS.txt`, `FULL_DIFF.patch`,
`appendix_BASELINE_FULL_PYTEST.txt`, `appendix_FINAL_FULL_PYTEST.txt`,
`appendix_baseline_failed_names.txt`, `appendix_final_failed_names.txt`,
`appendix_B2_TESTS_OUTPUT.txt`, `appendix_B2_V1_TESTS.txt` …
`appendix_B2_V7_TESTS.txt`, `appendix_NEGATIVE_VALIDATION.txt`.

## 4. Файлы, НЕ изменённые (выборочно, полная проверка — diff всего дерева)

`config.py`, `strategy.py`, `risk_manager.py`, `order_ledger.py`,
`tinkoff_client.py`, `screener.py`, `telegram_bot.py`, `conftest.py`,
`tests/` (все Samsung-тесты), `tools/`, `requirements.txt`,
runtime-файлы (`state.json`, `order_ledger.jsonl`, `research_trades.csv`,
`research_events.jsonl`, `sandbox_pnl.csv`) — побайтово идентичны
Samsung `051b10f`.

Инвентаризация: `diff -rq Samsung_051b10f кандидат` различает ТОЛЬКО
3 производственных файла и 7 новых тест-файлов.
