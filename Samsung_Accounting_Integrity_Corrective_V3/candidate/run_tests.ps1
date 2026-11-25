# run_tests.ps1
# Tsclp_v2.2_volatile — запуск локальных тестов.
# Не требует токена и не подключается к брокеру.
#
# ИЗМЕНЕНИЯ (этап 8):
#   - .venv вместо venv (актуальное окружение).
#   - Явный путь к .\.venv\Scripts\python.exe (не зависит от PATH).
#   - exit $LASTEXITCODE (падение тестов -> exit 1).
#   - Сообщение об ошибке: создать .venv, не venv.
#   - Проверка наличия tests/.

$ErrorActionPreference = "Stop"

$venvPython = ".\.venv\Scripts\python.exe"
$venvActivate = ".\.venv\Scripts\Activate.ps1"

if (-not (Test-Path $venvPython)) {
    Write-Host "❌ .venv не найден. Создайте: python -m venv .venv" -ForegroundColor Red
    Write-Host "   Затем: .\.venv\Scripts\python.exe -m pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path ".\tests")) {
    Write-Host "❌ Папка tests/ не найдена." -ForegroundColor Red
    exit 1
}

Write-Host "🧪 Запуск тестов в .venv..." -ForegroundColor Cyan
& $venvPython -m pytest tests -v
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host "✅ Тесты пройдены." -ForegroundColor Green
} else {
    Write-Host "❌ Тесты не пройдены (exit code: $exitCode)." -ForegroundColor Red
}

exit $exitCode