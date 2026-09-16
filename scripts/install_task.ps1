<#
.SYNOPSIS
    把"A 股行情定时抓取"注册成 Windows 计划任务。

.DESCRIPTION
    仪表盘开着的时候会自己刷新，但电脑关了就不更新了。这个脚本注册计划任务，
    在 A 股交易时段自动抓取并导出单文件 HTML 快照。这样即使你没开服务，
    也能随时双击 HTML 看到最近一次的数据。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1
    powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -Uninstall
#>

param(
    [string]$TaskName = "AShareWatch-DailyFetch",
    # 默认时间按 A 股交易时段（北京时间）设置
    [string[]]$Times = @("09:35", "10:30", "11:25", "13:05", "14:00", "14:55"),
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "已删除计划任务：$TaskName" -ForegroundColor Yellow
    } else {
        Write-Host "没有找到计划任务：$TaskName" -ForegroundColor Yellow
    }
    return
}

# 用和 start.bat 相同的策略找解释器：能跑通才算数
$Python = $null
foreach ($candidate in @(
    (Get-Command python -ErrorAction SilentlyContinue).Source,
    (Get-Command py -ErrorAction SilentlyContinue).Source,
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:USERPROFILE\anaconda3\python.exe",
    "$env:ProgramData\Anaconda3\python.exe",
    "D:\anaconda\python.exe"
)) {
    if (-not $candidate) { continue }
    if (-not (Test-Path $candidate)) { continue }
    & $candidate -c "import sys" 2>$null
    if ($LASTEXITCODE -eq 0) { $Python = $candidate; break }
}

if (-not $Python) {
    Write-Host "[错误] 没有找到可用的 Python。" -ForegroundColor Red
    Write-Host "注意：Windows 自带的 python.exe 是假的，只会打开微软商店。" -ForegroundColor Yellow
    exit 1
}

$ScriptPath = Join-Path $ProjectRoot "scripts\fetch_once.py"
if (-not (Test-Path $ScriptPath)) {
    Write-Host "[错误] 找不到 $ScriptPath" -ForegroundColor Red
    exit 1
}

$Action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "`"$ScriptPath`" --export" `
    -WorkingDirectory $ProjectRoot

$Triggers = @()
foreach ($t in $Times) {
    $Triggers += New-ScheduledTaskTrigger -Daily -At $t
}

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Triggers `
    -Settings $Settings `
    -Description "A 股交易时段定时抓取行情并导出单文件 HTML 快照" | Out-Null

Write-Host ""
Write-Host "已注册计划任务：$TaskName" -ForegroundColor Green
Write-Host "  使用的 Python：$Python"
Write-Host "  执行时间（北京时间）：$($Times -join '、')"
Write-Host "  导出位置：$ProjectRoot\data\exports\ashare-dashboard.html"
Write-Host ""
Write-Host "删除任务：powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -Uninstall"

