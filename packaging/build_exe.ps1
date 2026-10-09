# packaging/build_exe.ps1
# Builds dist\Spectra\Spectra.exe and dist\Spectra-<version>-setup.exe
# created from requirements.txt only -- never from the development .venv, which
# carries unrelated packages (ADR §1.140).
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1
#
# Prerequisites: Python 3.14 through `py`, Inno Setup 6 (or -IsccPath).

param([string]$IsccPath)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root '.build-venv'
$python = Join-Path $venv 'Scripts\python.exe'

if (-not $IsccPath) {
    $compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($compiler) { $IsccPath = $compiler.Source }
    else {
        $IsccPath = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
            (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
            (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
        ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
}
if (-not $IsccPath -or -not (Test-Path -LiteralPath $IsccPath)) {
    throw 'Inno Setup 6 not found. Install it or supply -IsccPath.'
}

function Invoke-Checked {
    & $args[0] $args[1..($args.Count - 1)]
    if ($LASTEXITCODE -ne 0) { throw "Failed ($LASTEXITCODE): $args" }
}

# --clear wipes the venv on every run, so a package dropped from requirements.txt
# cannot linger in the build. pip's download cache keeps this fast.
Invoke-Checked py -3.14 -m venv --clear $venv
Invoke-Checked $python -m pip install --disable-pip-version-check -r (Join-Path $root 'requirements.txt') 'pyinstaller==6.22.3'
Invoke-Checked $python -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $root 'dist') `
    --workpath (Join-Path $root 'build') `
    (Join-Path $PSScriptRoot 'spectra.spec')
# The work folder holds an intermediate Spectra.exe without _internal next to it;
# started by mistake it fails with "Failed to load Python DLL". --clean rebuilds
# it anyway, so nothing is lost.
$workFolder = [IO.Path]::GetFullPath((Join-Path $root 'build'))
if ($workFolder -ne ([IO.Path]::GetFullPath($root) + '\build')) {
    throw "Unexpected build folder: $workFolder"
}
Remove-Item -LiteralPath $workFolder -Recurse -Force

Invoke-Checked $python (Join-Path $PSScriptRoot 'third_party_licenses.py') `
    (Join-Path $root 'dist\Spectra\licenses')

# Run from the repository root so imports never depend on the caller's cwd.
Push-Location $root
try {
    $identity = & $python -c 'import json; from core.app_metadata import APP_NAME, APP_VERSION, APP_USER_MODEL_ID; print(json.dumps([APP_NAME, APP_VERSION, APP_USER_MODEL_ID]))'
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read app metadata.' }
    $identityValues = $identity | ConvertFrom-Json
    $name = $identityValues[0]
    $version = $identityValues[1]
    $appId = $identityValues[2]
    Invoke-Checked $IsccPath "/DAppName=$name" "/DAppVersion=$version" `
        "/DAppUserModelID=$appId" (Join-Path $PSScriptRoot 'spectra.iss')
} finally { Pop-Location }

Write-Host "Built $(Join-Path $root 'dist\Spectra\Spectra.exe')"
Write-Host "Built $(Join-Path $root "dist\$name-$version-setup.exe")"
