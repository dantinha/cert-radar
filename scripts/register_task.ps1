# scripts/register_task.ps1
# Script idempotente para registrar a tarefa CertRadarDailyCheck no Agendador de Tarefas do Windows

$ErrorActionPreference = "Stop"

$taskName = "CertRadarDailyCheck"
$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python.exe"
}

Write-Host "Configurando tarefa agendada: $taskName..." -ForegroundColor Cyan

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -Command `"Set-Location '$repoRoot'; & '$pythonExe' -m cert_radar check-radar`"" `
    -WorkingDirectory $repoRoot

$trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At "08:00" `
    -RepetitionInterval (New-TimeSpan -Hours 12)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($existingTask) {
    Write-Host "Atualizando tarefa agendada existente ($taskName)..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Verificação periódica do CertRadar a cada 12 horas (radar de vouchers e alertas)"

Write-Host "✓ Tarefa '$taskName' registrada com sucesso no Agendador de Tarefas do Windows!" -ForegroundColor Green
Write-Host "  Frequência: Diária a cada 12 horas" -ForegroundColor Gray
Write-Host "  Diretório de Trabalho: $repoRoot" -ForegroundColor Gray
Write-Host "  Comando: $pythonExe -m cert_radar check-radar" -ForegroundColor Gray
