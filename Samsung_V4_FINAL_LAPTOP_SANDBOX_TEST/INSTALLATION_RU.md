# INSTALLATION_RU.md — установка тестовой сборки Samsung V4

**Мандаты:** `STRATEGY LOGIC: UNCHANGED` · `RESEARCH ONLY` · `NO LIVE ORDERS`
**LAPTOP SANDBOX TEST BUILD — BROKER ORDER SUBMISSION DISABLED BY DEFAULT**

Подробные пояснения — в `LAPTOP_TEST_RUNBOOK_RU.md`. Здесь — краткая
последовательность установки и первичной проверки.

## 1. Требования

* Windows 10/11 (проверялось в среде аудита только статически — см. §7).
* Python 3.12.x (`python --version`).
* ~1 ГБ свободного места.
* Сетевой доступ к PyPI для установки зависимостей; для работы с брокером —
  приватный SDK `t-tech-investments==1.51.0` (как в рабочем окружении Samsung).

## 2. Установка

```powershell
mkdir C:\Samsung_V4_TEST
Expand-Archive -Path "$env:USERPROFILE\Downloads\Samsung_V4_FINAL_LAPTOP_SANDBOX_TEST.zip" -DestinationPath C:\Samsung_V4_TEST
cd C:\Samsung_V4_TEST\Samsung_V4_FINAL_LAPTOP_SANDBOX_TEST\candidate
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Если строка `t-tech-investments` не установилась (приватный пакет) — установите
остальные зависимости по отдельности и продолжите: тесты пройдут на штатных
заглушках; проверка API сообщит об отсутствии SDK безопасным отказом.

## 3. Конфигурация

1. Создайте `.env` в каталоге `candidate` по шаблону `CONFIGURATION_TEMPLATE.md`
   (в корне сборки). В ZIP шаблона и секретов НЕТ — файл создаётся пользователем.
2. Проверка конфигурации без сети:

```powershell
python safe_start.py --no-api
```

Ожидается «SAFE START завершён…» (раздел API — ПРОПУЩЕНО). При «БЕЗОПАСНЫЙ ОТКАЗ» —
исправьте причину, указанную в выводе (перечень отсутствующих полей выводится поимённо).

## 4. Первичная проверка (без брокера)

```powershell
python -m pytest -q
```

Ожидание: `789 passed`, `0 failed, 0 errors` (в среде без python-telegram-bot/
pandas-ta-classic число может отличаться; FAILED/ERROR быть не должно).

## 5. Проверка с брокером (только чтение)

```powershell
python safe_start.py
```

Подключение к SANDBOX API, список аккаунтов (id маскируются), счётчик позиций,
само-тест блокировки заявок. Торговый цикл не запускается.

## 6. Каталоги и файлы, которые создаёт сборка

* В каталоге `candidate`: `.venv\` (окружение), `.env` (секреты — создать вручную),
  runtime-файлы приложения (`state.json`, `order_ledger.jsonl`,
  `research_events.jsonl`, `research_trades.csv`) — только при работе main.py.
* Ничего вне папки сборки установка не создаёт (в системный Python ничего
  не ставится — всё в `.venv`).

## 7. Что проверено/не проверено по Windows (честная фиксация)

* Проверено в среде аудита (Linux): py_compile всех файлов, чистый импорт `main`
  в subprocess, отсутствие Unix-only API в production-коде, UTF-8 исходники,
  PowerShell-команды RUNBOOK на соответствие структуре ZIP, полный тестовый набор.
* НЕ проверено (требуется ноутбук): фактический запуск `safe_start.py`/pytest на
  Windows, активация `.venv` в конкретной PowerShell-политике, установка
  приватного SDK в живом окружении, подключение к реальному sandbox API.
