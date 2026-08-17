param(
    [Parameter(Mandatory=$true)]
    [string]$ArtifactDirectory
)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Src = (Resolve-Path $ArtifactDirectory).Path
$Files = @(
    'backend/requirements.lock',
    'backend/requirements-dev.lock',
    'backend/dependency-lock-metadata.json',
    'frontend/package.json',
    'frontend/package-lock.json'
)
foreach ($Rel in $Files) {
    $Source = Join-Path $Src $Rel
    if (-not (Test-Path $Source)) { throw "Artifact is missing $Rel" }
    $Dest = Join-Path $Root $Rel
    New-Item -ItemType Directory -Force -Path (Split-Path $Dest) | Out-Null
    Copy-Item -Force $Source $Dest
}
python (Join-Path $Root 'scripts/check_wave0_1_baseline.py') --strict
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Applied W0.1 generated locks. Review git diff, then run the normal CI matrix before marking W0.1 PASS.'
