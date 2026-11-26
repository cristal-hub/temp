# ROLLBACK_RU.md — возврат к исходному Samsung

**Мандаты:** `STRATEGY LOGIC: UNCHANGED` · `RESEARCH ONLY` · `NO LIVE ORDERS`

## 1. Главное

Тестовая сборка V4 поставляется и работает в ОТДЕЛЬНОЙ папке (например,
`C:\Samsung_V4_TEST\...`). Установка не затрагивает рабочий Samsung:

* файлы Samsung не изменялись и не перезаписывались;
* runtime-файлы (state.json, реестр заявок, CSV-журналы) у сборки СВОИ и лежат
  внутри её каталога `candidate`;
* ничего не устанавливалось в системный Python и в автозагрузку — вся среда в
  `.venv` внутри папки сборки.

## 2. Прекратить использование сборки

```powershell
# 1. Остановить всё, что могло быть запущено (Ctrl+C в окнах сборки), затем:
Get-Process python -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, StartTime

# 2. Закрыть сеансы PowerShell, связанные со сборкой.
# 3. Удалить папку сборки (когда решите):
Remove-Item -Recurse -Force C:\Samsung_V4_TEST
```

На этом «откат» завершён: рабочий Samsung продолжает работать как прежде.

## 3. Если случайно распаковали сборку ПОВЕРХ рабочего Samsung

По инструкции это исключено, но если произошло:

1. Остановите все процессы Python.
2. Восстановите файлы Samsung из вашего источника (git-репозиторий Samsung
   или резервная копия, которую вы вели до этого):

```powershell
cd <путь к папке Samsung>
git status        # увидеть изменённые файлы
git checkout -- . # вернуть рабочее дерево к HEAD (если Samsung под git)
```

3. Эталонные SHA256 исходной версии — в `SAMSUNG_PRESERVED.md` (файл сборки V3/V4
   наследует список неизменённых стратегических файлов) и в манифесте
   `SOURCE_BASELINE_MANIFEST_SHA256.txt` пакета V3.
4. Не запускайте торговый цикл до проверки `git status` (чистое дерево).

## 4. Отключение Режима B (если включали)

```powershell
cd C:\Samsung_V4_TEST\Samsung_V4_FINAL_LAPTOP_SANDBOX_TEST\candidate
Remove-Item .\sandbox_execution.enabled -ErrorAction SilentlyContinue
$env:SAMSUNG_V4_BUILD_MODE = $null
```

Заявки снова заблокированы (Режим A). LIVE был запрещён всегда.

## 5. Проверка после отката

```powershell
Test-Path C:\Samsung_V4_TEST    # False — сборка удалена
Test-Path .\sandbox_execution.enabled   # (в папке Samsung) False — маркера нет
```

Рабочий Samsung: запускается штатно, runtime-файлы не изменились (сборка их
не трогала — они у неё были собственные, в отдельной папке).
