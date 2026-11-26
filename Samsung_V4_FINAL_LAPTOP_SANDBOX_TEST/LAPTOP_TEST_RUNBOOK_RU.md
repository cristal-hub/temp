# LAPTOP_TEST_RUNBOOK_RU.md — пошаговая инструкция проверки сборки на ноутбуке

**Сборка:** Samsung_V4_FINAL_LAPTOP_SANDBOX_TEST
**Мандаты:** `STRATEGY LOGIC: UNCHANGED` · `RESEARCH ONLY` · `NO THRESHOLD IS OPTIMIZED` ·
`NO FILTER IS INSTALLED` · `NO LIVE ORDERS`
**LAPTOP SANDBOX TEST BUILD — BROKER ORDER SUBMISSION DISABLED BY DEFAULT**

Инструкция написана для пользователя без опыта Python: все команды можно копировать
в PowerShell и выполнять по одной. Команды даны для PowerShell 5+ (есть в Windows 10/11).

> **ГЛАВНОЕ ПРАВИЛО:** торговая отправка заявок в этой сборке ОТКЛЮЧЕНА по умолчанию.
> LIVE-режим запрещён всегда. Пока вы не выполните спецпроцедуру из раздела
> «Режим B» (а вам она для первой проверки НЕ нужна), ни одна заявка не будет
> отправлена — это защищено кодом, а не только настройкой.

---

## 1. Куда распаковать ZIP

1. Создайте ОТДЕЛЬНУЮ папку (не внутри других проектов):

```powershell
mkdir C:\Samsung_V4_TEST
```

2. Распакуйте ZIP в неё (правой кнопкой по архиву → «Извлечь всё…» → путь
   `C:\Samsung_V4_TEST`, либо):

```powershell
Expand-Archive -Path "$env:USERPROFILE\Downloads\Samsung_V4_FINAL_LAPTOP_SANDBOX_TEST.zip" -DestinationPath C:\Samsung_V4_TEST
```

3. Перейдите в папку сборки (все дальнейшие команды выполняются отсюда):

```powershell
cd C:\Samsung_V4_TEST\Samsung_V4_FINAL_LAPTOP_SANDBOX_TEST
```

## 2. Почему НЕЛЬЗЯ распаковывать поверх рабочего Samsung

* Тестовая сборка содержит изменённые файлы аудита и новые файлы безопасности —
  распаковка поверх рабочего проекта смешает версии и сломает и проверку, и рабочий робот.
* Проверка целостности ZIP и работоспособность сборки предполагают ИЗОЛИРОВАННУЮ папку.
* Исходный Samsung при работе по этой инструкции вообще не затрагивается
  (в конце — раздел «Возврат к исходному Samsung»).

## 3. Проверить версию Python

```powershell
python --version
```

Нужно **3.12** (например, `Python 3.12.10`). Если команда не находится или версия
другая — установите Python 3.12 с python.org (галочка «Add python.exe to PATH»),
затем ОТКРОЙТЕ PowerShell заново и повторите.

## 4. Создать виртуальное окружение

```powershell
cd C:\Samsung_V4_TEST\Samsung_V4_FINAL_LAPTOP_SANDBOX_TEST\candidate
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

После активации в начале строки появится `(.venv)`. Если PowerShell ругается на
запрет скриптов — один раз выполните:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

и повторите активацию. **Каждый новый сеанс PowerShell** начинайте с шагов:
`cd …\candidate` и `.\.venv\Scripts\Activate.ps1`.

## 5. Установить зависимости

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Пояснение: большинство пакетов установятся с PyPI. Строка `t-tech-investments==1.51.0` —
приватный SDK брокера: если она не установится из-за отсутствия доступа к внутреннему
индексу, установка остальных зависимостей всё равно нужна. Тогда:
* локальные тесты пройдут (тестовая среда автоматически использует штатные заглушки проекта);
* шаг «SAFE START с проверкой API» (раздел 8) сообщит об отсутствии SDK — это
  безопасный отказ, а не авария. Для полноценной работы с брокером SDK должен быть
  установлен (так же, как это сделано в рабочем окружении Samsung).

Проверка установки:

```powershell
pip show pandas pandas-ta-classic python-telegram-bot python-dotenv pytest
```

## 6. Проверить конфигурацию (до любых запусков)

1. Создайте файл настроек по шаблону `CONFIGURATION_TEMPLATE.md` (в корне сборки):

```powershell
notepad .env
```

Минимум для проверки (значения-заглушки НЕ подойдут для API — нужны ваши реальные
sandbox-токены; для чисто локальной проверки см. шаг 6б):

```
TINKOFF_API_TOKEN=ваш_sandbox_токен
TINKOFF_READONLY_TOKEN=ваш_readonly_токен
TELEGRAM_BOT_TOKEN=ваш_токен_бота
TELEGRAM_CHAT_ID=ваш_chat_id
TELEGRAM_ALLOWED_USER_ID=ваш_user_id
```

2. **6б. Локальная проверка конфигурации без сети** (если токены ещё не готовы):

```powershell
python safe_start.py --no-api
```

Ожидаемо: разделы 1–3 и 5 проверок, раздел 4 «ПРОПУЩЕНО (--no-api)», в конце
«SAFE START завершён…». Если видите «БЕЗОПАСНЫЙ ОТКАЗ» — прочтите причину в выводе
(обычно не заполнено поле .env) и исправьте.

3. **6в. Полная проверка (с сетью, только чтение)** — после заполнения .env:

```powershell
python safe_start.py
```

Эта проверка НИЧЕГО не создаёт у брокера и не отправляет заявок: только чтение
аккаунтов/позиций. Обязательно обратите внимание на строку
`[ OK ] само-тест блокировки: заявка отклонена…` — это подтверждение, что отправка
заявок заблокирована.

## 7. Выполнить локальные тесты

```powershell
python -m pytest -q
```

Ожидаемый результат: **789 passed** (на среде без python-telegram-bot или с другим
набором пакетов число может отличаться на 0 тестов; FAILED/ERROR быть не должно).
Полный лог (по желанию):

```powershell
python -m pytest -q 2>&1 | Tee-Object -FilePath v4_full_pytest.log
```

## 8. Запустить SAFE START / READ-ONLY (Режим A — по умолчанию)

```powershell
python safe_start.py
```

Что произойдёт: будут проверены зависимости, конфигурация, режим сборки, защита
заявок (включая само-тест блокировки), доступность sandbox API (только чтение),
реестр заявок и локальное состояние; приложение завершится само (штатная остановка).
**Торговый цикл не запускается. Заявки не отправляются.**

Коды возврата: `0` — успех; `2` — безопасный отказ (смотрите причину в выводе);
`130` — остановлено Ctrl+C.

## 9. Где смотреть логи

* Вывод safe_start/pytest — в консоли; для сохранения используйте `Tee-Object`
  (пример в разделе 7).
* Runtime-журналы приложения (создаются при работе main.py, не при safe_start):
  `research_events.jsonl`, `research_trades.csv`, `state.json`, `order_ledger.jsonl` —
  в каталоге `candidate` (рядом с main.py). Открывайте Блокнотом.
* Файл `logs\` в корне сборки — служебные материалы аудита (не изменяйте).

## 10. Как корректно остановить приложение

* `Ctrl+C` — штатная остановка (обрабатывается, состояние сохраняется).
* Убедиться, что фоновых задач не осталось:

```powershell
Get-Process python -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, StartTime
```

Повторный запуск — снова `python safe_start.py` (или, для Режима B, `python main.py`
— раздел «Режим B»). Локальные данные (state/ledger) переживают остановку и
подхватываются при следующем запуске — это штатная механика восстановления.

## 11. Как проверить результат запуска

Чек-лист после `python safe_start.py`:
* строка `активный режим: SAFE_START`;
* `[ OK ] config.validate()` (или понятная причина отказа);
* `[ OK ] само-тест блокировки: заявка отклонена…`;
* `[ OK ] order_ledger.jsonl: достоверен…` (или обоснованное предупреждение);
* итоговая строка `SAFE START завершён…`.

## 12. Собрать диагностический архив БЕЗ секретов

```powershell
mkdir C:\Samsung_V4_TEST\diag
Copy-Item .\v4_full_pytest.log C:\Samsung_V4_TEST\diag\ -ErrorAction SilentlyContinue
Copy-Item .\research_events.jsonl C:\Samsung_V4_TEST\diag\ -ErrorAction SilentlyContinue
python safe_start.py --no-api 2>&1 | Tee-Object -FilePath C:\Samsung_V4_TEST\diag\safe_start_output.txt
Compress-Archive -Path C:\Samsung_V4_TEST\diag\* -DestinationPath C:\Samsung_V4_TEST\diag_samsung_v4.zip
```

Проверка, что в архив не попали секреты:

```powershell
Select-String -Path C:\Samsung_V4_TEST\diag\* -Pattern "TINKOF\w+=\S{10,}|TELEGRAM_BOT_TOKEN=\S{10,}"
```

Вывод пустой → секретов нет. Файл `.env` в архив НЕ включать никогда.

## 13. Как вернуться к исходному Samsung

* Эта сборка — ОТДЕЛЬНАЯ папка; исходный Samsung не изменялся. Возврат = просто
  прекратить пользоваться тестовой папкой: закройте PowerShell, удалите
  `C:\Samsung_V4_TEST` когда сочтёте нужным. Рабочий Samsung продолжает работать как раньше.
* Рабочие файлы (`state.json`, реестр, CSV) у тестовой сборки СВОИ, в папке `candidate` —
  они не пересекаются с рабочими файлами Samsung.
* Подробности — `ROLLBACK_RU.md` (в корне сборки).

---

## Проверка отсутствия LIVE-режима и отключённой отправки заявок

Выполните по одной и сверьте ожидаемый вывод:

```powershell
# 1. Маркер Режима B отсутствует (False = заявки заблокированы)
Test-Path .\candidate\sandbox_execution.enabled

# 2. Переменная режима не задана в этой сессии (пусто = SAFE_START)
$env:SAMSUNG_V4_BUILD_MODE

# 3. Тесты безопасности сборки проходят (в т.ч. блокировка LIVE)
cd .\candidate
python -m pytest test_v4_safety_build.py -q
cd ..

# 4. В конфиге запрещён не-sandbox (ищем «Только песочница»)
Select-String -Path .\candidate\config.py -Pattern "Только песочница"

# 5. В клиенте жёсткий запрет не-sandbox
Select-String -Path .\candidate\tinkoff_client.py -Pattern "SandboxRequiredError"
```

Ожидания: (1) `False`; (2) пусто; (3) `18 passed`; (4) и (5) строки найдены.

---

## Режим B — CONTROLLED SANDBOX EXECUTION (по умолчанию ВЫКЛЮЧЕН; GLM не активировал)

Это техническая возможность для ПОСЛЕДУЮЩЕГО контролируемого sandbox-испытания.
GLM его не включал и заявок не отправлял. Включение — ТОЛЬКО вашим явным действием,
двумя шагами (ни один из них не может произойти случайно):

1. **Создать маркер** (интерактивно, подтверждение фразой):

```powershell
cd C:\Samsung_V4_TEST\Samsung_V4_FINAL_LAPTOP_SANDBOX_TEST\candidate
python enable_sandbox_execution.py
# на запрос ввести точно: ENABLE-SANDBOX
```

2. **Запустить робота с переменной режима** (в ТОМ ЖЕ сеансе PowerShell):

```powershell
$env:SAMSUNG_V4_BUILD_MODE = "SANDBOX_EXECUTION"
python main.py
```

Условия и ограничения:
* заявки возможны ТОЛЬКО в sandbox; LIVE запрещён всегда (config.py: «USE_SANDBOX=False
  запрещён. Только песочница»; клиент поднимает SandboxRequiredError);
* переменная окружения живёт только внутри текущего сеанса PowerShell — закрыв
  окно, вы вернётесь в Режим A (маркер сам по себе заявки не включает);
* вернуть всё в Режим A:

```powershell
Remove-Item .\sandbox_execution.enabled
$env:SAMSUNG_V4_BUILD_MODE = $null
```

* если параметр задан с опечаткой (например, `SANDBOX_EXEСUTION`) — сборка безопасно
  остаётся в Режиме A: неизвестное значение не включает заявки (проверено тестом
  `test_unknown_env_value_fail_closed`).

**Не добавляйте** `SAMSUNG_V4_BUILD_MODE` в файл `.env` — включение Режима B
выполняется только через переменную сеанса (см. CONFIGURATION_TEMPLATE.md).
