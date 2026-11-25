# DANGEROUS_SCRIPTS.md — потенциально опасные скрипты и их назначение

Метод: статический анализ (grep + чтение кода) всех скриптов кандидата и
baseline. НИ ОДИН скрипт НЕ запускался. Классификация по способности отправить
заявку / изменить счёт / изменить состояние.

Маркеры отправки заявок в кодовой базе: `TinkoffClient.post_market_order`
(tinkoff_client.py:555), `client.post_market_order(...)`, `cancel_order`
(tinkoff_client.py:646), sandbox pay-in (`AsyncSandboxClient.sandbox.pay_in`).

## 1. Скрипты, СПОСОБНЫЕ ОТПРАВИТЬ ЗАЯВКИ / ИЗМЕНИТЬ СЧЁТ (только SANDBOX)

| Скрипт | Действие | Защиты | Оценка |
|---|---|---|---|
| `close_all_positions.py` | РУЧНОЕ аварийное закрытие: отправляет SELL-заявки в песочнице (`post_market_order` через `TinkoffClient(use_sandbox=True)`) | `USE_SANDBOX`-проверка (строка 148: «USE_SANDBOX=False. Только песочница.»); интерактивное подтверждение `input("Введите YES…")` (строка 249); шапка «ТОЛЬКО SANDBOX. РЕАЛЬНЫЕ ОРДЕРА НЕ ОТПРАВЛЯЮТСЯ» | ОПАСНЫЙ при запуске вручную в sandbox-конфигурации; live-контуры блокированы проверкой USE_SANDBOX; запуск в аудите НЕ выполнялся |
| `pay_in.py` | Пополнение счёта ПЕСОЧНИЦЫ на 100 000 ₽ (`sandbox.pay_in`) | Проверка `USE_SANDBOX` (early return); проверка наличия `TINKOFF_ACCOUNT_ID`; интерактивное подтверждение `YES` | ОПАСНЫЙ умеренно (изменяет баланс песочницы); live исключён |
| `sandbox_topup.py` | Доведение баланса песочницы до 100 000 ₽ (`sandbox.pay_in`) | Проверка `USE_SANDBOX` (в config.validate / коде); Сверка `ACCOUNT_ID` с config (RuntimeError при несовпадении); **БЕЗ интерактивного подтверждения**; захардкоженный ACCOUNT_ID `538f670d-…` | ОПАСНЫЙ умеренно; меняет баланс песочницы молча при запуске |

## 2. Скрипты, ЗАПУСКАЮЩИЕ торгового робота (требуют оператора)

| Скрипт | Действие | Защиты |
|---|---|---|
| `start_after_tests.ps1` | pytest → при успехе и вводе оператором `SANDBOX` → запуск `main.py` (торговый цикл) | Тесты должны пройти (иначе отказ); явное подтверждение оператора вводом `SANDBOX`; предупреждения проверить config. Оценка: ОПАСНЫЙ при подтверждении — сам по себе ничего не отправляет до подтверждения |
| `main.py` | Торговый робот (цикл `trading_cycle`, отправка BUY/SELL) | Торговля только при наличии `trading.flag` (`is_trading_enabled`); флаг создаётся ТОЛЬКО командой Telegram /start (`start_trading()`); при `__name__ == "__main__"` только запуск `main()`; авто-старта торговли при импорте НЕТ (проверено: `import main` исполняет только определения; conftest импортирует main без побочных заявок — тесты это подтверждают) | 
| `telegram_bot.py` | /start создаёт `trading.flag`, /stop удаляет | Авторизация по `ALLOWED_USER_ID` (проверка `_authorized`); только 3 команды |

## 3. Скрипты, ИЗМЕНЯЮЩИЕ ФАЙЛЫ (не заявки)

| Скрипт | Действие | Оценка |
|---|---|---|
| `patch_samsung_main.ps1` | Скачивает `main.py` из GitHub (raw) и ЗАМЕНЯЕТ локальный файл; проверяет git-blob SHA1 (`fe974a98…`) до записи | Не отправляет заявок; изменяет production-файл локально. Использовать осознанно; в аудите не выполнялся |
| `check_config.ps1` | Вывод конфигурации | Безопасен (чтение) |
| `run_tests.ps1` | Запуск pytest из `.venv` (`pytest tests -v`) | Безопасен для заявок; НО запускает pytest в каталоге пакета — тесты могут дописать события в `research_events.jsonl` (см. UNVERIFIED_AND_RISKS.md U-2); рекомендуется запуск в копии |

## 4. Диагностические скрипты — READ-ONLY (проверено на отсутствие мутаций)

Все перечисленные проверены grep'ом на `post_|pay_in|pay_out|cancel_order|replace_sandbox`
— ноль совпадений; работают через sandbox READ-вызовы (`get_sandbox_*`) или
read-only токен:

* `check_sandbox.py`, `diagnose_sandbox.py`, `diag_max_lots.py`,
  `diag_operations.py`, `diag_order_state.py` (шапка: «НЕ ВЫЗЫВАЕТ
  post_market_order, cancel_order, pay_in»; ограничение числа API-запросов),
  `diag_unknown_position.py`, `check_shares.py`, `check_shares2.py`,
  `check_ma100.py`, `check_readonly.py` (read-only токен, поиск SBER),
  `read_sandbox_balance.py`, `preflight_check.py` (шапка: «ТОЛЬКО ЧТЕНИЕ. НЕ
  ОТПРАВЛЯЕТ ЗАЯВКИ. НЕ СОЗДАЁТ trading.flag. НЕ МЕНЯЕТ ПОРТФЕЛЬ»).

Примечание: диагностические скрипты НЕ входят в diff ни B2, ни BUY —
унаследованы от baseline байт-в-байт (проверено рекурсивным diff).

## 5. Тестовые файлы с вызовами отправки заявок

`test_tinkoff_client.py`, `test_b2_v5/v6/v7`, `test_buy_accounting_audit.py`,
`test_p0_*`, `test_v232/v233`, `test_manual_close_integration.py`,
`test_close_all_positions.py`, `test_main.py` — все вызовы
`post_market_order`/`cancel_order` выполняются на **fake/stub-клиентах**
(проверено выборочным чтением: FakeClient/FakeMoney классы; сеть не
используется). Реальных заявок отправить не могут.

## 6. Скрытые переключатели контура (проверено)

* SANDBOX/LIVE: `config.py` — `USE_SANDBOX` читается из окружения; `TinkoffClient(use_sandbox=True)`
  во всех тестах/диагностиках; производственный контур выбирается конфигом.
  Изменений config.py в B2/BUY НЕТ (SHA256 = baseline).
* Токены: только `os.getenv` (config.py:14–18); в пакете секретов нет
  (`.env` отсутствует; проверено рекурсивным списком).
* `trading.flag`: создаётся только `start_trading()` (main.py:845) и удаляется
  `stop_trading()` (main.py:856); `preflight_check.py` флаг не создаёт; тесты
  перенаправляют флаг в tmp_path (monkeypatch).
* `FORCE_TRADE` — имя ПРОФИЛЯ ФИЛЬТРОВ стратегии в config.py (ADX/MA/RSI
  пороги сигналов, не торговых заявок); значение унаследовано от baseline
  без изменений; не является обходом trading.flag.
* Автозаявки при импорте модулей: отсутствуют (единственный side effect
  импорта main — создание пустых журнальных файлов при первом вызове
  log_event/log_trade, что и так происходит при импорте logger; заявок нет;
  сетевых подключений нет).

## 7. Итоговая классификация

| Уровень | Скрипты |
|---|---|
| Отправляют заявки/меняют счёт (sandbox-only, с защитами) | `close_all_positions.py`, `pay_in.py`, `sandbox_topup.py` (без подтверждения — повышенное внимание) |
| Запуск торгового робота (ручной) | `start_after_tests.ps1`, `main.py` (с trading.flag), Telegram /start |
| Изменяют файлы (не заявки) | `patch_samsung_main.ps1` (замена main.py), `run_tests.ps1` (риск загрязнения журналов тестами) |
| READ-ONLY | все `check_*`, `diag_*`, `preflight_check.py`, `read_sandbox_balance.py` |
