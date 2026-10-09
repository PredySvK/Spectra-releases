# Build and publish an installer from the source tag at HEAD (ADR §1.140).
# Notes are supplied verbatim as a UTF-8 file; no source is uploaded.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][string]$NotesPath,
    [string]$IsccPath
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
# Resolve relative notes paths before changing the caller's working directory.
$notes = (Resolve-Path -LiteralPath $NotesPath).Path
if (-not (Test-Path -LiteralPath $notes -PathType Leaf)) {
    throw 'NotesPath must name a UTF-8 patch-notes file.'
}

function Invoke-Checked {
    & $args[0] $args[1..($args.Count - 1)]
    if ($LASTEXITCODE -ne 0) { throw "Failed ($LASTEXITCODE): $args" }
}

Push-Location $root
try {
    $dirty = Invoke-Checked git status --porcelain --untracked-files=all
    if ($dirty) { throw 'Working tree is dirty. Commit or move pending files before publishing; nothing uploaded.' }
    if ($Tag -cnotmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') {
        throw 'Release tag must have the form X.Y.Z; nothing uploaded.'
    }
    & git show-ref --verify --quiet "refs/tags/$Tag"
    if ($LASTEXITCODE -ne 0) { throw "Source tag $Tag does not exist; nothing uploaded." }
    $tagCommit = Invoke-Checked git rev-parse --verify "refs/tags/$Tag^{commit}"
    $headCommit = Invoke-Checked git rev-parse HEAD
    if ($tagCommit -ne $headCommit) {
        throw "Tag $Tag does not point to HEAD. Check out its commit before publishing; nothing uploaded."
    }
    $identity = Invoke-Checked py -3.14 -c 'import json; from core.app_metadata import APP_NAME, APP_VERSION, RELEASES_REPO; print(json.dumps([APP_NAME, APP_VERSION, RELEASES_REPO]))'
    $identityValues = $identity | ConvertFrom-Json
    $name = $identityValues[0]
    $version = $identityValues[1]
    $repository = $identityValues[2]
    if ($Tag -cne $version) {
        throw "Tag $Tag does not match App version $version; nothing uploaded."
    }
    Invoke-Checked gh auth status
    $visibility = Invoke-Checked gh repo view $repository --json visibility --jq .visibility
    if ($visibility -ne 'PUBLIC') { throw "Release repository $repository must be public; nothing uploaded." }

    & (Join-Path $PSScriptRoot 'build_exe.ps1') -IsccPath $IsccPath
    $installer = Join-Path $root "dist\$name-$version-setup.exe"
    if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
        throw "Build did not produce $installer; nothing uploaded."
    }
    # Catch source edits made while the lengthy build was running.
    $dirty = Invoke-Checked git status --porcelain --untracked-files=all
    $currentHead = Invoke-Checked git rev-parse HEAD
    $currentTag = Invoke-Checked git rev-parse --verify "refs/tags/$Tag^{commit}"
    if ($dirty -or $currentHead -ne $headCommit -or $currentTag -ne $tagCommit) {
        throw 'Source changed during the build. Restore the tagged clean tree and rebuild; nothing uploaded.'
    }
    # The public repository has its own tag: never push private source commits
    # there, and never pass the private source SHA as --target.
    Invoke-Checked gh release create $Tag $installer --repo $repository `
        --title "$name $version" --notes-file $notes
} finally { Pop-Location }
