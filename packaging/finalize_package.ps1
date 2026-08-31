# SPDX-License-Identifier: MIT
# Copyright (c) 2026 nanomicron

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$DistDirectory,
    [Parameter(Mandatory = $true)][string]$PackageDirectory,
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [Parameter(Mandatory = $true)][string]$Version
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$distRoot = (Resolve-Path -LiteralPath $DistDirectory).Path
$sourceRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$packageRoot = [IO.Path]::GetFullPath($PackageDirectory)
$packageLeaf = Split-Path -Leaf $packageRoot
$driveRoot = [IO.Path]::GetPathRoot($packageRoot)

if ($packageRoot -eq $driveRoot -or !$packageLeaf.StartsWith("TubePort-$Version", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing unsafe package directory: $packageRoot"
}
if (!(Test-Path -LiteralPath (Join-Path $distRoot 'TubePort.exe'))) {
    throw "TubePort.exe was not found under $distRoot"
}
if (Test-Path -LiteralPath $packageRoot) {
    if (@(Get-ChildItem -LiteralPath $packageRoot -Force).Count -ne 0) {
        throw "Package directory must be empty: $packageRoot"
    }
} else {
    New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
}

Copy-Item -LiteralPath (Join-Path $distRoot 'TubePort.exe') -Destination $packageRoot
Copy-Item -LiteralPath (Join-Path $distRoot '_internal') -Destination $packageRoot -Recurse

$licenseTarget = Join-Path $packageRoot 'licenses'
New-Item -ItemType Directory -Path $licenseTarget -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $sourceRoot 'LICENSE') -Destination (Join-Path $licenseTarget 'LICENSE-TubePort-MIT.txt')
Get-ChildItem -LiteralPath (Join-Path $sourceRoot 'third_party\licenses') -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $licenseTarget
}

Copy-Item -LiteralPath @(
    (Join-Path $sourceRoot 'Setup-Tools.cmd'),
    (Join-Path $sourceRoot 'Setup-Tools.ps1'),
    (Join-Path $sourceRoot 'packaging\README.html'),
    (Join-Path $sourceRoot 'packaging\QUICK_START.txt')
) -Destination $packageRoot
Copy-Item -LiteralPath (Join-Path $sourceRoot 'third_party\TOOLS.lock.json') -Destination (Join-Path $packageRoot 'TOOLS.lock.json')
Copy-Item -LiteralPath (Join-Path $sourceRoot 'third_party\COMPONENTS.json') -Destination (Join-Path $packageRoot 'VERSIONS.json')
Copy-Item -LiteralPath (Join-Path $sourceRoot 'third_party\THIRD_PARTY_NOTICES.txt') -Destination $packageRoot

$buildInfo = @(
    "TubePort $Version"
    'Public bootstrap distribution for Windows 10/11 x64'
    "Built: $((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))"
    'Packaging: PyInstaller one-directory mode'
    'License: MIT; see licenses/LICENSE-TubePort-MIT.txt'
    'External tools: not redistributed in this archive'
    'Setup-Tools downloads pinned upstream artifacts and verifies SHA-256 before installation'
    'Authentication: user-selected Netscape cookies.txt; a detected Mozilla Firefox installation may also be offered; TubePort does not collect passwords'
) -join "`r`n"
[IO.File]::WriteAllText(
    (Join-Path $packageRoot 'BUILD_INFO.txt'),
    $buildInfo + "`r`n",
    [Text.UTF8Encoding]::new($false)
)

[pscustomobject]@{
    package_directory = $packageRoot
    file_count = @(Get-ChildItem -LiteralPath $packageRoot -File -Recurse).Count
    bytes = (Get-ChildItem -LiteralPath $packageRoot -File -Recurse | Measure-Object Length -Sum).Sum
    distribution = 'bootstrap'
} | ConvertTo-Json
