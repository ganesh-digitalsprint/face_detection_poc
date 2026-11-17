# Start only the local Alert Service and Vite with a shared, temporary operator key.
# No key is written to disk or passed on a command line. Stop existing listeners first.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath($PSScriptRoot)
$alertDir = Join-Path $repo 'backend/services/alert_service'
$frontendDir = Join-Path $repo 'frontend'
$uvicorn = Join-Path $alertDir '.venv/Scripts/uvicorn.exe'
$node = (Get-Command node -ErrorAction Stop).Source
$vite = Join-Path $frontendDir 'node_modules/vite/bin/vite.js'

foreach ($port in @(8012, 3000)) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if ($listener) { throw "Port $port is already in use. Stop its existing project server before running this launcher." }
}
if (-not (Test-Path -LiteralPath $uvicorn -PathType Leaf)) { throw 'Alert Service virtual environment is missing.' }
if (-not (Test-Path -LiteralPath $vite -PathType Leaf)) { throw 'Frontend dependencies are missing.' }

$bytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
$token = ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
$credentials = @{ $token = @{ actor_id = 'local-browser'; use_cases = @('branch_exterior', 'face_mask', 'vault_monitoring', 'grill_gate') } } | ConvertTo-Json -Depth 4 -Compress
$oldCredentials = [Environment]::GetEnvironmentVariable('ALERT_OPERATOR_CREDENTIALS', 'Process')
$oldProxyToken = [Environment]::GetEnvironmentVariable('ALERT_SERVICE_OPERATOR_TOKEN', 'Process')
try {
    [Environment]::SetEnvironmentVariable('ALERT_OPERATOR_CREDENTIALS', $credentials, 'Process')
    [Environment]::SetEnvironmentVariable('ALERT_SERVICE_OPERATOR_TOKEN', $token, 'Process')
    $alert = Start-Process -FilePath $uvicorn -ArgumentList @('app.main:app', '--host', '127.0.0.1', '--port', '8012') -WorkingDirectory $alertDir -WindowStyle Hidden -PassThru
    $frontend = Start-Process -FilePath $node -ArgumentList @($vite, '--host', '127.0.0.1', '--port', '3000', '--strictPort') -WorkingDirectory $frontendDir -WindowStyle Hidden -PassThru
} finally {
    [Environment]::SetEnvironmentVariable('ALERT_OPERATOR_CREDENTIALS', $oldCredentials, 'Process')
    [Environment]::SetEnvironmentVariable('ALERT_SERVICE_OPERATOR_TOKEN', $oldProxyToken, 'Process')
}
Write-Host "Started local Alert Service (PID $($alert.Id)) and frontend (PID $($frontend.Id))."
Write-Host 'The operator key is process-local and will change on the next paired restart.'
