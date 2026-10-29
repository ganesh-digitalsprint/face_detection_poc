[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$repoRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$commonPath = Join-Path $repoRoot 'scripts\launcher-common.ps1'
if (-not (Test-Path -LiteralPath $commonPath -PathType Leaf)) { throw 'Launcher helper scripts/launcher-common.ps1 is missing.' }
. $commonPath

$manifestPath = Join-Path $repoRoot '.launcher\processes.json'
try {
    $entries = @(Read-LauncherManifest -Path $manifestPath)
} catch {
    Write-Error $_.Exception.Message
    exit 1
}

if ($entries.Count -eq 0) {
    Write-Host 'No launcher-owned processes are recorded. Nothing to stop.'
    exit 0
}

$remaining = New-Object System.Collections.Generic.List[object]
$shutdownEntries = $entries
[array]::Reverse($shutdownEntries)
foreach ($entry in $shutdownEntries) {
    $identity = Get-LauncherProcessIdentity -Entry $entry
    if ($null -eq $identity) {
        Write-Host "STALE $($entry.Service) PID $($entry.ProcessId): process identity no longer matches; left any current process untouched." -ForegroundColor Yellow
        continue
    }

    $result = Stop-LauncherEntry -Entry $entry
    if ($result -eq 'stopped') {
        Write-Host "STOPPED $($entry.Service) (PID $($entry.ProcessId))" -ForegroundColor Green
    } elseif ($result -eq 'stale-or-identity-mismatch') {
        Write-Host "STALE $($entry.Service) PID $($entry.ProcessId): process identity changed during shutdown; left it untouched." -ForegroundColor Yellow
    } else {
        Write-Host "FAILED $($entry.Service) (PID $($entry.ProcessId)): could not stop safely; logs: $($entry.StdoutPath), $($entry.StderrPath)" -ForegroundColor Red
        $remaining.Add($entry)
    }
}

if ($remaining.Count -gt 0) {
    Write-LauncherManifest -Path $manifestPath -Processes $remaining.ToArray()
    Write-Error 'Some launcher-owned processes remain. Their verified metadata was retained; run .\stop-all.ps1 again after reviewing the log files.'
    exit 1
}

if (Test-Path -LiteralPath $manifestPath) { Remove-Item -LiteralPath $manifestPath -Force }
Write-Host 'Shutdown complete. No application data, database, or log files were removed.' -ForegroundColor Green
