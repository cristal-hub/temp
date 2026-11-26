# SAFETY_MODEL.md — как устроена безопасность laptop-сборки V4 (для независимой проверки)

Назначение: дать проверяющему (в т.ч. в staging-репозитории) точную карту
защитных механизмов сборки и мест их проверки.

## 1. Слои блокировки LIVE (независимые)

| Слой | Место | Механизм |
|---|---|---|
| 1. Конфигурация | `config.py::validate()` | `USE_SANDBOX=False` → RuntimeError («Только песочница») |
| 2. Клиент | `tinkoff_client.py::TinkoffClient.__init__` | `use_sandbox=False` → `SandboxRequiredError`; все заявки идут только через `client.sandbox.post_sandbox_order` |
| 3. Сборка | `build_safety.py::assert_sandbox_only` | явная проверка в `main()` и `safe_start.py` |
| 4. Режим сборки | `build_safety.py::install_order_guard` | в Режиме A методы `post_market_order`/`cancel_order` замещаются на защитные функции на ЭКЗЕМПЛЯРЕ клиента → `OrderSubmissionDisabledError` ДО сети |

## 2. Режимы

* **A — SAFE START / READ-ONLY (по умолчанию):** входная точка `safe_start.py`
  (конфигурация, зависимости, read-only API-проверка, локальные данные, само-тест
  блокировки). `main.py` в Режиме A тоже защищён guard'ом — любые попытки заявок
  отклоняются.
* **B — CONTROLLED SANDBOX EXECUTION (выключен):** активен только при
  (маркер-файл `sandbox_execution.enabled` И env `SAMSUNG_V4_BUILD_MODE=SANDBOX_EXECUTION`).
  Оба условия создаются вручную (`enable_sandbox_execution.py` + переменная сеанса).
  Неизвестное значение env → fail-closed (Режим A). В поставке маркера НЕТ.

## 3. Точки вызова заявок и их покрытие guard'ом

Все отправки/отмены в production-коде проходят через два метода `TinkoffClient`:
* `post_market_order` — BUY (`register_executed_buy`-путь: этап 4.1/заявки; входы
  `trading_cycle`) и SELL (`close_position`);
* `cancel_order` — отмена остатков (`poll_open_orders`).
Guard подменяет ОБА метода на экземпляре → покрытие полное. Список методов —
`build_safety.GUARDED_METHODS`; тест `test_guard_blocks_post_and_cancel_in_safe_start`.

## 4. Что в Режиме A остаётся «читающим»

`safe_start.py`: `users.get_accounts`, `operations.get_positions` (только чтение;
аккаунт НЕ создаётся — отличие от `main()`, который при первом запуске создаёт
sandbox-аккаунт). Сетевых записывающих вызовов в Режиме A нет.

## 5. Карта тестов безопасности

`candidate/test_v4_safety_build.py` (18 тестов): режимы, fail-closed, guard, LIVE-блокировка,
safe_start (pass/fail/секреты/Режим B), контракт «нет торгового цикла в safe_start»,
py_compile, чистый импорт main, fail-closed конфигурации в чистой среде.
`candidate/test_v4_integration_integrity.py` (8): защита от дубля позиции, stale close order.
