<#
.SYNOPSIS
    Bootstrap a fresh Windows machine for Atlas Chat development and release builds.
.DESCRIPTION
    Checks for git, python, node, rustc/cargo, Visual Studio C++ Build Tools,
    NSIS (makensis), and Playwright (+ Chromium). Skips every tool that is already
    installed and installs missing ones via winget, rustup, or pip.
.PARAMETER CheckOnly
    Report what is installed or missing without installing anything.
#>
[CmdletBinding()]
param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

function Write-Status {
    param(
        [string]$Tool,
        [ValidateSet("Skip", "Install", "Warn", "Fail")]
        [string]$State,
        [string]$Detail
    )
    switch ($State) {
        "Skip"    { Write-Host ("[SKIP]    {0,-24} {1}" -f $Tool, $Detail) -ForegroundColor Green }
        "Install" { Write-Host ("[INSTALL] {0,-24} {1}" -f $Tool, $Detail) -ForegroundColor Cyan }
        "Warn"    { Write-Host ("[WARN]    {0,-24} {1}" -f $Tool, $Detail) -ForegroundColor Yellow }
        "Fail"    { Write-Host ("[MISSING] {0,-24} {1}" -f $Tool, $Detail) -ForegroundColor Red }
    }
}

function Refresh-PathEnvironment {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $combined = @($machinePath, $userPath) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    $env:Path = ($combined -join ";")
}

function Test-WingetAvailable {
    return $null -ne (Get-Command winget -ErrorAction SilentlyContinue)
}

function Install-WithWinget {
    param(
        [string]$PackageId,
        [string]$DisplayName,
        [string]$OverrideArgs
    )
    if ($CheckOnly) {
        Write-Status $DisplayName "Fail" "Not installed (would install via winget: $PackageId)"
        return $false
    }
    if (-not (Test-WingetAvailable)) {
        Write-Status $DisplayName "Warn" "winget not available; install $PackageId manually."
        return $false
    }
    Write-Status $DisplayName "Install" "Installing $PackageId via winget..."
    $args = @(
        "install", "--id", $PackageId, "--exact",
        "--accept-package-agreements", "--accept-source-agreements"
    )
    if (-not [string]::IsNullOrWhiteSpace($OverrideArgs)) {
        $args += @("--override", $OverrideArgs)
    }
    & winget @args
    if ($LASTEXITCODE -ne 0) {
        Write-Status $DisplayName "Warn" "winget exited with code $LASTEXITCODE."
        return $false
    }
    Refresh-PathEnvironment
    return $true
}

function Find-Makensis {
    $cmd = Get-Command makensis -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "NSIS\makensis.exe"),
        (Join-Path $env:ProgramFiles "NSIS\makensis.exe"),
        (Join-Path $env:LOCALAPPDATA "tauri\NSIS\makensis.exe")
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path -LiteralPath $path -PathType Leaf -ErrorAction SilentlyContinue)) {
            return $path
        }
    }
    return $null
}

function Find-VsCppBuildTools {
    if (Get-Command cl.exe -ErrorAction SilentlyContinue) {
        return "cl.exe in PATH"
    }
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path -LiteralPath $vswhere -PathType Leaf) {
        $installPath = & $vswhere -latest -products * `
            -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
            -property installationPath 2>$null
        if (-not [string]::IsNullOrWhiteSpace($installPath)) {
            return $installPath.Trim()
        }
    }
    return $null
}

Write-Host "=== Atlas Chat Windows Dev Environment Setup ===" -ForegroundColor Cyan
if ($CheckOnly) {
    Write-Host "Running in -CheckOnly mode (no packages will be installed).`n" -ForegroundColor Yellow
}

# 1. Git
$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if ($gitCmd) {
    Write-Status "git" "Skip" $gitCmd.Source
} else {
    [void](Install-WithWinget -PackageId "Git.Git" -DisplayName "git")
}

# 2. Python
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCmd) {
    Write-Status "python" "Skip" $pythonCmd.Source
} else {
    if (Install-WithWinget -PackageId "Python.Python.3.12" -DisplayName "python") {
        $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    }
}

# 3. Node.js
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCmd) {
    Write-Status "node" "Skip" $nodeCmd.Source
} else {
    [void](Install-WithWinget -PackageId "OpenJS.NodeJS.LTS" -DisplayName "node")
}

# 4. Rust (rustc / cargo)
$rustcCmd = Get-Command rustc -ErrorAction SilentlyContinue
$cargoCmd = Get-Command cargo -ErrorAction SilentlyContinue
$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if (-not $rustcCmd -and (Test-Path -LiteralPath (Join-Path $cargoBin "rustc.exe"))) {
    $env:Path = "$cargoBin;$env:Path"
    $rustcCmd = Get-Command rustc -ErrorAction SilentlyContinue
    $cargoCmd = Get-Command cargo -ErrorAction SilentlyContinue
}
if ($rustcCmd -and $cargoCmd) {
    Write-Status "rustc / cargo" "Skip" $rustcCmd.Source
} else {
    $rustupCmd = Get-Command rustup -ErrorAction SilentlyContinue
    if (-not $rustupCmd -and (Test-Path -LiteralPath (Join-Path $cargoBin "rustup.exe"))) {
        $env:Path = "$cargoBin;$env:Path"
        $rustupCmd = Get-Command rustup -ErrorAction SilentlyContinue
    }
    if (-not $rustupCmd) {
        [void](Install-WithWinget -PackageId "Rustlang.Rustup" -DisplayName "rustc / cargo")
        if (Test-Path -LiteralPath $cargoBin) {
            $env:Path = "$cargoBin;$env:Path"
        }
        $rustupCmd = Get-Command rustup -ErrorAction SilentlyContinue
    }
    if (-not $CheckOnly -and $rustupCmd) {
        Write-Status "rustc / cargo" "Install" "Ensuring stable toolchain via rustup..."
        & rustup default stable
    }
}

# 5. Visual Studio C++ Build Tools
$vsCpp = Find-VsCppBuildTools
if ($vsCpp) {
    Write-Status "VS C++ Build Tools" "Skip" $vsCpp
} else {
    [void](Install-WithWinget `
        -PackageId "Microsoft.VisualStudio.2022.BuildTools" `
        -DisplayName "VS C++ Build Tools" `
        -OverrideArgs "--wait --quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended")
}

# 6. NSIS (makensis)
$makensis = Find-Makensis
if ($makensis) {
    Write-Status "makensis (NSIS)" "Skip" $makensis
} else {
    [void](Install-WithWinget -PackageId "NSIS.NSIS" -DisplayName "makensis (NSIS)")
}

# 7. Playwright + Chromium
$pythonExe = if ($pythonCmd) { $pythonCmd.Source } else {
    $bundled = Join-Path $PSScriptRoot "atlas-rust-desktop\src-tauri\resources\atlas\runtime\python\python.exe"
    if (Test-Path -LiteralPath $bundled -PathType Leaf) { $bundled } else { $null }
}

if (-not $pythonExe) {
    Write-Status "playwright" "Warn" "Python not found; skipping playwright check."
} else {
    $ErrorActionPreference = "Continue"
    & $pythonExe -c "import playwright" 2>$null
    $pwExit = $LASTEXITCODE
    $ErrorActionPreference = "Stop"

    if ($pwExit -eq 0) {
        Write-Status "playwright (pip)" "Skip" "Already importable via $pythonExe"
    } elseif ($CheckOnly) {
        Write-Status "playwright (pip)" "Fail" "Not installed (would run: $pythonExe -m pip install playwright)"
    } else {
        Write-Status "playwright (pip)" "Install" "Installing playwright via pip..."
        & $pythonExe -m pip install playwright
        $pwExit = $LASTEXITCODE
    }

    $playwrightCache = Join-Path $env:LOCALAPPDATA "ms-playwright"
    $hasChromium = (Test-Path -LiteralPath $playwrightCache -ErrorAction SilentlyContinue) -and
        (@(Get-ChildItem -LiteralPath $playwrightCache -Directory -Filter "chromium*" -ErrorAction SilentlyContinue).Count -gt 0)

    if ($hasChromium) {
        Write-Status "playwright chromium" "Skip" "Found in $playwrightCache"
    } elseif ($CheckOnly) {
        Write-Status "playwright chromium" "Fail" "Not installed in $playwrightCache"
    } elseif ($pwExit -eq 0) {
        Write-Status "playwright chromium" "Install" "Installing Chromium via playwright..."
        & $pythonExe -m playwright install chromium
    } else {
        Write-Status "playwright chromium" "Warn" "Skipping Chromium install because playwright is not installed."
    }
}

Write-Host "`nDone." -ForegroundColor Cyan
