# TEST_RESULTS.md — команды, окружение, результаты, exit codes

Мандаты: `RESEARCH ONLY` · `NO LIVE ORDERS`. Все прогоны выполнены в
ИЗОЛИРОВАННЫХ копиях каталогов (BASELINE — кандидат без исправлений,
FINAL — кандидат с исправлениями); runtime-файлы исходных клонов не
использовались как рабочие данные; никаких заявок не отправлялось; сеть
к брокеру не подключалась (SDK отсутствует — заглушки conftest.py проекта).

## 1. Окружение (идентичное для BASELINE и FINAL)

| Параметр | Значение |
|---|---|
| ОС | Linux (sandbox аудита) |
| Python | 3.12.16 |
| pytest | 9.0.2; pytest-asyncio 1.3.0 |
| t_tech.invest (SDK) | ОТСУТСТВУЕТ — заглушки conftest.py проекта |
| pandas_ta_classic | ОТСУТСТВУЕТ — заглушка conftest.py |
| python-telegram-bot | ОТСУТСТВУЕТ — заглушка conftest.py |
| BASELINE | `/audit_v2/BASELINE` (копия кандидата до исправлений) |
| FINAL | `/audit_v2/FINAL` (копия кандидата после исправлений) |
| Конфигурация pytest | pytest.ini/pyproject отсутствуют — режим по умолчанию |

## 2. Точные команды (рабочая директория = соответствующая копия)

```bash
# [1/5] BUY Accounting + новые тесты корректирующего аудита
PYTHONPATH=. python3 -m pytest test_buy_accounting_audit.py test_corrective_audit_v2.py -q --tb=short
# (для BASELINE файл test_corrective_audit_v2.py не существует — прогон
#  только test_buy_accounting_audit.py; негативная валидация нового файла
#  на BASELINE выполнена отдельно — см. §5)

# [2/5] B2 v1–v7
PYTHONPATH=. python3 -m pytest test_b2_close_accounting.py test_b2_csv_recovery.py \
  test_b2_terminal_metadata_recovery.py test_b2_v4_accounting_consistency.py \
  test_b2_v5_identity_and_timestamp.py test_b2_v6_timestamp_identity_close_reason.py \
  test_b2_v7_cursor_version_and_alt_timestamp.py -q --tb=short

# [3/5] SELL Safety / Stage 3
PYTHONPATH=. python3 -m pytest test_v232_close_defects.py test_v233_partial_sell_reopen_defect.py \
  test_stage1_packet_v.py test_stage1_s1_telemetry.py test_manual_close_integration.py -q --tb=short

# [4/5] P0-файлы корня
PYTHONPATH=. python3 -m pytest test_p0_defect_fixes.py test_p0_batch2_late_execution.py \
  test_p0_sell_id_fixes.py -q --tb=line --continue-on-collection-errors

# [5/5] Полный набор / официальный tests/
python3 -m pytest -q --continue-on-collection-errors --tb=no -rfEr
python3 -m pytest tests -q --continue-on-collection-errors --tb=no -rfEr
```

## 3. Итоговые строки (BASELINE vs FINAL)

| Прогон | BASELINE | FINAL | Разница |
|---|---|---|---|
| [1/5] BUY + corrective | 23 passed (exit 0) | **41 passed, 0 failed (exit 0)** | +18 новых тестов |
| [2/5] B2 v1–v7 | 96 passed (exit 0) | **96 passed (exit 0)** | без изменений |
| [3/5] SELL Safety/Stage 3 | 48 passed (exit 0) | **48 passed (exit 0)** | без изменений |
| [4/5] P0 корень | 12 failed, 58 passed (exit 1) | **1 failed, 69 passed (exit 1)** | 11 исправлены; 1 NOT VERIFIED |
| [5/5] Полный набор | 74 failed, 685 passed, 1 error (exit 1) | **36 failed, 741 passed, 1 error (exit 1)** | 38 failed устранены ПОИМЁННО; 0 новых |
| [5b] tests/ | 49 failed, 249 passed (exit 1) | **24 failed, 274 passed (exit 1)** | 25 failed устранены ПОИМЁННО; 0 новых |

«1 error» в полном наборе — предсуществующая collection error корневого
`test_execution.py` (`FileNotFoundError: …/execution.py` — файл рассчитан
на расположение в tests/: `ROOT = Path(__file__).parent.parent`),
присутствует в baseline и final (не скрывалась).

## 4. Поимённая сверка полных наборов

Метод: извлечение всех строк `FAILED`/`ERROR` из логов → сортировка →
`comm`. Файлы: `evidence/failed_names_baseline_full.txt` (75 строк),
`evidence/failed_names_final_full.txt` (37 строк).

* **Новые FAILED/ERROR в FINAL: 0** (`comm -13` — пусто).
* **Устранены в FINAL: 38** — полный список в REGRESSION_COMPARISON.md §2.
* **Оставшиеся 37 (36 FAILED + 1 ERROR) — ПОИМЁННО идентичны baseline**
  (`comm -12`): ни одно имя не изменилось.

## 5. Негативная валидация FIX-1 (новые тесты на СТАРОМ коде)

Команда (в BASELINE, файл теста временно скопирован, после прогона удалён):

```bash
PYTHONPATH=. python3 -m pytest test_corrective_audit_v2.py -q --tb=short
```

Результат: **3 failed, 15 passed** — падают ровно fail-режимные тесты
`test_fix1_a_save_failure_no_false_confirmation` (старый код возвращал True
при несохранённом state), `test_fix1_b_invalid_exec_price_no_partial_mutation`
(частичная мутация комиссии), `test_fix1_f_retry_after_save_failure_…`
(ложное подтверждение). Семантико-сохраняющие тесты (D/E/C/C2, SELL,
needs_poll) проходят на ОБОИХ кодах. Полный лог:
`evidence/negative_validation_old_code.txt`.

## 6. Прогон на СТАЖИРОВАННОМ candidate/ (архив)

Финальная проверка целостности: тестовый прогон на копии каталога
`candidate/` ИЗ АРХИВА (распакованного стенда):

```
17 файлов ключевых наборов: 254 passed, 1 failed
(единственный failed — известный NOT VERIFIED интеграционный тест)
```

Подтверждает: архив самодостаточен (заголовки импортов, инфраструктура,
исправленные заглушки), воспроизводимость результатов.

## 7. Классификация оставшихся 36 FAILED + 1 ERROR (все предсуществующие)

| Группа | Кол-во | Причина | Отношение к ТЗ |
|---|---|---|---|
| `test_screener.py` (root 6 + tests/ 6) | 12 | SDK отсутствует: скринер возвращает None (заглушка conftest), assert-ы на содержимое | вне области (среда) |
| `test_strategy.py` ADX (root 3 + tests/ 3) | 6 | заглушка pandas_ta_classic без ta-атрибутов | вне области (среда) |
| `test_persistence.py` (root 2 + tests/ 2) | 4 | subprocess-тесты: state-снимки (платформа) | вне области (среда) |
| `tests/test_main_helpers.py::test_process_closing_*` | 6 | семантический дрейф теста (commission_source 'model' при PRICE_UNKNOWN vs production 'none') — задокументировано предыдущим аудитом (D-5) | вне области (дрейф теста) |
| `tests/test_fail_closed.py::test_mixed_commission_source` | 1 | тот же дрейф | вне области |
| `tests/test_execution.py` (2 теста) | 2 | своя устаревшая заглушка `get_sandbox_order_state(self, oid)` | вне области 12 P0 (tests/-копии) |
| `tests/test_main.py::test_trading_cycle_not_fill_but_executed_…` | 1 | своя устаревшая заглушка | вне области 12 P0 |
| `tests/test_p0_batch2_late_execution.py::test_n3_…` | 1 | устаревшая tests/-копия переписанного корневого теста (дрейф копий) | вне области FIX-2 (не входит в 12) |
| `tests/test_p0_defect_fixes.py::test_defect4_…` | 1 | устаревшая tests/-копия обновлённого корневого теста (дрейф копий) | вне области FIX-2 |
| `test_p0_batch2_late_execution.py::test_integration_…` (root) | 1 | NOT VERIFIED — производственный конфликт нулевой цены | доказательства в evidence |
| `test_execution.py` (collection error) | 1 | дефект пути теста (`parent.parent`) | вне области |

Ни одно из оставшихся падений не указывает на дефект, внесённый
исправлениями настоящего аудита: все воспроизводятся на неизменённом
BASELINE (поимённая сверка — §4).

## 8. Ограничения

* SDK брокера отсутствует — поведение на реальном SDK не проверялось
  (совпадает со средой прогонов кандидата; сравнение корректно).
* Windows-специфичные элементы (.ps1) не выполнялись.
* Никакие SANDBOX/LIVE-операции не выполнялись; main.py не запускался;
  скрипты заявок не запускались.
