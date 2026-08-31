# SPDX-License-Identifier: MIT
# Copyright (c) 2026 nanomicron

[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $PSScriptRoot 'tools'),
    [string]$CacheDirectory = (Join-Path ([IO.Path]::GetTempPath()) 'TubePort-tool-cache'),
    [switch]$Force,
    [switch]$KeepCache
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-FullPath([string]$Path) {
    return [IO.Path]::GetFullPath($Path)
}

function Assert-SafeDirectory([string]$Path, [string]$Label) {
    $full = Get-FullPath $Path
    $root = [IO.Path]::GetPathRoot($full)
    if ([string]::IsNullOrWhiteSpace($full) -or $full -eq $root) {
        throw "$Label cannot be a drive root: $full"
    }
    return $full
}

function Reset-ChildDirectory([string]$Parent, [string]$ChildName) {
    $parentFull = Assert-SafeDirectory $Parent 'CacheDirectory'
    $child = Get-FullPath (Join-Path $parentFull $ChildName)
    $prefix = $parentFull.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (!$child.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to reset a path outside the cache: $child"
    }
    if (Test-Path -LiteralPath $child) {
        Remove-Item -LiteralPath $child -Recurse -Force
    }
    New-Item -ItemType Directory -Path $child -Force | Out-Null
    return $child
}

function Get-VerifiedFile([string]$Url, [string]$ExpectedSha256, [string]$Target) {
    if ((Test-Path -LiteralPath $Target) -and !$Force) {
        $existing = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash
        if ($existing -eq $ExpectedSha256) {
            Write-Host "Using verified cache: $([IO.Path]::GetFileName($Target))"
            return
        }
    }

    $partial = "$Target.partial"
    if (Test-Path -LiteralPath $partial) {
        Remove-Item -LiteralPath $partial -Force
    }
    Write-Host "Downloading $Url"
    Invoke-WebRequest -Uri $Url -OutFile $partial
    $actual = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash
    if ($actual -ne $ExpectedSha256) {
        Remove-Item -LiteralPath $partial -Force
        throw "SHA-256 mismatch for $Url. Expected $ExpectedSha256, received $actual."
    }
    Move-Item -LiteralPath $partial -Destination $Target -Force
}

$projectRoot = Get-FullPath $PSScriptRoot
$lockCandidates = @(
    (Join-Path $projectRoot 'TOOLS.lock.json'),
    (Join-Path $projectRoot 'third_party\TOOLS.lock.json')
)
$lockPath = $lockCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (!$lockPath) {
    throw 'TOOLS.lock.json was not found. Keep Setup-Tools.ps1 with the complete TubePort package.'
}

$destinationRoot = Assert-SafeDirectory $Destination 'Destination'
$cacheRoot = Assert-SafeDirectory $CacheDirectory 'CacheDirectory'
New-Item -ItemType Directory -Path $destinationRoot, $cacheRoot -Force | Out-Null
$lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json

foreach ($component in $lock.components) {
    $downloadName = [IO.Path]::GetFileName(([Uri]$component.url).AbsolutePath)
    $downloadPath = Join-Path $cacheRoot $downloadName
    Get-VerifiedFile $component.url $component.sha256 $downloadPath

    if ($component.format -eq 'file') {
        $sourceRoot = Split-Path -Parent $downloadPath
    } elseif ($component.format -eq 'zip') {
        $sourceRoot = Reset-ChildDirectory $cacheRoot ("extract-" + ($component.name -replace '[^A-Za-z0-9_.-]', '-'))
        Expand-Archive -LiteralPath $downloadPath -DestinationPath $sourceRoot -Force
    } else {
        throw "Unsupported archive format: $($component.format)"
    }

    foreach ($executable in $component.executables) {
        if ($component.format -eq 'file') {
            $source = $downloadPath
        } else {
            $matches = @(Get-ChildItem -LiteralPath $sourceRoot -File -Recurse -Filter $executable.name)
            if ($matches.Count -ne 1) {
                throw "Expected one $($executable.name) in $downloadName; found $($matches.Count)."
            }
            $source = $matches[0].FullName
        }
        $actual = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
        if ($actual -ne $executable.sha256) {
            throw "SHA-256 mismatch for $($executable.name). Expected $($executable.sha256), received $actual."
        }
        Copy-Item -LiteralPath $source -Destination (Join-Path $destinationRoot $executable.name) -Force
        Write-Host "Installed $($executable.name) ($($component.version))"
    }

    if (!$KeepCache) {
        if ($component.format -eq 'zip' -and (Test-Path -LiteralPath $sourceRoot)) {
            Remove-Item -LiteralPath $sourceRoot -Recurse -Force
        }
        if (Test-Path -LiteralPath $downloadPath) {
            Remove-Item -LiteralPath $downloadPath -Force
        }
    }
}

$installed = [ordered]@{
    schema = 1
    installed_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    lock_sha256 = (Get-FileHash -LiteralPath $lockPath -Algorithm SHA256).Hash
    files = @()
}
foreach ($file in Get-ChildItem -LiteralPath $destinationRoot -File -Filter '*.exe' | Sort-Object Name) {
    $installed.files += [ordered]@{
        name = $file.Name
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    }
}
[IO.File]::WriteAllText(
    (Join-Path $destinationRoot 'TOOLS_INSTALLED.json'),
    ($installed | ConvertTo-Json -Depth 5) + "`r`n",
    [Text.UTF8Encoding]::new($false)
)

Write-Host ''
Write-Host 'TubePort tools are installed and verified.' -ForegroundColor Green
Write-Host "Destination: $destinationRoot"
Write-Host 'You can now start TubePort.exe.'
