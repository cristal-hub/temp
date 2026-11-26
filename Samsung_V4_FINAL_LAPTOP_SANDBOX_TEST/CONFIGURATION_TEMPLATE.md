# CONFIGURATION_TEMPLATE.md — шаблон конфигурации тестовой сборки

**Мандаты:** `STRATEGY LOGIC: UNCHANGED` · `RESEARCH ONLY` · `NO LIVE ORDERS`
**LAPTOP SANDBOX TEST BUILD — BROKER ORDER SUBMISSION DISABLED BY DEFAULT**

В ZIP НЕТ файла `.env` и НЕТ секретов. Файл создаётся пользователем вручную в
каталоге `candidate` (рядом с main.py). Ниже — шаблон с объяснением каждой строки.
Значения-заглушки вида `...` замените своими SANDBOX-токенами (не LIVE!).

## Шаблон `.env` (создать в candidate\)

```
# --- Обязательно ---
TINKOFF_API_TOKEN=ваш_sandbox_токен
TINKOFF_READONLY_TOKEN=ваш_readonly_токен

# --- Telegram (обязательны, т.к. ENABLE_TELEGRAM=True в config.py) ---
TELEGRAM_BOT_TOKEN=ваш_токен_бота
TELEGRAM_CHAT_ID=ваш_chat_id
TELEGRAM_ALLOWED_USER_ID=ваш_user_id

# --- Опционально ---
# Явно указать аккаунт песочницы (иначе будет использован первый найденный)
# TINKOFF_ACCOUNT_ID=
# Стартовый баланс для отчётности
# STARTING_BALANCE=
```

## Переменные РЕЖИМА (НЕ в .env — только в сеансе PowerShell)

| Переменная | Значение | Эффект |
|---|---|---|
| `SAMSUNG_V4_BUILD_MODE` | (не задана) | Режим A — SAFE START / READ-ONLY, заявки заблокированы (по умолчанию) |
| `SAMSUNG_V4_BUILD_MODE` | `SANDBOX_EXECUTION` | Режим B — ТОЛЬКО при наличии маркера `sandbox_execution.enabled` |
| любое другое значение | — | безопасно трактуется как Режим A (fail-closed; опечатка не включает заявки) |

```powershell
# задать на текущий сеанс (Режим B, после создания маркера):
$env:SAMSUNG_V4_BUILD_MODE = "SANDBOX_EXECUTION"
# убрать:
$env:SAMSUNG_V4_BUILD_MODE = $null
```

**Важно:** не добавляйте `SAMSUNG_V4_BUILD_MODE` в `.env`. Режим B включается
только парой «маркер-файл (создаётся вручную) + переменная сеанса», чтобы ни
одно случайное значение конфигурации не могло включить отправку заявок.

## Что задано в коде и НЕ меняется (стратегия/безопасность)

`config.py` (не редактировать в рамках проверки сборки):

* `USE_SANDBOX = True` — только песочница; `validate()` поднимает ошибку при попытке
  отключить песочницу («USE_SANDBOX=False запрещён. Только песочница.»);
* `PROFILE = "FORCE_TRADE"` и все индикаторы/пороги — исходная стратегия Samsung,
  **не изменялись** (`STRATEGY LOGIC: UNCHANGED`);
* `BE_TRAIL_ENABLED = False` — безубыток/трейлинг выключены (исходное состояние).

`tinkoff_client.py`: `TinkoffClient(..., use_sandbox=False)` поднимает
`SandboxRequiredError` — LIVE технически невозможен на уровне клиента.

`build_safety.py`: guard заявок в Режиме A блокирует `post_market_order`/`cancel_order`
ДО сетевого вызова (`OrderSubmissionDisabledError`).

## Fail-closed поведение (проверено тестами, ТЗ §7.2)

| Ситуация | Поведение |
|---|---|
| Токен отсутствует/пуст | `config.validate()` → RuntimeError с перечнем полей; safe_start: «БЕЗОПАСНЫЙ ОТКАЗ» (код 2) |
| Неверный токен | sandbox API-проверка safe_start сообщает отказ (код 2); заявки невозможны в Режиме A в любом случае |
| `.env` отсутствует | safe_start показывает источник «переменные окружения процесса» и поимённый список незаданных полей |
| Неизвестный режим (`SAMSUNG_V4_BUILD_MODE=...`) | безопасно SAFE_START + предупреждение в диагностике |
| Ошибка подключения/недоступность API | безопасный отказ с причиной; без повторов в Режиме A |
| Нет маркера Режима B | заявки заблокированы независимо от переменной режима |
