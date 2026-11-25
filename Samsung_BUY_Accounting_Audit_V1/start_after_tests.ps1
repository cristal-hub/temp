
# ============================================================
# Tsclp Samsung — TESTS -> MANUAL CONFIRMATION -> MAIN
# Не запускает main.py, если хотя бы один тест завершился ошибкой.
# ============================================================

$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  SAMSUNG: FULL TESTS" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# Выбираем Python из виртуального окружения, если оно есть
$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (Test-Path $VenvPython) {
    $Python = $VenvPython
    Write-Host "Python: .venv" -ForegroundColor Green
}
else {
    $Python = "python"
    Write-Host "Python: системный" -ForegroundColor Yellow
}

# Проверка доступности Python
& $Python --version
if ($LASTEXITCODE -ne 0) {
    Write-Host "ОШИБКА: Python не найден." -ForegroundColor Red
    Read-Host "Enter для выхода"
    exit 1
}

# Полный запуск pytest
Write-Host ""
Write-Host "Запуск ВСЕХ тестов..." -ForegroundColor Cyan
& $Python -m pytest -q

$TestExitCode = $LASTEXITCODE

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan

if ($TestExitCode -ne 0) {
    Write-Host "ТЕСТЫ НЕ ПРОШЛИ." -ForegroundColor Red
    Write-Host "main.py НЕ будет запущен." -ForegroundColor Red
    Write-Host "Код завершения pytest: $TestExitCode" -ForegroundColor Yellow
    Read-Host "Enter для выхода"
    exit $TestExitCode
}

Write-Host "ВСЕ ТЕСТЫ ПРОШЛИ." -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan

Write-Host ""
Write-Host "ВНИМАНИЕ: далее будет запущен торговый робот." -ForegroundColor Yellow
Write-Host "Перед запуском проверь:" -ForegroundColor Yellow
Write-Host "1. В config.py установлен SANDBOX."
Write-Host "2. Используется именно sandbox-токен."
Write-Host "3. Реальные торговые заявки невозможны."
Write-Host ""

$Confirm = Read-Host "Для запуска main.py введи SANDBOX"

if ($Confirm -cne "SANDBOX") {
    Write-Host "Запуск отменён." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "Запуск main.py..." -ForegroundColor Green
Write-Host "Для остановки используй Ctrl+C."
Write-Host ""

& $Python .\main.py

$MainExitCode = $LASTEXITCODE

Write-Host ""
Write-Host "main.py завершился. Код: $MainExitCode" -ForegroundColor Yellow
Read-Host "Enter для выхода"

exit $MainExitCode
