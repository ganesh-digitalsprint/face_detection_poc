Set-StrictMode -Version 2.0

$script:LauncherSensitiveEnvPattern = '^(DEBUG|DATABASE_URL|QDRANT_.*|VAULT_.*|RTSP_.*|WEBCAM_.*|VIDEO_.*|CLOUDINARY_.*|EVIDENCE_.*|ALERT_.*|DB_.*|API_KEY|CORS_.*|APP_.*|NOTIFY_WEBHOOK_URL|VITE_.*|INFERENCE_.*|FEDBANK_SHARED_PATH|CUDA_VISIBLE_DEVICES|COMPUTE_DEVICE|RFDETR_.*|PERSON_DETECTOR_BACKEND|SINGLE_ACTIVE_CAMERA|PROCESSING_FPS|FRAME_WIDTH|CPU_THREADS|DETECT_.*|WEAPON_.*|POSE_.*|FIGHT_.*|RUN_.*|BAG_.*|ZONE_.*|UNATTENDED_BAG_SECONDS|FACE_RECOGNITION_ENABLED)$'
$script:AlertServiceEnvNames = @(
    'ALERT_DATABASE_URL',
    'ALERT_PRODUCER_CREDENTIALS',
    'ALERT_OPERATOR_CREDENTIALS',
    'ALERT_NOTIFICATION_WEBHOOK_URL',
    'ALERT_NOTIFICATION_POLL_SECONDS',
    'ALERT_NOTIFICATION_MAX_ATTEMPTS'
)

function Get-LauncherEnvFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    $values = @{}
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $values
    }

    foreach ($line in [System.IO.File]::ReadAllLines($Path)) {
        if ($line -match '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            $name = $matches[1]
            $value = $matches[2]
            if ($value.Length -ge 2 -and (($value[0] -eq '"' -and $value[$value.Length - 1] -eq '"') -or
                    ($value[0] -eq "'" -and $value[$value.Length - 1] -eq "'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            } elseif ($value -match '\s+#') {
                $value = ($value -replace '\s+#.*$', '').Trim()
            }
            $values[$name] = $value
        }
    }
    return $values
}

function Get-LauncherEnvValue {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Values,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if ($Values.ContainsKey($Name)) { return [string]$Values[$Name] }
    return ''
}

function Get-LauncherUrlParts {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string[]]$AllowedSchemes
    )

    $parsed = $null
    if (-not [Uri]::TryCreate($Value, [UriKind]::Absolute, [ref]$parsed)) { return $null }
    if ($AllowedSchemes -notcontains $parsed.Scheme -or [string]::IsNullOrWhiteSpace($parsed.Host)) { return $null }
    return [pscustomobject]@{
        Scheme = $parsed.Scheme
        Host = $parsed.Host
        Port = $parsed.Port
        Path = $parsed.AbsolutePath
        UserInfo = $parsed.UserInfo
    }
}

function Test-LauncherTcpEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$HostName,
        [Parameter(Mandatory = $true)][int]$Port,
        [int]$TimeoutMilliseconds = 900
    )

    $isLoopback = $HostName -eq 'localhost' -or $HostName -eq '::1' -or $HostName -match '^127(?:\.\d{1,3}){3}$'
    if (-not $isLoopback) { return 'not-probed' }

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne($TimeoutMilliseconds)) { return 'unreachable' }
        $client.EndConnect($pending)
        return 'reachable'
    } catch {
        return 'unreachable'
    } finally {
        $client.Close()
    }
}

function Get-LauncherPortListeners {
    param([Parameter(Mandatory = $true)][int]$Port)

    $probe = [System.Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    try {
        $probe.Start()
        $probe.Stop()
        return @()
    } catch {
        try { $probe.Stop() } catch { }
        $processIds = @()
        try {
            $rows = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
            $processIds += @($rows | ForEach-Object { [int]$_.OwningProcess })
        } catch { }
        if ($processIds.Count -eq 0) {
            $netstat = & "$env:SystemRoot\System32\netstat.exe" -ano -p tcp 2>$null
            foreach ($row in $netstat) {
                if ($row -match '^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$' -and [int]$matches[1] -eq $Port) {
                    $processIds += [int]$matches[2]
                }
            }
        }
        if ($processIds.Count -eq 0) { return @(-1) }
        return @($processIds | Sort-Object -Unique)
    }
}

function Test-LauncherHealthyEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$Service,
        [int]$TimeoutSeconds = 2
    )

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec $TimeoutSeconds -ErrorAction Stop
        if ($response.StatusCode -ne 200) { return $false }
        if ($Service -eq 'Frontend') { return $response.Content -match 'Vite|/src/main\.(jsx|tsx?)|<div id="root"' }

        $body = $response.Content | ConvertFrom-Json -ErrorAction Stop
        if ($Service -eq 'Alert Service') {
            return $body.status -eq 'ok' -and $body.service -eq 'alert-service'
        }
        if ($Service -eq 'Vault Monitoring') {
            return $body.status -eq 'ok' -and $body.database -eq 'ok' -and $body.qdrant -eq 'ok'
        }
        if ($Service -eq 'Branch Exterior Monitoring') {
            return $body.status -eq 'ok' -and $null -ne $body.routes_checked -and $body.zone_schema.ok -eq $true
        }
    } catch {
        return $false
    }
    return $false
}

function Get-LauncherProcessIdentity {
    param([Parameter(Mandatory = $true)]$Entry)

    try {
        $proc = Get-Process -Id ([int]$Entry.ProcessId) -ErrorAction Stop
        $exePath = [string]$proc.Path
        if ([string]::IsNullOrWhiteSpace($exePath)) { $exePath = [string]$proc.MainModule.FileName }
        if ([string]::IsNullOrWhiteSpace($exePath)) { return $null }
        if (-not [string]::Equals([IO.Path]::GetFullPath($exePath), [IO.Path]::GetFullPath([string]$Entry.ExecutablePath), [StringComparison]::OrdinalIgnoreCase)) {
            return $null
        }
        $created = $proc.StartTime.ToUniversalTime()
        $expectedTicks = ([DateTime]::Parse([string]$Entry.StartedAtUtc, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind)).ToUniversalTime().Ticks
        if ([Math]::Abs($created.Ticks - $expectedTicks) -gt [TimeSpan]::FromSeconds(3).Ticks) { return $null }

        # CIM command-line validation strengthens the identity check when Windows permits it.
        # PID, executable path, and process creation time remain the required checks; some managed
        # PowerShell sessions deny Win32_Process access even to same-user child processes.
        try {
            $details = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$Entry.ProcessId)" -ErrorAction Stop
            if ($null -ne $details -and -not [string]::IsNullOrWhiteSpace($details.CommandLine) -and
                $details.CommandLine.IndexOf([string]$Entry.CommandMarker, [StringComparison]::OrdinalIgnoreCase) -lt 0) { return $null }
        } catch { }
        return $proc
    } catch {
        return $null
    }
}

function Read-LauncherManifest {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return @() }
    try {
        $document = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        if ($document.Version -ne 1 -or $null -eq $document.Processes) { throw 'manifest shape is invalid' }
        return @($document.Processes)
    } catch {
        throw "Launcher process metadata is unreadable at '$Path'. Do not delete it while services may be running; inspect it and verify process identities first."
    }
}

function Write-LauncherManifest {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object[]]$Processes
    )
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $tempPath = "$Path.tmp"
    $document = [ordered]@{ Version = 1; Processes = @($Processes) }
    $json = $document | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($tempPath, $json, (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $tempPath -Destination $Path -Force | Out-Null
}

function Stop-LauncherEntry {
    param([Parameter(Mandatory = $true)]$Entry)

    $process = Get-LauncherProcessIdentity -Entry $Entry
    if ($null -eq $process) { return 'stale-or-identity-mismatch' }
    try {
        Stop-Process -Id ([int]$Entry.ProcessId) -Force -ErrorAction Stop
        $processId = [int]$Entry.ProcessId
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Milliseconds 100
            if ($null -eq (Get-LauncherProcessIdentity -Entry $Entry)) { return 'stopped' }
        }
        return 'still-running'
    } catch {
        if (-not (Get-Process -Id ([int]$Entry.ProcessId) -ErrorAction SilentlyContinue)) { return 'stopped' }
        return 'stop-failed'
    }
}

function Start-LauncherProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$CommandMarker,
        [Parameter(Mandatory = $true)][string]$StdoutPath,
        [Parameter(Mandatory = $true)][string]$StderrPath,
        [hashtable]$ScopedEnvironment = @{}
    )

    $saved = @{}
    foreach ($item in @(Get-ChildItem Env: | Where-Object { $_.Name -match $script:LauncherSensitiveEnvPattern })) {
        $saved[$item.Name] = $item.Value
        Remove-Item "Env:$($item.Name)" -ErrorAction SilentlyContinue
    }
    try {
        foreach ($name in $ScopedEnvironment.Keys) { Set-Item "Env:$name" ([string]$ScopedEnvironment[$name]) }
        $process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory `
            -WindowStyle Hidden -PassThru -RedirectStandardOutput $StdoutPath -RedirectStandardError $StderrPath -ErrorAction Stop
    } finally {
        foreach ($name in $ScopedEnvironment.Keys) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
        foreach ($name in $saved.Keys) { Set-Item "Env:$name" $saved[$name] }
    }

    $process.Refresh()
    $entry = [pscustomobject]@{
        Service = $Service
        ProcessId = [int]$process.Id
        ExecutablePath = [IO.Path]::GetFullPath($FilePath)
        StartedAtUtc = $process.StartTime.ToUniversalTime().ToString('o', [Globalization.CultureInfo]::InvariantCulture)
        WorkingDirectory = [IO.Path]::GetFullPath($WorkingDirectory)
        CommandMarker = $CommandMarker
        StdoutPath = [IO.Path]::GetFullPath($StdoutPath)
        StderrPath = [IO.Path]::GetFullPath($StderrPath)
    }
    return $entry
}

function Wait-LauncherEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)]$Entry,
        [int]$TimeoutSeconds = 60
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($null -eq (Get-LauncherProcessIdentity -Entry $Entry)) {
            throw "$Service exited before its health check passed. Logs: '$($Entry.StdoutPath)' and '$($Entry.StderrPath)'."
        }
        if (Test-LauncherHealthyEndpoint -Uri $Uri -Service $Service -TimeoutSeconds 2) { return $true }
        Start-Sleep -Milliseconds 750
    }
    throw "$Service did not pass its health check within $TimeoutSeconds seconds. Logs: '$($Entry.StdoutPath)' and '$($Entry.StderrPath)'."
}
