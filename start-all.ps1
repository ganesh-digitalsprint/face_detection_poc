[CmdletBinding()]
param(
    [switch]$PreflightOnly,
    [ValidateRange(15, 600)][int]$AlertTimeoutSeconds = 60,
    [ValidateRange(15, 600)][int]$VaultTimeoutSeconds = 180,
    [ValidateRange(15, 600)][int]$BranchTimeoutSeconds = 150,
    [ValidateRange(15, 600)][int]$FrontendTimeoutSeconds = 60
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$repoRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$commonPath = Join-Path $repoRoot 'scripts\launcher-common.ps1'
if (-not (Test-Path -LiteralPath $commonPath -PathType Leaf)) { throw 'Launcher helper scripts/launcher-common.ps1 is missing.' }
. $commonPath

$launcherDir = Join-Path $repoRoot '.launcher'
$manifestPath = Join-Path $launcherDir 'processes.json'
$logDir = Join-Path $repoRoot 'logs'
$lockPath = Join-Path $launcherDir 'start.lock'
$started = New-Object System.Collections.Generic.List[object]
$warnings = New-Object System.Collections.Generic.List[string]
$lockStream = $null

function Add-LauncherWarning {
    param([string]$Message)
    $warnings.Add($Message)
    Write-Host "WARN  $Message" -ForegroundColor Yellow
}

function Get-ValueFromMaps {
    param([hashtable[]]$Maps, [string]$Name)
    for ($i = $Maps.Count - 1; $i -ge 0; $i--) {
        if ($Maps[$i].ContainsKey($Name)) { return [string]$Maps[$i][$Name] }
    }
    return ''
}

function Test-AlertCredentialsMap {
    param([string]$Value, [ValidateSet('producer','operator')][string]$Kind)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    try {
        $parsed = $Value | ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $parsed -or $parsed -isnot [System.Management.Automation.PSCustomObject]) { return $false }
        $items = @($parsed.PSObject.Properties)
        if ($items.Count -eq 0) { return $false }
        foreach ($item in $items) {
            if ([string]::IsNullOrWhiteSpace($item.Name)) { return $false }
            if ($Kind -eq 'producer') {
                if ([string]::IsNullOrWhiteSpace([string]$item.Value.use_case) -or [string]::IsNullOrWhiteSpace([string]$item.Value.producer)) { return $false }
            } else {
                if ([string]::IsNullOrWhiteSpace([string]$item.Value.actor_id) -or $null -eq $item.Value.use_cases) { return $false }
            }
        }
        return $true
    } catch { return $false }
}

function Assert-PythonEnvironment {
    param(
        [string]$Label,
        [string]$PythonPath,
        [int[]]$AllowedMinorVersions,
        [string[]]$RequiredModules
    )
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw "$Label virtual environment is missing its Python executable. Set it up from that service's README, then retry." }
    $versionText = (& $PythonPath --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^Python\s+(\d+)\.(\d+)\.') { throw "$Label Python executable could not report its version." }
    $minor = [int]$matches[2]
    if ([int]$matches[1] -ne 3 -or $AllowedMinorVersions -notcontains $minor) {
        $expected = ($AllowedMinorVersions | ForEach-Object { "3.$_" }) -join ' or '
        throw "$Label requires Python $expected; its environment reports $versionText."
    }
    $moduleJson = (& $PythonPath -c "import importlib.util,json,sys; print(json.dumps([m for m in sys.argv[1:] if importlib.util.find_spec(m) is None]))" @RequiredModules 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "$Label could not validate its installed Python dependencies." }
    $missing = @()
    if ($moduleJson -and $moduleJson -ne '[]') { $missing = @($moduleJson | ConvertFrom-Json) }
    if ($missing.Count -gt 0) { throw "$Label is missing Python packages: $($missing -join ', '). Install this service's declared dependencies in its own .venv." }
    Write-Host "PASS  $Label Python $($versionText -replace '^Python\s+','') and required packages" -ForegroundColor Green
}

function Assert-LocalPortIsFree {
    param([string]$Service, [int]$Port, [string]$HealthUri)
    $listeners = @(Get-LauncherPortListeners -Port $Port)
    if ($listeners.Count -eq 0) {
        Write-Host "PASS  $Service port $Port is free" -ForegroundColor Green
        return
    }
    if (Test-LauncherHealthyEndpoint -Uri $HealthUri -Service $Service -TimeoutSeconds 2) {
        throw "$Service health endpoint is already healthy on port $Port, but that process is not owned by this launcher. It was left untouched; stop it manually or use its existing launcher manifest."
    }
    $names = @($listeners | ForEach-Object {
        $process = Get-Process -Id $_ -ErrorAction SilentlyContinue
        if ($process) { "$($process.ProcessName) (PID $_)" } else { "PID $_" }
    }) -join ', '
    throw "Port $Port is occupied ($names), and it did not pass the $Service health check. The existing process was left untouched."
}

function Test-ServiceHealth {
    param([string]$Service, [string]$Uri)
    if (-not (Test-LauncherHealthyEndpoint -Uri $Uri -Service $Service -TimeoutSeconds 2)) {
        throw "$Service health endpoint did not confirm readiness at $Uri."
    }
}

try {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'This launcher requires Windows PowerShell.' }
    if ($PSVersionTable.PSVersion -lt [Version]'5.1') { throw 'Windows PowerShell 5.1 or later is required.' }

    $vaultDir = Join-Path $repoRoot 'backend\use_cases\vault_monitoring'
    $branchDir = Join-Path $repoRoot 'backend\use_cases\branch_exterior'
    $alertDir = Join-Path $repoRoot 'backend\services\alert_service'
    $frontendDir = Join-Path $repoRoot 'frontend'
    $vaultPython = Join-Path $vaultDir '.venv\Scripts\python.exe'
    $branchPython = Join-Path $branchDir '.venv\Scripts\python.exe'
    $alertPython = Join-Path $alertDir '.venv\Scripts\python.exe'
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue

    foreach ($directory in @($vaultDir, $branchDir, $alertDir, $frontendDir)) {
        if (-not (Test-Path -LiteralPath $directory -PathType Container)) { throw "Required application directory is missing: $directory" }
    }
    foreach ($file in @(
        (Join-Path $vaultDir 'app\main.py'),
        (Join-Path $branchDir 'app\main.py'),
        (Join-Path $alertDir 'app\main.py'),
        (Join-Path $frontendDir 'package.json'),
        (Join-Path $frontendDir 'package-lock.json'),
        (Join-Path $frontendDir 'node_modules\vite\bin\vite.js'),
        (Join-Path $frontendDir 'node_modules\react\package.json')
    )) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Required application file is missing: $file" }
    }
    if (-not $nodeCommand -or -not $npmCommand) { throw 'Node.js and npm.cmd are required. Install Node.js, reopen PowerShell, and retry.' }

    Assert-PythonEnvironment -Label 'Vault Monitoring' -PythonPath $vaultPython -AllowedMinorVersions @(12) -RequiredModules @('fastapi','uvicorn','sqlalchemy','psycopg2','qdrant_client')
    Assert-PythonEnvironment -Label 'Branch Exterior Monitoring' -PythonPath $branchPython -AllowedMinorVersions @(11) -RequiredModules @('fastapi','uvicorn','sqlalchemy','cv2','aiosqlite','rfdetr','rtmlib')
    Assert-PythonEnvironment -Label 'Alert Service' -PythonPath $alertPython -AllowedMinorVersions @(11,12) -RequiredModules @('fastapi','uvicorn','sqlalchemy','httpx')

    $nodeVersionText = (& $nodeCommand.Source --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $nodeVersionText -notmatch '^v?(\d+)\.(\d+)\.(\d+)') { throw 'Node.js could not report its version.' }
    $nodeVersion = [Version]::new([int]$matches[1], [int]$matches[2], [int]$matches[3])
    if (-not (($nodeVersion.Major -eq 20 -and $nodeVersion -ge [Version]'20.19.0') -or ($nodeVersion.Major -ge 22 -and $nodeVersion -ge [Version]'22.12.0'))) {
        throw "Vite requires Node 20.19+ or 22.12+; found $nodeVersionText."
    }
    Write-Host "PASS  Node.js $nodeVersionText and npm.cmd $((& $npmCommand.Source --version 2>&1 | Out-String).Trim())" -ForegroundColor Green

    $vaultEnvPath = Join-Path $vaultDir '.env'
    $branchEnvPath = Join-Path $branchDir '.env'
    $frontendEnvPath = Join-Path $frontendDir '.env'
    foreach ($file in @($vaultEnvPath, $branchEnvPath, $frontendEnvPath)) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Required local configuration file is missing: $file" }
    }
    $vaultEnv = Get-LauncherEnvFile -Path $vaultEnvPath
    $branchEnv = Get-LauncherEnvFile -Path $branchEnvPath
    $frontendEnv = Get-LauncherEnvFile -Path $frontendEnvPath
    $frontendLocalEnv = Get-LauncherEnvFile -Path (Join-Path $frontendDir '.env.local')

    $databaseUrl = Get-LauncherEnvValue -Values $vaultEnv -Name 'DATABASE_URL'
    $database = Get-LauncherUrlParts -Value $databaseUrl -AllowedSchemes @('postgresql','postgresql+psycopg2','postgresql+psycopg','postgres')
    if ($null -eq $database -or [string]::IsNullOrWhiteSpace($database.Path.Trim('/')) -or [string]::IsNullOrWhiteSpace($database.UserInfo)) {
        throw 'Vault DATABASE_URL is missing or is not a complete PostgreSQL URL. Configure it in backend\use_cases\vault_monitoring\.env; the value is never printed.'
    }
    if ($database.Host -match '^(your-|example|<)' -or $database.Path -match '^/(your-|example|<)') { throw 'Vault DATABASE_URL still contains an example placeholder.' }
    $qdrantUrl = Get-LauncherEnvValue -Values $vaultEnv -Name 'QDRANT_URL'
    $qdrantKey = Get-LauncherEnvValue -Values $vaultEnv -Name 'QDRANT_API_KEY'
    $qdrant = Get-LauncherUrlParts -Value $qdrantUrl -AllowedSchemes @('http','https')
    if ($null -eq $qdrant -or [string]::IsNullOrWhiteSpace($qdrantKey)) { throw 'Vault QDRANT_URL and QDRANT_API_KEY must be configured in backend\use_cases\vault_monitoring\.env; values are never printed.' }
    if ($qdrant.Host -match '^(your-|example|<)' -or $qdrantKey -match '^(your-|example|<|replace)') { throw 'Vault Qdrant configuration still contains an example placeholder.' }
    $postgresReachability = Test-LauncherTcpEndpoint -HostName $database.Host -Port $database.Port
    if ($postgresReachability -eq 'unreachable') { throw 'The configured local PostgreSQL endpoint is not accepting TCP connections. Start PostgreSQL or correct Vault configuration; no credentials were displayed.' }
    if ($postgresReachability -eq 'reachable') { Write-Host 'PASS  Configured local PostgreSQL TCP endpoint is reachable' -ForegroundColor Green }
    else { Add-LauncherWarning 'PostgreSQL is configured at a non-loopback host and was not probed before startup. Vault health will verify database access.' }
    $qdrantReachability = Test-LauncherTcpEndpoint -HostName $qdrant.Host -Port $qdrant.Port
    if ($qdrantReachability -eq 'unreachable') { throw 'The configured local Qdrant endpoint is not accepting TCP connections. Start Qdrant or correct Vault configuration; no credentials were displayed.' }
    if ($qdrantReachability -eq 'reachable') { Write-Host 'PASS  Configured local Qdrant TCP endpoint is reachable' -ForegroundColor Green }
    else { Add-LauncherWarning 'Qdrant is configured at a non-loopback host and was not probed before startup. Vault health will verify connection and authentication.' }
    Write-Host 'PASS  Vault PostgreSQL and Qdrant configuration is present' -ForegroundColor Green

    $vaultFrontendUrl = Get-LauncherEnvValue -Values $frontendEnv -Name 'VITE_VAULT_API_BASE_URL'
    if (-not $vaultFrontendUrl) { $vaultFrontendUrl = Get-LauncherEnvValue -Values $frontendEnv -Name 'VITE_API_BASE_URL' }
    $branchFrontendUrl = Get-LauncherEnvValue -Values $frontendEnv -Name 'VITE_BRANCH_EXTERIOR_API_BASE_URL'
    $vaultFrontend = Get-LauncherUrlParts -Value $vaultFrontendUrl -AllowedSchemes @('http','https')
    $branchFrontend = Get-LauncherUrlParts -Value $branchFrontendUrl -AllowedSchemes @('http','https')
    if ($null -eq $vaultFrontend -or $vaultFrontend.Port -ne 8010 -or $vaultFrontend.Host -notin @('localhost','127.0.0.1')) { throw 'frontend\.env must point Vault to http://localhost:8010 or http://127.0.0.1:8010.' }
    if ($null -eq $branchFrontend -or $branchFrontend.Port -ne 8011 -or $branchFrontend.Host -notin @('localhost','127.0.0.1')) { throw 'frontend\.env must point Branch Exterior to http://localhost:8011 or http://127.0.0.1:8011.' }
    $alertProxyUrl = Get-ValueFromMaps -Maps @($frontendEnv, $frontendLocalEnv) -Name 'ALERT_SERVICE_URL'
    if (-not $alertProxyUrl) { $alertProxyUrl = 'http://127.0.0.1:8012' }
    $alertProxy = Get-LauncherUrlParts -Value $alertProxyUrl -AllowedSchemes @('http','https')
    if ($null -eq $alertProxy -or $alertProxy.Port -ne 8012 -or $alertProxy.Host -notin @('localhost','127.0.0.1')) { throw 'Vite ALERT_SERVICE_URL must point to the local Alert Service on port 8012.' }
    Write-Host 'PASS  Frontend Vault, Branch, and Alert Service URLs match launcher ports' -ForegroundColor Green

    $alertEnvFile = Get-LauncherEnvFile -Path (Join-Path $alertDir '.env')
    $callerAlertEnv = @{}
    foreach ($name in $script:AlertServiceEnvNames) {
        $fromFile = Get-LauncherEnvValue -Values $alertEnvFile -Name $name
        if (-not [string]::IsNullOrEmpty($fromFile)) { $callerAlertEnv[$name] = $fromFile }
        $processValue = [Environment]::GetEnvironmentVariable($name, 'Process')
        if (-not [string]::IsNullOrEmpty($processValue)) { $callerAlertEnv[$name] = $processValue }
    }
    $producerCredentials = Get-LauncherEnvValue -Values $callerAlertEnv -Name 'ALERT_PRODUCER_CREDENTIALS'
    $operatorCredentials = Get-LauncherEnvValue -Values $callerAlertEnv -Name 'ALERT_OPERATOR_CREDENTIALS'
    if (-not (Test-AlertCredentialsMap -Value $producerCredentials -Kind producer)) { Add-LauncherWarning 'Alert Service producer credentials are not configured; Vault/Branch publication will not be usable until matching producer tokens are configured.' }
    if (-not (Test-AlertCredentialsMap -Value $operatorCredentials -Kind operator)) { Add-LauncherWarning 'Alert Service operator credentials are not configured; protected Alert Center API calls will fail until an operator token is configured.' }
    foreach ($name in @('ALERT_SERVICE_BASE_URL','ALERT_SERVICE_TOKEN')) {
        if ([string]::IsNullOrWhiteSpace((Get-LauncherEnvValue -Values $vaultEnv -Name $name))) { Add-LauncherWarning "Vault $name is unset; Vault alert publication is disabled."; break }
    }
    foreach ($name in @('ALERT_SERVICE_BASE_URL','ALERT_SERVICE_TOKEN')) {
        if ([string]::IsNullOrWhiteSpace((Get-LauncherEnvValue -Values $branchEnv -Name $name))) { Add-LauncherWarning "Branch $name is unset; Branch alert publication is disabled."; break }
    }
    $proxyToken = Get-ValueFromMaps -Maps @($frontendEnv, $frontendLocalEnv) -Name 'ALERT_SERVICE_OPERATOR_TOKEN'
    if ([string]::IsNullOrWhiteSpace($proxyToken) -and [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable('ALERT_SERVICE_OPERATOR_TOKEN','Process'))) { Add-LauncherWarning 'Frontend Alert Center proxy token is not configured; set ALERT_SERVICE_OPERATOR_TOKEN in frontend\.env.local.' }

    $portSpecs = @(
        @{ Name = 'Alert Service'; Port = 8012; Health = 'http://127.0.0.1:8012/health' },
        @{ Name = 'Vault Monitoring'; Port = 8010; Health = 'http://127.0.0.1:8010/api/v1/health' },
        @{ Name = 'Branch Exterior Monitoring'; Port = 8011; Health = 'http://127.0.0.1:8011/api/health' },
        @{ Name = 'Frontend'; Port = 3000; Health = 'http://127.0.0.1:3000/' }
    )

    $existingEntries = @(Read-LauncherManifest -Path $manifestPath)
    if ($existingEntries.Count -gt 0) {
        $activeEntries = @($existingEntries | Where-Object { $null -ne (Get-LauncherProcessIdentity -Entry $_) })
        if ($activeEntries.Count -gt 0) {
            $activeNames = ($activeEntries | ForEach-Object { $_.Service }) -join ', '
            throw "This launcher already owns active process(es): $activeNames. Run .\stop-all.ps1 before starting another set."
        }
        Remove-Item -LiteralPath $manifestPath -Force
        Write-Host 'INFO  Removed stale launcher metadata; no recorded process identity matched.'
    }
    foreach ($spec in $portSpecs) { Assert-LocalPortIsFree -Service $spec.Name -Port $spec.Port -HealthUri $spec.Health }

    if ($PreflightOnly) {
        Write-Host 'PREFLIGHT PASSED. No application process was started.' -ForegroundColor Green
        exit 0
    }

    if (-not (Test-Path -LiteralPath $launcherDir -PathType Container)) { New-Item -ItemType Directory -Path $launcherDir -Force | Out-Null }
    try { $lockStream = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
    catch { throw 'Another start-all invocation may be running. If it is not, remove only the stale .launcher\start.lock file after confirming no launcher is active.' }
    if (-not (Test-Path -LiteralPath $logDir -PathType Container)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $launchSpecs = @(
        @{ Service = 'Alert Service'; Exe = $alertPython; Args = @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8012'); Cwd = $alertDir; Marker = 'uvicorn app.main:app --host 127.0.0.1 --port 8012'; Uri = 'http://127.0.0.1:8012/health'; Timeout = $AlertTimeoutSeconds; Env = $callerAlertEnv },
        @{ Service = 'Vault Monitoring'; Exe = $vaultPython; Args = @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8010'); Cwd = $vaultDir; Marker = 'uvicorn app.main:app --host 127.0.0.1 --port 8010'; Uri = 'http://127.0.0.1:8010/api/v1/health'; Timeout = $VaultTimeoutSeconds; Env = @{} },
        @{ Service = 'Branch Exterior Monitoring'; Exe = $branchPython; Args = @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8011'); Cwd = $branchDir; Marker = 'uvicorn app.main:app --host 127.0.0.1 --port 8011'; Uri = 'http://127.0.0.1:8011/api/health'; Timeout = $BranchTimeoutSeconds; Env = @{} },
        @{ Service = 'Frontend'; Exe = $nodeCommand.Source; Args = @('node_modules/vite/bin/vite.js','--host','127.0.0.1'); Cwd = $frontendDir; Marker = 'vite/bin/vite.js --host 127.0.0.1'; Uri = 'http://127.0.0.1:3000/'; Timeout = $FrontendTimeoutSeconds; Env = @{} }
    )

    foreach ($spec in $launchSpecs) {
        $safeName = $spec.Service.ToLowerInvariant() -replace '[^a-z0-9]+','-'
        $stdout = Join-Path $logDir "$safeName-$timestamp.stdout.log"
        $stderr = Join-Path $logDir "$safeName-$timestamp.stderr.log"
        $entry = Start-LauncherProcess -Service $spec.Service -FilePath $spec.Exe -ArgumentList $spec.Args `
            -WorkingDirectory $spec.Cwd -CommandMarker $spec.Marker -StdoutPath $stdout -StderrPath $stderr `
            -ScopedEnvironment $spec.Env
        $started.Add($entry)
        Write-LauncherManifest -Path $manifestPath -Processes $started.ToArray()
        Write-Host "START $($spec.Service) (PID $($entry.ProcessId)); waiting for $($spec.Uri)" -ForegroundColor Cyan
        Wait-LauncherEndpoint -Service $spec.Service -Uri $spec.Uri -Entry $entry -TimeoutSeconds $spec.Timeout | Out-Null
        Write-Host "READY $($spec.Service): $($spec.Uri) (health verified)" -ForegroundColor Green
    }

    Write-Host ''
    Write-Host 'All four applications passed their readiness checks.' -ForegroundColor Green
    Write-Host "Logs: $logDir"
    Write-Host "Process metadata (no secrets): $manifestPath"
    if ($warnings.Count -gt 0) { Write-Host 'Some optional alert workflows need the credentials listed in the warnings above.' -ForegroundColor Yellow }
    Write-Host 'Stop the launcher-owned applications with .\stop-all.ps1.'
} catch {
    Write-Host "ERROR  $($_.Exception.Message)" -ForegroundColor Red
    if ($started.Count -gt 0) {
        Write-Host 'Cleaning up only processes started by this invocation...' -ForegroundColor Yellow
        $remaining = New-Object System.Collections.Generic.List[object]
        $cleanupEntries = $started.ToArray()
        [array]::Reverse($cleanupEntries)
        foreach ($entry in $cleanupEntries) {
            $result = Stop-LauncherEntry -Entry $entry
            if ($result -eq 'stopped' -or $result -eq 'stale-or-identity-mismatch') {
                Write-Host "STOP  $($entry.Service): $result"
            } else {
                Write-Host "WARN  Could not stop $($entry.Service) safely; retained its metadata for stop-all.ps1. Logs: $($entry.StdoutPath); $($entry.StderrPath)" -ForegroundColor Yellow
                $remaining.Add($entry)
            }
        }
        if ($remaining.Count -gt 0) { Write-LauncherManifest -Path $manifestPath -Processes $remaining.ToArray() }
        elseif (Test-Path -LiteralPath $manifestPath) { Remove-Item -LiteralPath $manifestPath -Force }
    }
    exit 1
} finally {
    if ($null -ne $lockStream) {
        $lockStream.Dispose()
        if (Test-Path -LiteralPath $lockPath) { Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue }
    }
}
