$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts/launcher-common.ps1')
$script:healthBody = ''
function Invoke-WebRequest {
    param($Uri, [switch]$UseBasicParsing, $TimeoutSec, $ErrorAction)
    return [pscustomobject]@{StatusCode=200; Content=$script:healthBody}
}
$checks = 0
foreach ($case in @(
    @{Body='{"service":"face_mask","status":"ok","db":"ok"}'; Expected=$true},
    @{Body='{"service":"face_mask","status":"degraded","db":"ok"}'; Expected=$false},
    @{Body='{"service":"face_mask","status":"ok","db":"unavailable"}'; Expected=$false},
    @{Body='{"service":"other_service","status":"ok","db":"ok"}'; Expected=$false},
    @{Body='{"status":"ok"}'; Expected=$false},
    @{Body='not-json'; Expected=$false}
)) {
    $script:healthBody = $case.Body
    $actual = Test-LauncherHealthyEndpoint -Service 'Face Mask Monitoring' -Uri 'http://127.0.0.1:8014/api/health'
    if ($actual -ne $case.Expected) { throw 'Face Mask readiness accepted an incorrect health response.' }
    $checks++
}
foreach ($file in @('start-all.ps1','stop-all.ps1','scripts/launcher-common.ps1')) {
    $tokens=$null; $parseErrors=$null
    [Management.Automation.Language.Parser]::ParseFile((Join-Path (Split-Path -Parent $PSScriptRoot) $file),[ref]$tokens,[ref]$parseErrors) | Out-Null
    if ($parseErrors.Count) { throw "PowerShell syntax error in $file" }
    $checks++
}
Write-Host "All $checks Face Mask launcher checks passed."
