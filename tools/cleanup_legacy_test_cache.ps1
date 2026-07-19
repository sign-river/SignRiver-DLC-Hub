[CmdletBinding()]
param(
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$cacheRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "cache")).TrimEnd("\")
$expectedCacheRoot = [IO.Path]::GetFullPath(
    (Join-Path (Split-Path -Parent $PSScriptRoot) "cache")
).TrimEnd("\")

if (-not [StringComparer]::OrdinalIgnoreCase.Equals($cacheRoot, $expectedCacheRoot)) {
    throw "Unexpected cache root: $cacheRoot"
}
if ((Split-Path -Leaf $cacheRoot) -cne "cache") {
    throw "Refusing to operate outside a cache directory: $cacheRoot"
}

# This is an exact list from the 2026-07-19 cache audit. Runtime directories
# such as downloads, packages, quarantine and ignored-task-records are never
# selected by this script.
$legacyNames = @(
    ".pytest-full-persistence-review",
    ".pytest-persistence-db-run2",
    ".pytest-persistence-db-run3",
    ".pytest-persistence-db-run4",
    ".pytest-persistence-db-run5",
    ".pytest-persistence-db-run6",
    "persistence-concurrency-0pjk8_r2",
    "persistence-concurrency-2kjh9b0h",
    "persistence-concurrency-a58qva5o",
    "persistence-concurrency-fe60h20c",
    "persistence-concurrency-po11cga8",
    "persistence-concurrency-ys7ca0yl",
    "persistence-final-yxtnq62w",
    "persistence-selftest-s933wcji",
    "pytest-adapter-final",
    "pytest-adapter-final-2",
    "pytest-adapter-full",
    "pytest-adapter-mock",
    "pytest-adapter-review",
    "pytest-discovery",
    "pytest-discovery-final",
    "pytest-full-persistence",
    "pytest-persistence",
    "pytest-persistence-2",
    "pytest-persistence-corruption",
    "pytest-persistence-final",
    "pytest-persistence-unicode",
    "pytest-review-final",
    "pytest-stellaris-e2e",
    "pytest-stellaris-final",
    "pytest-stellaris-full",
    "pytest-stellaris-unit",
    "pytest-tmp",
    "repository-audit-ox6xsu1f",
    "repository-audit-surrogate-j791mj5o",
    "review-adapter-tests"
)

$cutoff = [datetime]"2026-07-13 00:00:00"
$targets = [Collections.Generic.List[IO.DirectoryInfo]]::new()

foreach ($name in $legacyNames) {
    $path = [IO.Path]::GetFullPath((Join-Path $cacheRoot $name))
    $parent = [IO.Path]::GetDirectoryName($path).TrimEnd("\")
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals($parent, $cacheRoot)) {
        throw "Target escaped the cache root: $path"
    }
    if (-not [IO.Directory]::Exists($path)) {
        continue
    }

    $item = Get-Item -LiteralPath $path -Force
    if (-not $item.PSIsContainer) {
        throw "Allowlisted target is not a directory: $path"
    }
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to process a reparse point: $path"
    }
    if ($item.LastWriteTime -ge $cutoff) {
        throw "Target is newer than the audited cutoff: $path"
    }
    $targets.Add($item)
}

if ($targets.Count -eq 0) {
    Write-Host "All audited legacy test directories are already gone."
    return
}

Write-Host "Audited legacy test cache (real packages are never selected):" -ForegroundColor Yellow
$targets | Select-Object FullName, LastWriteTime | Format-Table -AutoSize

if (-not $Apply) {
    Write-Host "`nPreview only. Re-run from Administrator PowerShell with -Apply to remove these directories."
    return
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from Administrator PowerShell."
}

$answer = Read-Host "Type DELETE-TEST-CACHE to continue"
if ($answer -cne "DELETE-TEST-CACHE") {
    throw "Cancelled."
}

$grant = "*$($identity.User.Value):(OI)(CI)F"
foreach ($item in $targets) {
    $path = $item.FullName

    & takeown.exe /F $path /R /D Y /SKIPSL | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to take ownership: $path"
    }
    & icacls.exe $path /grant:r $grant /T /C /L /Q | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to grant access: $path"
    }

    # Re-check the entire tree after taking ownership. A link or junction could
    # otherwise make a recursive delete escape the audited cache directory.
    $stack = [Collections.Generic.Stack[string]]::new()
    $stack.Push($path)
    while ($stack.Count -gt 0) {
        $directory = $stack.Pop()
        foreach ($entry in [IO.Directory]::EnumerateFileSystemEntries($directory)) {
            $attributes = [IO.File]::GetAttributes($entry)
            if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "A reparse point was found; deletion stopped: $entry"
            }
            if (($attributes -band [IO.FileAttributes]::Directory) -ne 0) {
                $stack.Push($entry)
            }
        }
    }

    Remove-Item -LiteralPath $path -Recurse -Force
    Write-Host "Removed: $path" -ForegroundColor Green
}

Write-Host "`nRemaining cache root entries:"
Get-ChildItem -LiteralPath $cacheRoot -Force |
    Select-Object Name, LastWriteTime |
    Format-Table -AutoSize
