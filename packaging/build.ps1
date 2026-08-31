# SPDX-License-Identifier: MIT
# Copyright (c) 2026 nanomicron

[CmdletBinding()]
param(
    [string]$WorkDirectory = (Join-Path ([IO.Path]::GetTempPath()) 'TubePort-build'),
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\dist')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-SafeDirectory([string]$Path, [string]$Label) {
    $full = [IO.Path]::GetFullPath($Path)
    if ($full -eq [IO.Path]::GetPathRoot($full)) {
        throw "$Label cannot be a drive root: $full"
    }
    return $full
}

function Reset-ChildDirectory([string]$Parent, [string]$ChildName) {
    $parentFull = Assert-SafeDirectory $Parent 'WorkDirectory'
    New-Item -ItemType Directory -Path $parentFull -Force | Out-Null
    $target = [IO.Path]::GetFullPath((Join-Path $parentFull $ChildName))
    $prefix = $parentFull.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (!$target.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to reset a path outside WorkDirectory: $target"
    }
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    return $target
}

function Assert-LastExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

function Invoke-GuiExecutableAndWait(
    [string]$FilePath,
    [string[]]$Arguments,
    [string]$Step
) {
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.UseShellExecute = $false
    foreach ($argument in $Arguments) {
        [void]$startInfo.ArgumentList.Add($argument)
    }

    $process = [Diagnostics.Process]::Start($startInfo)
    if ($null -eq $process) {
        throw "$Step failed to start."
    }
    try {
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            throw "$Step failed with exit code $($process.ExitCode)"
        }
    }
    finally {
        $process.Dispose()
    }
}

if ($env:OS -ne 'Windows_NT') {
    throw 'TubePort Windows packages must be built on Windows.'
}

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$version = (Get-Content -LiteralPath (Join-Path $projectRoot 'VERSION') -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Invalid VERSION value: $version"
}

$workRoot = Assert-SafeDirectory $WorkDirectory 'WorkDirectory'
$outputRoot = Assert-SafeDirectory $OutputDirectory 'OutputDirectory'
$runRoot = Reset-ChildDirectory $workRoot "TubePort-$version-build"
$venvRoot = Join-Path $runRoot 'venv'
$pyInstallerDist = Join-Path $runRoot 'pyinstaller-dist'
$pyInstallerWork = Join-Path $runRoot 'pyinstaller-work'
$reportsRoot = Join-Path $runRoot 'reports'
$packageParent = Join-Path $runRoot 'package'
$packageRoot = Join-Path $packageParent "TubePort-$version-win64"
New-Item -ItemType Directory -Path $outputRoot, $reportsRoot, $packageRoot -Force | Out-Null

$pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
$launcherArguments = @('-3.12')
if (!$pythonLauncher) {
    $pythonLauncher = Get-Command python.exe -ErrorAction SilentlyContinue
    $launcherArguments = @()
}
if (!$pythonLauncher) {
    throw 'Python 3.12.10 was not found.'
}
$launcherVersion = & $pythonLauncher.Source @launcherArguments -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")'
Assert-LastExitCode 'Checking the Python version'
if ($launcherVersion.Trim() -ne '3.12.10') {
    throw "Python 3.12.10 is required for the reproducible release recipe; selected interpreter reports $launcherVersion."
}
$launcherBits = & $pythonLauncher.Source @launcherArguments -c 'import struct; print(struct.calcsize("P") * 8)'
Assert-LastExitCode 'Checking the Python architecture'
if ($launcherBits.Trim() -ne '64') {
    throw "64-bit Python is required for the win64 package; selected interpreter reports $launcherBits-bit."
}

& $pythonLauncher.Source @launcherArguments -m venv $venvRoot
Assert-LastExitCode 'Creating the Python virtual environment'
$python = Join-Path $venvRoot 'Scripts\python.exe'
$env:PIP_CACHE_DIR = Join-Path $workRoot 'pip-cache'
$env:PYTHONPYCACHEPREFIX = Join-Path $runRoot 'pycache'

& $python -m pip install --disable-pip-version-check --requirement (Join-Path $projectRoot 'requirements-build.txt')
Assert-LastExitCode 'Installing build dependencies'
& $python -m py_compile (Join-Path $projectRoot 'src\TubePort.pyw')
Assert-LastExitCode 'Compiling the source'
& $python (Join-Path $projectRoot 'src\TubePort.pyw') --url-input-self-test --report-file (Join-Path $reportsRoot 'source-url-input.json')
Assert-LastExitCode 'Running the source URL-input self-test'

& $python -m PyInstaller --noconfirm --clean --distpath $pyInstallerDist --workpath $pyInstallerWork (Join-Path $projectRoot 'packaging\TubePort.spec')
Assert-LastExitCode 'Building TubePort with PyInstaller'

& (Join-Path $projectRoot 'packaging\finalize_package.ps1') `
    -DistDirectory (Join-Path $pyInstallerDist 'TubePort') `
    -PackageDirectory $packageRoot `
    -ProjectRoot $projectRoot `
    -Version $version
Assert-LastExitCode 'Assembling the bootstrap package'

$packageExe = Join-Path $packageRoot 'TubePort.exe'
$packageInputReport = Join-Path $reportsRoot 'package-url-input.json'
$packageUiReport = Join-Path $reportsRoot 'package-ui-contract.json'
Invoke-GuiExecutableAndWait `
    -FilePath $packageExe `
    -Arguments @('--url-input-self-test', '--report-file', $packageInputReport) `
    -Step 'Running the packaged URL-input self-test'
Invoke-GuiExecutableAndWait `
    -FilePath $packageExe `
    -Arguments @('--ui-contract', '--report-file', $packageUiReport) `
    -Step 'Running the packaged UI contract'

$sourceInput = Get-Content -LiteralPath (Join-Path $reportsRoot 'source-url-input.json') -Raw | ConvertFrom-Json
$packageInput = Get-Content -LiteralPath $packageInputReport -Raw | ConvertFrom-Json
$packageUi = Get-Content -LiteralPath $packageUiReport -Raw | ConvertFrom-Json
if (!$sourceInput.ok -or !$packageInput.ok -or !$packageUi.ok) {
    throw 'One or more verification reports returned ok=false.'
}

$verification = [ordered]@{
    schema = 1
    application = 'TubePort'
    version = $version
    verified_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    platform = 'Windows x64'
    distribution = 'bootstrap; external media tools are not included'
    checks = [ordered]@{
        python_compile = $true
        source_url_input_self_test = $true
        packaged_url_input_self_test = $true
        packaged_ui_contract = $true
        english_interface_contract = [bool]$packageUi.english_interface.no_cyrillic
        browser_and_profile_selection = [bool]$packageUi.english_interface.cookie_sources
    }
}
[IO.File]::WriteAllText(
    (Join-Path $packageRoot 'VERIFICATION.json'),
    ($verification | ConvertTo-Json -Depth 8) + "`r`n",
    [Text.UTF8Encoding]::new($false)
)

$manifestPath = Join-Path $packageRoot 'SHA256SUMS.txt'
$manifestLines = Get-ChildItem -LiteralPath $packageRoot -File -Recurse |
    Where-Object { $_.FullName -ne $manifestPath } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = [IO.Path]::GetRelativePath($packageRoot, $_.FullName).Replace('\', '/')
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        "$hash *$relative"
    }
[IO.File]::WriteAllLines($manifestPath, $manifestLines, [Text.UTF8Encoding]::new($false))

$zipPath = Join-Path $outputRoot "TubePort-$version-win64-bootstrap.zip"
$checksumPath = "$zipPath.sha256"
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
if (Test-Path -LiteralPath $checksumPath) {
    Remove-Item -LiteralPath $checksumPath -Force
}
Compress-Archive -LiteralPath $packageRoot -DestinationPath $zipPath -CompressionLevel Optimal
$zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
[IO.File]::WriteAllText(
    $checksumPath,
    "$zipHash *$([IO.Path]::GetFileName($zipPath))`r`n",
    [Text.UTF8Encoding]::new($false)
)

[pscustomobject]@{
    version = $version
    package = $packageRoot
    archive = $zipPath
    archive_bytes = (Get-Item -LiteralPath $zipPath).Length
    archive_sha256 = $zipHash
    checksum = $checksumPath
} | ConvertTo-Json
