# TEST_RESULTS.md — результаты независимых прогонов

Мандаты: `RESEARCH ONLY`, `NO LIVE ORDERS`. Все прогоны выполнены в ИЗОЛИРОВАННЫХ
копиях каталогов (исходники не изменялись); runtime-файлы исходных клонов не
трогались; никаких заявок не отправлялось; сеть к брокеру не подключалась
(SDK отсутствует — заглушки conftest.py самого проекта).

## 1. Окружение и точные команды

| Параметр | Значение |
|---|---|
| ОС | Linux (sandbox аудита) |
| Python | 3.12.16 (`/home/z/.venv/bin/python3`) |
| pytest | 9.0.2; pytest-asyncio 1.3.0 |
| pandas | 2.2.3 |
| t_tech.invest (SDK) | ОТСУТСТВУЕТ — заглушки из conftest.py проекта |
| pandas_ta_classic | ОТСУТСТВУЕТ — заглушка conftest.py |
| python-telegram-bot | ОТСУТСТВУЕТ — заглушка conftest.py |
| Копии для прогонов | `<audit>/run/base`, `<audit>/run/b2`, `<audit>/run/buy` (полные копии соответствующих деревьев, без .git) |
| Конфигурация pytest | проект не содержит pytest.ini/setup.cfg/pyproject.toml — режим по умолчанию; asyncio-тесты используют `@pytest.mark.asyncio` (pytest-asyncio) |

Команды (рабочая директория = соответствующая копия):

```
# Полный набор (все три дерева):
python3 -m pytest -q --continue-on-collection-errors
#   (флаг необходим: pytest 9 прерывает сбор при 1 collection error;
#    прогоны кандидатов выполнены в том же режиме — их логи содержат
#    тот же 1 collection error и завершённый прогон)

# Официальный набор проекта (как run_tests.ps1):
python3 -m pytest tests -q --continue-on-collection-errors

# Только корневые тесты:
python3 -m pytest -q --continue-on-collection-errors --ignore=tests

# Целевые группы (BUY-копия):
python3 -m pytest test_b2_close_accounting.py test_b2_csv_recovery.py \
  test_b2_terminal_metadata_recovery.py test_b2_v4_accounting_consistency.py \
  test_b2_v5_identity_and_timestamp.py test_b2_v6_timestamp_identity_close_reason.py \
  test_b2_v7_cursor_version_and_alt_timestamp.py
python3 -m pytest test_buy_accounting_audit.py
python3 -m pytest test_p0_defect_fixes.py test_p0_batch2_late_execution.py test_p0_sell_id_fixes.py
python3 -m pytest test_v232_close_defects.py test_v233_partial_sell_reopen_defect.py \
  test_stage1_packet_v.py test_stage1_s1_telemetry.py test_manual_close_integration.py
```

Полные логи (с версиями и командой в шапке) приложены к архиву аудита:
`logs/full_base.log`, `logs/full_b2.log`, `logs/full_buy.log`,
`logs/logs_b2_v1_v7.log`, `logs/logs_buy_audit_tests.log`,
`logs/logs_sell_stage3_tests.log`, `logs/logs_tests_dir.log`.

## 2. Итоговые строки

| Прогон | Результат | Время |
|---|---|---|
| Полный набор, baseline 051b10f | **74 failed, 566 passed, 1 error** | 10.06s |
| Полный набор, B2-кандидат | **74 failed, 662 passed, 1 error** | 12.91s |
| Полный набор, BUY-кандидат | **74 failed, 685 passed, 1 error** | 12.96s |
| Официальный `tests/` (BUY) | 49 failed, 249 passed | 7.01s |
| Только корневые тесты (BUY) | 25 failed, 436 passed, 1 error | 4.98s |
| B2 v1–v7 (7 файлов, корень, BUY-копия) | **96 passed** | 1.41s |
| BUY Accounting (23 теста, BUY-копия) | **23 passed** | 0.35s |
| P0-файлы корня (BUY-копия) | 58 passed, **12 failed** | — |
| SELL Safety / Stage 3 / v232 / v233 / stage1 (BUY-копия) | **48 passed** | 0.66s |

«1 error» — collection error корневого `test_execution.py`
(`FileNotFoundError: …/run/execution.py`): файл предполагает расположение в
`tests/` (`ROOT = Path(__file__).parent.parent`). Одинаково во всех трёх
деревьях и в записанных логах кандидатов (предсуществующее).

## 3. Сверка с записанными логами кандидатов (поимённая)

| Сравнение | Метод | Результат |
|---|---|---|
| Мой прогон BUY vs `FULL_PYTEST_FINAL.txt` кандидата | список FAILED, нормализация «имя теста» (без текста исключения) | **74 = 74, ПОЛНОЕ СОВПАДЕНИЕ ИМЁН** |
| `FULL_PYTEST_FINAL.txt` vs `FULL_PYTEST_BASELINE.txt` кандидата | то же | 74 = 74, совпадение |
| Мой прогон B2 vs мой прогон BUY | то же | 74 = 74, совпадение |
| Мой прогон baseline vs мой прогон B2 | то же | 74 = 74, совпадение |

Пример верификации различий: расхождения при первом сравнении были ТОЛЬКО в
строках лога `ERROR root:main.py:5290 …` (лог-выход production-кода с
случайными UUID тестов), не в списке FAILED — после нормализации различий нет.

## 4. Классификация 74 падений (одинаковая для всех деревьев)

| Группа | Число | Причина | Тип |
|---|---|---|---|
| `test_p0_batch2_late_execution.py` (корень 11 + tests/ 12) | 23 | `TypeError: FakeClient.get_sandbox_order_state() got an unexpected keyword argument 'order_id_type'` — заглушки не обновлены после ЭТАП 5Б | устаревший тест-стаб |
| `tests/test_p0_defect_fixes.py` | 13 | та же причина | устаревший тест-стаб |
| `test_p0_sell_id_fixes.py::test_16_request_lookup_unavailable_fails_closed` | 1 | та же причина | устаревший тест-стаб |
| `test_buy_registration_fix2*.py` (корень 2 + tests/ 3, включая дубль `(1).py`) | 5 | та же причина | устаревший тест-стаб |
| `tests/test_main.py::test_trading_cycle_not_fill_but_executed_creates_position` | 1 | та же причина | устаревший тест-стаб |
| `test_screener.py` (корень 6 + tests/ 6) | 12 | SDK отсутствует: скринер возвращает None (заглушка conftest), assert-ы на содержимое | среда |
| `test_strategy.py` ADX (корень 3 + tests/ 3) | 6 | `AttributeError: <module 'pandas_ta_classic'> has no attribute 'adx'` — заглушка conftest без ta-атрибутов | среда |
| `test_persistence.py` (корень 2 + tests/ 2) | 4 | subprocess-тесты: state-снимки (AssertionError) | среда/платформа |
| `tests/test_main_helpers.py::test_process_closing_*` | 6 | ожидание `commission_source='model'` при PRICE_UNKNOWN, production пишет `'none'` (семантический дрейф теста) | устаревший тест |
| `tests/test_fail_closed.py::test_mixed_commission_source` | 1 | та же группа | устаревший тест |
| `tests/test_execution.py::test_partial_sell_then_second_sell_uses_own_cursor`, `test_terminal_partial_sell_reopens_remaining_position` | 2 | TypeError (заглушка) | устаревший тест-стаб |
| Collection error корневого `test_execution.py` | 1 | путь `parent.parent` при расположении в корне | дефект теста |

Ни одно из 74 падений не указывает на дефект production-кода кандидатов:
все воспроизводятся на НЕИЗМЕННОМ baseline 051b10f.

## 5. Целевые верификации (детально)

1. **Новые BUY-тесты (23)**: все прошли, включая TZ-01…TZ-20, синтетический
   WUSH и 2 ledger-теста. Лог приложен.
2. **B2 v1–v7 (96)**: все прошли на BUY-кандидате — B2 CLOSE ACCOUNTING
   сохранён (включая V6/V7 identity-валидацию cursor'ов).
3. **P0-тесты корня (58 passed / 12 failed)**: все 12 падений входят в
   предсуществующий набор 74 (проверено поимённо); новых падений нет.
   Устаревшие стабы не позволяют прогнать тесты P0-3/P0-4/P0-5 в этой ветке
   истории — см. UNVERIFIED_AND_RISKS.md U-3.
4. **SELL Safety / Stage 3 (48)**: все прошли (`test_v232_close_defects.py`,
   `test_v233_partial_sell_reopen_defect.py`, `test_stage1_packet_v.py`,
   `test_stage1_s1_telemetry.py`, `test_manual_close_integration.py`).
5. **Полный набор**: выполнен на всех трёх деревьях; ни один тест не был
   исключён из прогона; collection error не скрывался (отражён в итоговой
   строке и логах).

## 6. Ограничения прогонов (честно)

* SDK брокера, pandas_ta_classic, python-telegram-bot в среде аудита
  отсутствуют — поведение на реальном SDK НЕ проверялось (совпадает со средой
  прогонов самих кандидатов, что делает сравнение корректным, но ограничивает
  внешний охват).
* Windows-специфичные элементы (`.ps1`, subprocess-пути) не выполнялись.
* Никакие SANDBOX/LIVE-операции не выполнялись; `main.py` не запускался;
  запускался только pytest (сбор/тесты, без сетевых вызовов).
