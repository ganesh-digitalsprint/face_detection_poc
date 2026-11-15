param([ValidateSet('lite', 'full')][string]$Model = 'lite')
$ErrorActionPreference = 'Stop'

$modelUrl = 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task'
$expectedSha256 = '59929E1D1EE95287735DDD833B19CF4AC46D29BC7AFDDBBF6753C459690D574A'
if ($Model -eq 'full') {
    $modelUrl = $modelUrl.Replace('pose_landmarker_lite', 'pose_landmarker_full')
    $expectedSha256 = '5134A3AAD27A58B93DA0088D431F366DA362B44E3CCFBE3462B3827A839011B1'
}
$modelDirectory = Join-Path $PSScriptRoot '..\app\models'
$modelPath = Join-Path $modelDirectory "pose_landmarker_$Model.task"
$downloadPath = "$modelPath.download"

New-Item -ItemType Directory -Force -Path $modelDirectory | Out-Null
if (Test-Path -LiteralPath $modelPath) {
    $currentHash = (Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash
    if ($currentHash -eq $expectedSha256) {
        Write-Output "Pose model already present: $modelPath"
        exit 0
    }
    throw "Existing pose model has an unexpected SHA-256 hash: $modelPath"
}

Invoke-WebRequest -Uri $modelUrl -OutFile $downloadPath
$downloadHash = (Get-FileHash -LiteralPath $downloadPath -Algorithm SHA256).Hash
if ($downloadHash -ne $expectedSha256) {
    Remove-Item -LiteralPath $downloadPath -Force
    throw 'Downloaded pose model failed SHA-256 verification.'
}
Move-Item -LiteralPath $downloadPath -Destination $modelPath
Write-Output "Installed official MediaPipe Pose Landmarker $Model model: $modelPath"
