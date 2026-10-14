# Offers a source update when Spectra-releases has a newer release. Always exits 0: the launcher goes on.
# Updates by `git pull` when the folder is a clone, otherwise by overlaying the release ZIP.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

try {
    $cur = [version](Select-String -Path "$root\core\app_metadata.py" -Pattern 'APP_VERSION = "([^"]+)"').Matches[0].Groups[1].Value
    $rel = Invoke-RestMethod 'https://api.github.com/repos/PredySvK/Spectra-releases/releases/latest' -TimeoutSec 10
    $new = [version]$rel.tag_name
} catch { exit 0 }  # offline or API hiccup: just start the app
if ($new -le $cur) { exit 0 }
if ((Read-Host "Spectra $new is available (you have $cur). Update? [A/N]") -notmatch '^[aAyY]') { exit 0 }

function Find-Git {
    $g = Get-Command git -ErrorAction SilentlyContinue
    if ($g) { return $g.Source }
    $p = "$env:ProgramFiles\Git\cmd\git.exe"
    if (Test-Path $p) { return $p }
}

try {
    $git = $null
    if (Test-Path "$root\.git") {
        $git = Find-Git
        if (-not $git -and (Read-Host 'Git is not installed. Install it now (winget)? [A/N]') -match '^[aAyY]') {
            winget install --id Git.Git -e --source winget
            $git = Find-Git
        }
    }
    if ($git) {
        & $git -C $root pull --ff-only
        if ($LASTEXITCODE) { throw 'git pull failed' }
    } else {
        # ponytail: files deleted in a newer release stay behind; use the git path to avoid that
        $tmp = Join-Path $env:TEMP "spectra-$new"
        Remove-Item "$tmp.zip", $tmp -Recurse -Force -ErrorAction SilentlyContinue
        Invoke-WebRequest $rel.zipball_url -OutFile "$tmp.zip"
        Expand-Archive "$tmp.zip" $tmp
        Copy-Item "$tmp\*\*" $root -Recurse -Force
        Remove-Item "$tmp.zip", $tmp -Recurse -Force
    }
    Write-Host "Updated to $new."
} catch {
    Write-Host "Update failed: $_"
    Read-Host 'Press Enter to start the current version' | Out-Null
}
