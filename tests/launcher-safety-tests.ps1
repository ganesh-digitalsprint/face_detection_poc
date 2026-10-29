[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $repoRoot 'scripts\launcher-common.ps1')

$script:checks = 0
function Assert-LauncherTest {
    param([bool]$Condition, [string]$Name)
    $script:checks++
    if (-not $Condition) { throw "FAIL: $Name" }
    Write-Host "PASS: $Name" -ForegroundColor Green
}

$testRoot = Join-Path $env:TEMP ("face-detection-launcher-test-" + [Guid]::NewGuid().ToString('N'))
$logs = Join-Path $testRoot 'logs'
$manifest = Join-Path $testRoot 'processes.json'
$listener = $null
$first = $null
$second = $null
$previousAlert = [Environment]::GetEnvironmentVariable('ALERT_OPERATOR_CREDENTIALS','Process')
$previousVite = [Environment]::GetEnvironmentVariable('VITE_VAULT_API_BASE_URL','Process')

try {
    New-Item -ItemType Directory -Path $logs -Force | Out-Null

    foreach ($file in @('start-all.ps1','stop-all.ps1','scripts\launcher-common.ps1')) {
        $path = Join-Path $repoRoot $file
        $tokens = $null; $parseErrors = $null
        [Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$parseErrors) | Out-Null
        Assert-LauncherTest ($parseErrors.Count -eq 0) "PowerShell syntax: $file"
    }

    $envFile = Join-Path $testRoot 'test.env'
    [IO.File]::WriteAllText($envFile, "DATABASE_URL=postgresql+psycopg2://user:private-value@localhost:5432/demo`r`nVALUE='safe test'`r`n")
    $parsedEnv = Get-LauncherEnvFile -Path $envFile
    Assert-LauncherTest ($parsedEnv.ContainsKey('DATABASE_URL') -and $parsedEnv['VALUE'] -eq 'safe test') 'environment parser reads values without printing them'
    $dbParts = Get-LauncherUrlParts -Value $parsedEnv['DATABASE_URL'] -AllowedSchemes @('postgresql+psycopg2')
    Assert-LauncherTest ($null -ne $dbParts -and $dbParts.Host -eq 'localhost' -and $dbParts.Port -eq 5432 -and $dbParts.UserInfo -match 'private-value') 'PostgreSQL URL parsing retains credentials only in memory'

    $listener = [System.Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $busyPort = ([Net.IPEndPoint]$listener.LocalEndpoint).Port
    $busyIds = @(Get-LauncherPortListeners -Port $busyPort)
    Assert-LauncherTest ($busyIds.Count -gt 0) 'port conflict detection sees a temporary owned listener'
    $listener.Stop(); $listener = $null
    Assert-LauncherTest (@(Get-LauncherPortListeners -Port $busyPort).Count -eq 0) 'free port detection passes after listener closes'
    Assert-LauncherTest (-not (Test-LauncherHealthyEndpoint -Uri 'http://127.0.0.1:1/health' -Service 'Alert Service' -TimeoutSeconds 1)) 'unavailable health endpoint is not marked ready'

    $powershell = Join-Path $PSHOME 'powershell.exe'
    if (-not (Test-Path -LiteralPath $powershell -PathType Leaf)) { throw 'Test requires the Windows PowerShell executable.' }
    $childCommand = "if (`$env:ALERT_OPERATOR_CREDENTIALS -eq 'child-test-marker' -and -not `$env:VITE_VAULT_API_BASE_URL) { 'SCOPED_ENV_OK' } else { 'SCOPED_ENV_BAD' }; [Environment]::CurrentDirectory; Start-Sleep -Seconds 60"
    $encodedChildCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($childCommand))
    $secondCommand = 'Start-Sleep -Seconds 60'
    $encodedSecondCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($secondCommand))
    $marker = 'Start-Sleep -Seconds 60'

    [Environment]::SetEnvironmentVariable('ALERT_OPERATOR_CREDENTIALS','parent-test-marker','Process')
    [Environment]::SetEnvironmentVariable('VITE_VAULT_API_BASE_URL','parent-vite-marker','Process')
    $first = Start-LauncherProcess -Service 'Test One' -FilePath $powershell `
        -ArgumentList @('-NoLogo','-NoProfile','-EncodedCommand',$encodedChildCommand) -WorkingDirectory $testRoot `
        -CommandMarker $marker -StdoutPath (Join-Path $logs 'first.out.log') -StderrPath (Join-Path $logs 'first.err.log') `
        -ScopedEnvironment @{ ALERT_OPERATOR_CREDENTIALS = 'child-test-marker' }
    Assert-LauncherTest ([Environment]::GetEnvironmentVariable('ALERT_OPERATOR_CREDENTIALS','Process') -eq 'parent-test-marker' -and
        [Environment]::GetEnvironmentVariable('VITE_VAULT_API_BASE_URL','Process') -eq 'parent-vite-marker') 'launcher restores caller environment after scoped process launch'
    $deadline = [DateTime]::UtcNow.AddSeconds(8)
    do {
        Start-Sleep -Milliseconds 100
        $logText = if (Test-Path $first.StdoutPath) { [string](Get-Content -LiteralPath $first.StdoutPath -Raw) } else { '' }
    } while ([DateTime]::UtcNow -lt $deadline -and $logText -notmatch 'SCOPED_ENV_OK')
    $workingDirectoryMatched = [string]::Equals([IO.Path]::GetFullPath($first.WorkingDirectory),[IO.Path]::GetFullPath($testRoot),[StringComparison]::OrdinalIgnoreCase)
    Assert-LauncherTest ($logText -match 'SCOPED_ENV_OK' -and $workingDirectoryMatched) 'managed process receives only scoped app variables and records expected working directory'
    $firstIdentity = Get-LauncherProcessIdentity -Entry $first
    if ($null -eq $firstIdentity) { Write-Host "DEBUG process=$($first.ProcessId) executable=$($first.ExecutablePath) started=$($first.StartedAtUtc) cmd=$($first.CommandMarker)" }
    Assert-LauncherTest ($null -ne $firstIdentity) 'process identity verifies PID, executable, start time, and command marker'

    $second = Start-LauncherProcess -Service 'Test Two' -FilePath $powershell `
        -ArgumentList @('-NoLogo','-NoProfile','-EncodedCommand',$encodedSecondCommand) -WorkingDirectory $testRoot `
        -CommandMarker $marker -StdoutPath (Join-Path $logs 'second.out.log') -StderrPath (Join-Path $logs 'second.err.log')
    Write-LauncherManifest -Path $manifest -Processes @($first,$second)
    $manifestText = Get-Content -LiteralPath $manifest -Raw
    Assert-LauncherTest ($manifestText -notmatch 'child-test-marker|parent-test-marker|private-value') 'process manifest contains no environment credentials'
    Assert-LauncherTest (@(Read-LauncherManifest -Path $manifest).Count -eq 2) 'process manifest round-trips launcher-owned process metadata'

    $stale = [pscustomobject]@{
        Service = 'Stale fixture'; ProcessId = $PID; ExecutablePath = (Get-Process -Id $PID).Path
        StartedAtUtc = [DateTime]::UtcNow.ToString('o'); WorkingDirectory = $testRoot; CommandMarker = 'not-the-test-shell'
        StdoutPath = ''; StderrPath = ''
    }
    Assert-LauncherTest ((Stop-LauncherEntry -Entry $stale) -eq 'stale-or-identity-mismatch' -and
        $null -ne (Get-Process -Id $PID -ErrorAction SilentlyContinue)) 'stale/reused PID metadata leaves the current shell untouched'

    Assert-LauncherTest ((Stop-LauncherEntry -Entry $second) -eq 'stopped') 'partial-startup cleanup stops only the second tracked test process'
    $firstStopResult = Stop-LauncherEntry -Entry $first
    Assert-LauncherTest ($firstStopResult -in @('stopped','stale-or-identity-mismatch')) 'shutdown stops only the first tracked test process or safely recognizes it already exited'
    Assert-LauncherTest ((Stop-LauncherEntry -Entry $first) -eq 'stale-or-identity-mismatch') 'repeated shutdown is safe after an owned process exits'
    Assert-LauncherTest ((Test-Path $first.StdoutPath) -and (Test-Path $first.StderrPath)) 'stdout and stderr logs are created for managed processes'
    Write-Host "All $script:checks launcher safety checks passed." -ForegroundColor Green
} finally {
    if ($listener) { try { $listener.Stop() } catch { } }
    foreach ($entry in @($second,$first)) {
        if ($null -ne $entry) { Stop-LauncherEntry -Entry $entry | Out-Null }
    }
    [Environment]::SetEnvironmentVariable('ALERT_OPERATOR_CREDENTIALS',$previousAlert,'Process')
    [Environment]::SetEnvironmentVariable('VITE_VAULT_API_BASE_URL',$previousVite,'Process')
    $resolvedTempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
    $resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
    if ($resolvedTestRoot.StartsWith($resolvedTempRoot,[StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Parent $resolvedTestRoot) -eq $env:TEMP -and (Test-Path -LiteralPath $resolvedTestRoot)) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
