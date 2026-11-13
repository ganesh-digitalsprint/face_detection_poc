param([switch]$Apply)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$common = Join-Path $repo 'storage'
$backup = Join-Path $repo 'backups/storage-migration-20261112'
$manifestPath = Join-Path $repo 'docs/storage-migration-manifest.json'
$sources = @(
    @{ Key = 'legacy_branch'; Dir = 'backend/branch-exterior-monitoring/storage'; Owner = 'branch_exterior' },
    @{ Key = 'branch_exterior'; Dir = 'backend/use_cases/branch_exterior/storage'; Owner = 'branch_exterior' },
    @{ Key = 'face_mask'; Dir = 'backend/use_cases/face_mask/storage'; Owner = 'face_mask' },
    @{ Key = 'vault_monitoring'; Dir = 'backend/use_cases/vault_monitoring/storage'; Owner = 'vault_monitoring' }
)
$items = @()
foreach ($source in $sources) {
    $base = Join-Path $repo $source.Dir
    if (-not (Test-Path -LiteralPath $base)) { continue }
    foreach ($file in (Get-ChildItem -LiteralPath $base -Recurse -File)) {
        if ($file.Name -in @('app.db','.gitkeep') -or $file.Name -like 'app.db-*') { continue }
        $relative = $file.FullName.Substring($base.TrimEnd('\').Length + 1).Replace('\','/')
        $parts = $relative.Split('/')
        $category = $parts[0]
        if ($category -eq 'snapshots') { $category = 'screenshots' }
        if ($category -notin @('sample_videos','uploads','clips','screenshots','evidence','annotated','temp','guard_faces','alert_outbox')) { continue }
        $rest = ($parts | Select-Object -Skip 1) -join '/'
        if ($category -in @('clips','screenshots','evidence','guard_faces','alert_outbox')) { $rest = "$($source.Owner)/$rest" }
        $target = Join-Path $common ("$category/$rest")
        $saved = Join-Path $backup ("$($source.Key)/$relative")
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        $items += [pscustomobject]@{ old = $file.FullName; new = $target; backup = $saved; bytes = $file.Length; sha256 = $hash; action = 'pending' }
    }
}
$bytes = if ($items.Count) { ($items | Measure-Object -Property bytes -Sum).Sum } else { 0 }
Write-Output ("MEDIA_FILES={0} MEDIA_MB={1:N2} MODE={2}" -f $items.Count,($bytes/1MB),$(if($Apply){'apply'}else{'dry-run'}))
if (-not $Apply) { $items | Group-Object {Split-Path $_.new -Parent} | ForEach-Object {"$($_.Name): $($_.Count)"}; return }
if ($items.Count -eq 0) { Write-Output 'No source media remains; migration is already applied.'; return }
$available = (Get-PSDrive -Name D).Free
if ($available -lt ($bytes + 1GB)) { throw 'Insufficient free D: space for verified backup.' }
foreach ($item in $items) {
    New-Item -ItemType Directory -Path (Split-Path $item.backup -Parent) -Force | Out-Null
    if (-not (Test-Path -LiteralPath $item.backup)) { Copy-Item -LiteralPath $item.old -Destination $item.backup }
    if ((Get-FileHash -LiteralPath $item.backup -Algorithm SHA256).Hash -ne $item.sha256) { throw "Backup verification failed: $($item.old)" }
}
Write-Output "Verified backup of $($items.Count) files at $backup"
foreach ($item in $items) {
    New-Item -ItemType Directory -Path (Split-Path $item.new -Parent) -Force | Out-Null
    if (Test-Path -LiteralPath $item.new) {
        if ((Get-FileHash -LiteralPath $item.new -Algorithm SHA256).Hash -ne $item.sha256) { throw "Different content at destination: $($item.new)" }
        $item.action = 'deduplicated'
        Remove-Item -LiteralPath $item.old
    } else {
        Move-Item -LiteralPath $item.old -Destination $item.new
        if ((Get-FileHash -LiteralPath $item.new -Algorithm SHA256).Hash -ne $item.sha256) { throw "Move verification failed: $($item.new)" }
        $item.action = 'moved'
    }
}
$items | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding utf8
Write-Output "Migrated $($items.Count) files; manifest: $manifestPath"
