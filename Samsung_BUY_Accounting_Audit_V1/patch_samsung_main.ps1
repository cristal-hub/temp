#requires -Version 5.1
$ErrorActionPreference = "Stop"

# Samsung main.py: исправление ложной блокировки первичной регистрации BUY.
# Скрипт не запускает робота, не обращается к T-Invest и не меняет GitHub.

$Repo = "cristal-hub/cristal-hub-Tsclp_v2.1_volatile_Samsung"
$Branch = "main"
$ExpectedGitBlobSha = "fe974a98a0542e0de91f82aa4835a1e71d2b19a0"
$RawUrl = "https://raw.githubusercontent.com/cristal-hub/$Repo/$Branch/main.py"
$Target = Join-Path (Get-Location) "main.py"

function Get-GitBlobSha1([byte[]]$Bytes) {
    $Header = [System.Text.Encoding]::ASCII.GetBytes("blob " + $Bytes.Length + [char]0)
    $Combined = New-Object byte[] ($Header.Length + $Bytes.Length)
    [Array]::Copy($Header, 0, $Combined, 0, $Header.Length)
    [Array]::Copy($Bytes, 0, $Combined, $Header.Length, $Bytes.Length)
    $Sha = [System.Security.Cryptography.SHA1]::Create()
    try {
        return ([BitConverter]::ToString($Sha.ComputeHash($Combined))).Replace("-", "").ToLowerInvariant()
    } finally {
        $Sha.Dispose()
    }
}

Write-Host "=== Samsung main.py: безопасная локальная замена ===" -ForegroundColor Cyan
Write-Host "Папка: $((Get-Location).Path)"
Write-Host "Цель:  $Target"

if (Test-Path -LiteralPath $Target) {
    Write-Host ""
    Write-Host "ВНИМАНИЕ: текущий main.py будет заменён. Резервная копия останется рядом."
    $Answer = Read-Host "Продолжить? Введите YES"
    if ($Answer -cne "YES") {
        Write-Host "Отменено. Файлы не изменены." -ForegroundColor Yellow
        exit 0
    }
}

$Temp = Join-Path $env:TEMP ("Samsung_main_" + [Guid]::NewGuid().ToString("N") + ".py")
$Backup = $null
$OriginalBytes = $null
$TargetWritten = $false

try {
    Write-Host "`n1/6 Скачиваю исходный main.py из Samsung..."
    Invoke-WebRequest -Uri $RawUrl -OutFile $Temp -UseBasicParsing

    $DownloadedBytes = [System.IO.File]::ReadAllBytes($Temp)
    $ActualBlobSha = Get-GitBlobSha1 $DownloadedBytes
    if ($ActualBlobSha -ne $ExpectedGitBlobSha) {
        throw "SHA Git blob не совпал. Ожидался $ExpectedGitBlobSha, получен $ActualBlobSha. Репозиторий изменился или скачан не тот файл. Ничего не заменено."
    }
    Write-Host "Исходный Git blob SHA подтверждён: $ActualBlobSha" -ForegroundColor Green

    $Utf8Strict = New-Object System.Text.UTF8Encoding($false, $true)
    $Source = $Utf8Strict.GetString($DownloadedBytes)
    $NewLine = if ($Source.Contains("`r`n")) { "`r`n" } else { "`n" }
    $Normalized = $Source.Replace("`r`n", "`n")

    Write-Host "2/6 Проверяю исходный блок защиты..."
    $OldBlock = @'
    # Партия P0-2: защита от «воскрешения» закрытой позиции. Терминальная
    # заявка, чьё исполнение УЖЕ применено к учёту (executed_lots в записи
    # реестра совпадает с сообщённым брокером), без активной позиции не
    # регистрируется повторно. Рост lots_executed сверх учтённого — это
    # ПОЗДНЕЕ исполнение: обрабатывается штатно ниже. Страховка при
    # расхождении — reconcile-адопция по достоверному снимку брокера.
    rec_pre = ledger.latest(order_id) if (ledger is not None and order_id) else None
    if (rec_pre is not None
            and rec_pre.get("status") in _TERMINAL_ORDER_STATUSES
            and not monitor.has_active_position(figi)):
        recorded_le = int(rec_pre.get("executed_lots") or 0)
        if executed_lots <= recorded_le:
            logging.warning(
                f"[register] {ticker}: исполнение заявки {order_id} ({executed_lots} лот.) "
                f"уже применено к учёту (в реестре {recorded_le}), активной позиции нет — "
                f"повторная регистрация не выполняется (защита от «воскрешения»)"
            )
            return None
'@

    $NewBlock = @'
    # Партия P0-2 / исправление первичной регистрации:
    # FILL в ledger фиксирует ответ брокера, но НЕ доказывает, что исполнение
    # уже применено к локальной позиции. Поэтому при отсутствии активной
    # позиции нельзя блокировать регистрацию только по совпадению FILL в ledger.
    # Защита от «воскрешения» действует, когда в monitor осталась именно CLOSED
    # позиция с тем же entry_order_id: повторное исполнение этой же заявки
    # не создаёт позицию заново. Поздний рост после закрытия требует reconcile.
    rec_pre = ledger.latest(order_id) if (ledger is not None and order_id) else None
    if (rec_pre is not None
            and rec_pre.get("status") in _TERMINAL_ORDER_STATUSES
            and not monitor.has_active_position(figi)):
        recorded_le = int(rec_pre.get("executed_lots") or 0)
        closed_pos = monitor.get_position(figi)
        same_closed_order = (
            closed_pos is not None
            and closed_pos.state == PositionState.CLOSED
            and bool(order_id)
            and closed_pos.entry_order_id == order_id
        )
        if same_closed_order and executed_lots <= max(
                recorded_le, int(closed_pos.entry_applied_lots or 0)):
            logging.warning(
                f"[register] {ticker}: исполнение заявки {order_id} ({executed_lots} лот.) "
                f"уже относится к закрытой позиции (ledger={recorded_le}, "
                f"applied={closed_pos.entry_applied_lots}) — повторная регистрация "
                f"запрещена (защита от «воскрешения»)"
            )
            return None
        if same_closed_order and executed_lots > max(
                recorded_le, int(closed_pos.entry_applied_lots or 0)):
            client.uncertain_state = True
            if ledger is not None:
                ledger.record_uncertain(
                    order_id, figi=figi, ticker=ticker, side="BUY",
                    executed_lots=int(executed_lots),
                    reason=("поздний рост исполнения после CLOSED той же позиции; "
                            "автоматическое воскрешение запрещено, требуется reconcile"),
                    source=source or "register_executed_buy",
                )
            logging.error(
                f"[register] {ticker}: поздний рост заявки {order_id} после CLOSED — "
                f"авторегистрация запрещена, требуется reconcile"
            )
            return None
'@

    $OldLf = $OldBlock.Replace("`r`n", "`n").TrimEnd("`n")
    $NewLf = $NewBlock.Replace("`r`n", "`n").TrimEnd("`n")
    $Occurrences = ([regex]::Matches($Normalized, [regex]::Escape($OldLf))).Count
    if ($Occurrences -ne 1) {
        throw "Исходный guard найден $Occurrences раз вместо ровно 1. Файл не заменён."
    }

    $Patched = $Normalized.Replace($OldLf, $NewLf)
    if ($Patched -eq $Normalized) {
        throw "Замена не изменила файл. Файл не заменён."
    }
    if (([regex]::Matches($Patched, "same_closed_order")).Count -ne 3) {
        throw "Контроль нового блока не пройден. Файл не заменён."
    }

    Write-Host "Исходный блок найден ровно один раз." -ForegroundColor Green
    Write-Host "3/6 Сохраняю резервную копию и полный main.py..."
    if (Test-Path -LiteralPath $Target) {
        $Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $Backup = "$Target.bak_$Stamp"
        Copy-Item -LiteralPath $Target -Destination $Backup
        $OriginalBytes = [System.IO.File]::ReadAllBytes($Target)
        Write-Host "Резервная копия: $Backup" -ForegroundColor Green
    }

    $FinalText = if ($NewLine -eq "`r`n") { $Patched.Replace("`n", "`r`n") } else { $Patched }
    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Target, $FinalText, $Utf8NoBom)
    $TargetWritten = $true

    Write-Host "4/6 Проверяю размер, SHA-256 и наличие старого/нового guard..."
    $FinalBytes = [System.IO.File]::ReadAllBytes($Target)
    $FinalSha = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash
    $FinalTextCheck = $Utf8Strict.GetString($FinalBytes)
    if ($FinalTextCheck.Contains("and not monitor.has_active_position(figi)):`r`n        recorded_le")) {
        throw "Старый guard всё ещё присутствует."
    }
    if (-not $FinalTextCheck.Contains("same_closed_order")) {
        throw "Новый guard не найден после записи."
    }
    Write-Host "Размер: $($FinalBytes.Length) байт"
    Write-Host "SHA-256 нового main.py: $FinalSha"

    Write-Host "5/6 Проверяю синтаксис Python (только py_compile)..."
    $Py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $Py) { $Py = Get-Command py -ErrorAction SilentlyContinue }
    if (-not $Py) {
        throw "Python/py не найден в PATH. Файл будет восстановлен из резервной копии."
    }
    if ($Py.Name -eq "py") {
        & $Py.Source -3 -m py_compile $Target
    } else {
        & $Py.Source -m py_compile $Target
    }
    if ($LASTEXITCODE -ne 0) {
        throw "py_compile завершился с кодом $LASTEXITCODE."
    }

    Write-Host "6/6 Готово. Полный main.py заменён; синтаксис Python корректен." -ForegroundColor Green
    Write-Host ""
    Write-Host "ВАЖНО: это только синтаксическая проверка. Торговые тесты P0-3/P0-4/P0-5 и весь набор тестов НЕ запускались."
    Write-Host "Не запускайте робота до прохождения тестов."
}
catch {
    Write-Host "`nОШИБКА: $($_.Exception.Message)" -ForegroundColor Red
    if ($TargetWritten) {
        if ($null -ne $OriginalBytes) {
            [System.IO.File]::WriteAllBytes($Target, $OriginalBytes)
            Write-Host "Исходный main.py восстановлен из сохранённых байтов." -ForegroundColor Yellow
        } elseif ($null -ne $Backup -and (Test-Path -LiteralPath $Backup)) {
            Copy-Item -LiteralPath $Backup -Destination $Target -Force
            Write-Host "Исходный main.py восстановлен из резервной копии." -ForegroundColor Yellow
        } else {
            Remove-Item -LiteralPath $Target -Force
            Write-Host "Созданный скриптом main.py удалён; исходного файла до запуска не было." -ForegroundColor Yellow
        }
    } else {
        Write-Host "main.py не изменялся." -ForegroundColor Yellow
    }
    exit 1
}
finally {
    if (Test-Path -LiteralPath $Temp) {
        Remove-Item -LiteralPath $Temp -Force -ErrorAction SilentlyContinue
    }
}
