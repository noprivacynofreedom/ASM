# -FastNsis: installer without compression. Default is ON (Fast NSIS). Pass -Compress for compressed distribution.
# -Compress: enable NSIS compression for smaller release distribution size (slower build).
# -HotSync: sync Python backend + chat UI directly into the live install in seconds (skip Nuitka and NSIS).
# -BuildExe: with -HotSync, also rebuild atlas-desktop.exe incrementally (Vite + Cargo) and copy it over.
# -Launch: with -HotSync, launch Atlas Chat after syncing.
# -NoCoreCache: force Nuitka to recompile every core module instead of reusing build-tools/nuitka-cache.
# -Update <branch>: first take that GitHub branch with get_update.py (its checks, never a branch switch), then build.
# CmdletBinding: a wrong option name (for example -FastNsi) stops the build instead of being ignored.
[CmdletBinding()]
param([string]$TargetRoot, [switch]$CloseApp, [switch]$SkipAppCheck, [switch]$FastNsis, [switch]$Compress, [string]$Update, [switch]$HotSync, [switch]$BuildExe, [switch]$Launch, [switch]$NoCoreCache)
$ErrorActionPreference = "Stop"

if (-not $PSBoundParameters.ContainsKey('FastNsis')) {
    $FastNsis = -not $Compress
}
if ($Compress) {
    $FastNsis = $false
}
if ($Update) {
    & python (Join-Path $PSScriptRoot "get_update.py") $Update
    if ($LASTEXITCODE -ne 0) { throw "get_update.py stopped (see above). Nothing was built." }
}
if ($HotSync) {
    $syncScript = Join-Path $PSScriptRoot "sync-live.ps1"
    & $syncScript -CloseApp:$CloseApp -SkipAppCheck:$SkipAppCheck -BuildExe:$BuildExe -Launch:$Launch
    if ($LASTEXITCODE -ne 0) { throw "sync-live.ps1 failed with exit code $LASTEXITCODE." }
    return
}
$BuildTimer = [System.Diagnostics.Stopwatch]::StartNew()
$BuildStarted = Get-Date
Write-Host ("Build started:  {0:yyyy-MM-dd HH:mm:ss}" -f $BuildStarted) -ForegroundColor Cyan

# Live step board and window-title timer (display only; see build-progress.ps1).
try {
    $ProgressHelper = Join-Path $PSScriptRoot "build-progress.ps1"
    if (Test-Path -LiteralPath $ProgressHelper) { . $ProgressHelper }
}
catch { }
if (!(Get-Command Set-AtlasStep -ErrorAction SilentlyContinue)) {
    function Start-AtlasProgress { }
    function Set-AtlasStep { param([int]$Number) }
    function Complete-AtlasProgress { }
    function Stop-AtlasProgress { }
}
Start-AtlasProgress

# Building while Atlas runs can slow or stall the build (CPU, RAM, VRAM, antivirus scans) and a running
# target\release exe cannot be replaced. Installing over a running app can leave a half-replaced install.
# This check ends Atlas (politely first) and any llama-swap / llama-server it left behind.
# Use -CloseApp to skip the question, or -SkipAppCheck to bypass the check.
function Assert-AtlasClosed {
    if ($SkipAppCheck) {
        Write-Host "`n===== CHECK RUNNING ATLAS (skipped by -SkipAppCheck) =====" -ForegroundColor Yellow
        return
    }
    Write-Host "`n===== CHECK RUNNING ATLAS =====" -ForegroundColor Cyan
    $appNames = @("atlas-desktop")
    $modelNames = @("llama-swap", "llama-server")
    $apps = @(Get-Process -Name $appNames -ErrorAction SilentlyContinue)
    $models = @(Get-Process -Name $modelNames -ErrorAction SilentlyContinue)
    if (($apps.Count -eq 0) -and ($models.Count -eq 0)) {
        Write-Host "Atlas is not running. Safe to build." -ForegroundColor Green
        return
    }
    foreach ($proc in @($apps + $models)) {
        Write-Host ("  running: {0} (PID {1})" -f $proc.ProcessName, $proc.Id) -ForegroundColor Yellow
    }
    if (-not $CloseApp) {
        $answer = Read-Host "Close these now so the build runs safely? [Y/n]"
        if ($answer -match '^(n|no)$') {
            throw "Build cancelled. Close Atlas Chat first, or run .\build-release.ps1 -CloseApp."
        }
    }
    foreach ($proc in $apps) {
        try { [void]$proc.CloseMainWindow() } catch { }
    }
    $deadline = (Get-Date).AddSeconds(25)
    while (((Get-Date) -lt $deadline) -and (@(Get-Process -Name $appNames -ErrorAction SilentlyContinue).Count -gt 0)) {
        Start-Sleep -Milliseconds 500
    }
    $still = @(Get-Process -Name $appNames -ErrorAction SilentlyContinue)
    if ($still.Count -gt 0) {
        Write-Host "Atlas did not close by itself. Ending it." -ForegroundColor Yellow
        $still | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
    Start-Sleep -Seconds 2
    $left = @(Get-Process -Name $modelNames -ErrorAction SilentlyContinue)
    if ($left.Count -gt 0) {
        Write-Host "Stopping leftover llama-swap / llama-server processes." -ForegroundColor Yellow
        $left | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
    if (@(Get-Process -Name $appNames -ErrorAction SilentlyContinue).Count -gt 0) {
        throw "Atlas is still running and could not be closed. Close it manually, then run the build again."
    }
    Write-Host "Atlas is closed. Continuing." -ForegroundColor Green
}


$Root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$Desktop = Join-Path $Root "atlas-rust-desktop"
$Tauri = Join-Path $Desktop "src-tauri"
$Target = if ([string]::IsNullOrWhiteSpace($TargetRoot)) {
    Join-Path $Tauri "target"
} else {
    [System.IO.Path]::GetFullPath($TargetRoot)
}
if (!$Target.StartsWith($Tauri + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "TargetRoot must remain inside the Tauri source folder: $Target"
}
$Release = Join-Path $Target "release"
$Exe = Join-Path $Release "atlas-desktop.exe"
$Bundle = Join-Path $Release "bundle"
$Nsis = Join-Path $Bundle "nsis"
$Audit = Join-Path $Root ".atlas-patch-audit"

function Get-TreeManifest {
    param([string]$Path)

    if (!(Test-Path -LiteralPath $Path -PathType Container)) {
        throw "Directory missing for manifest: $Path"
    }

    $Base = (Get-Item -LiteralPath $Path).FullName.TrimEnd('\')
    $Files = @(Get-ChildItem -LiteralPath $Base -File -Recurse)

    $Entries = @(
        foreach ($File in $Files) {
            $Relative = $File.FullName.Substring($Base.Length).TrimStart('\')
            $Hash = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash
            "$Relative|$Hash"
        }
    )

    return ,@($Entries | Sort-Object)
}

function Assert-TreeManifest {
    param(
        [string[]]$Expected,
        [string[]]$Actual,
        [string]$Description
    )

    $Differences = @(Compare-Object $Expected $Actual)
    if ($Differences.Count -gt 0) {
        throw "$Description manifest mismatch."
    }
}

$RolledBack = $false
function Invoke-Rollback {
    $script:RolledBack = $true
    if (!$BackupComplete) {
        Write-Host "Backup phase did not complete. No release outputs were isolated; original outputs were left in place." -ForegroundColor Yellow
        return
    }
    try {
        if ($ExeIsolated) {
            if (Test-Path -LiteralPath $Exe -PathType Leaf) {
                Move-Item -LiteralPath $Exe -Destination (Join-Path $BackupRoot "failed-executable")
            }

            $ExeRestore = "$Exe.restore-$RunStamp"
            Copy-Item -LiteralPath $ExeBackup -Destination $ExeRestore

            if ((Get-FileHash $ExeRestore -Algorithm SHA256).Hash -ne $ExeManifest[0]) {
                throw "Restored executable staging hash mismatch."
            }

            Move-Item -LiteralPath $ExeRestore -Destination $Exe
        }
        elseif (!$HadExe -and $BuildStarted -and (Test-Path -LiteralPath $Exe -PathType Leaf)) {
            Move-Item -LiteralPath $Exe -Destination (Join-Path $BackupRoot "failed-executable")
        }

        if ($BundleIsolated) {
            if (Test-Path -LiteralPath $Bundle -PathType Container) {
                Move-Item -LiteralPath $Bundle -Destination (Join-Path $BackupRoot "failed-bundle")
            }

            $BundleRestore = Join-Path $Release "bundle.restore-$RunStamp"
            Copy-Item -LiteralPath $BundleBackup -Destination $BundleRestore -Recurse

            $RestoreManifest = Get-TreeManifest $BundleRestore
            Assert-TreeManifest $BundleManifest $RestoreManifest "Restored bundle"

            Move-Item -LiteralPath $BundleRestore -Destination $Bundle
        }
        elseif (!$HadBundle -and $BuildStarted -and (Test-Path -LiteralPath $Bundle -PathType Container)) {
            Move-Item -LiteralPath $Bundle -Destination (Join-Path $BackupRoot "failed-bundle")
        }

        Write-Host "Previous release outputs restored and verified." -ForegroundColor Green
    }
    catch {
        Write-Host "ROLLBACK NEEDS MANUAL ATTENTION. Backups and failed outputs have been preserved." -ForegroundColor Red
        Write-Host $_
    }
}

$PreviousLocation = Get-Location
$HadTargetVariable = Test-Path Env:CARGO_TARGET_DIR
$PreviousTarget = $env:CARGO_TARGET_DIR

$HadExe = Test-Path -LiteralPath $Exe -PathType Leaf
$HadBundle = Test-Path -LiteralPath $Bundle -PathType Container

$BackupComplete = $false
$ExeIsolated = $false
$BundleIsolated = $false
$BuildStarted = $false
$BuildVerified = $false

$BackupRoot = $null
$ExeBackup = $null
$BundleBackup = $null
$ExeManifest = @()
$BundleManifest = @()

try {
    if (!(Test-Path -LiteralPath (Join-Path $Desktop "package.json") -PathType Leaf)) {
        throw "Desktop package.json missing."
    }
    if (!(Test-Path -LiteralPath (Join-Path $Tauri "Cargo.toml") -PathType Leaf)) {
        throw "Cargo.toml missing."
    }
    # A fresh clone has no node_modules, so "tauri" is missing at step 4 (laptop, 2026-11-18). Install it first.
    if (!(Test-Path -LiteralPath (Join-Path $Desktop "node_modules\.bin\tauri.cmd") -PathType Leaf)) {
        Write-Host "node_modules missing: running npm ci in $Desktop"
        Push-Location $Desktop
        try { & npm.cmd ci; if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE." } }
        finally { Pop-Location }
    }
    if (!(Test-Path -LiteralPath (Join-Path $Tauri "tauri.conf.json") -PathType Leaf)) {
        throw "Tauri configuration missing."
    }

    Assert-AtlasClosed
    Set-AtlasStep 1
    Write-Host "`n===== CHECK BUNDLED BACKEND =====" -ForegroundColor Cyan
    $BundledPython = Join-Path $Tauri "resources\atlas\runtime\python\python.exe"
    if (!(Test-Path -LiteralPath $BundledPython -PathType Leaf)) {
        throw "Bundled Python missing: $BundledPython. It is not stored in git; copy the runtime\python folder into resources\atlas before building."
    }
    $StrayPythonZip = Join-Path $Tauri "resources\atlas\runtime\python.zip"
    if (Test-Path -LiteralPath $StrayPythonZip -PathType Leaf) {
        $zipMb = [math]::Round((Get-Item -LiteralPath $StrayPythonZip).Length / 1MB)
        Write-Host "WARNING: $StrayPythonZip ($zipMb MB) is inside resources\atlas\runtime and will be packed into the installer." -ForegroundColor Yellow
    }
    & $BundledPython (Join-Path $Root "check-bundle.py")
    if ($LASTEXITCODE -ne 0) {
        throw "Bundled backend check failed. Nothing was built or changed."
    }
    # The private core ships compiled (Nuitka .pyd), not as readable .py. compile_core.py makes
    # src-tauri\core-staging\atlas and tauri.core.conf.json, which points Tauri at that copy.
    Write-Host "`n===== COMPILE PRIVATE CORE (Nuitka) =====" -ForegroundColor Cyan
    $coreArgs = @((Join-Path $Root "compile_core.py"))
    if ($NoCoreCache) {
        $coreArgs += "--no-cache"
    }
    if ($FastNsis) {
        Write-Host "FAST NSIS: installer compression is OFF (fast build default). Pass -Compress for smaller release installer." -ForegroundColor Cyan
        $coreArgs += "--fast-nsis"
    } else {
        Write-Host "COMPRESSED NSIS: installer compression is ON." -ForegroundColor Yellow
    }
    & $BundledPython @coreArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Core compile failed. Nothing was built or changed."
    }
    $CoreConfig = Join-Path $Tauri "core-staging\tauri.core.conf.json"
    if (!(Test-Path -LiteralPath $CoreConfig -PathType Leaf)) {
        throw "Core compile did not write $CoreConfig. Nothing was built or changed."
    }

    New-Item -ItemType Directory -Path $Audit -Force | Out-Null

    $RunStamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $BackupRoot = Join-Path $Audit "release-output-$RunStamp"
    New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

    Set-AtlasStep 2
    Write-Host "`n===== BACKUP EXISTING OUTPUTS =====" -ForegroundColor Cyan

    if ($HadExe) {
        $ExeBackup = Join-Path $BackupRoot "atlas-desktop.exe.before"
        Copy-Item -LiteralPath $Exe -Destination $ExeBackup

        $ExeManifest = @((Get-FileHash $Exe -Algorithm SHA256).Hash)
        $ExeBackupManifest = @((Get-FileHash $ExeBackup -Algorithm SHA256).Hash)
        Assert-TreeManifest $ExeManifest $ExeBackupManifest "Executable backup"
    }

    if ($HadBundle) {
        $BundleBackup = Join-Path $BackupRoot "bundle.before"
        Copy-Item -LiteralPath $Bundle -Destination $BundleBackup -Recurse

        $BundleManifest = Get-TreeManifest $Bundle
        $BundleBackupManifest = Get-TreeManifest $BundleBackup
        Assert-TreeManifest $BundleManifest $BundleBackupManifest "Bundle backup"
    }

    $BackupComplete = $true
    Write-Host "All existing release backups verified." -ForegroundColor Green

    Set-AtlasStep 3
    Write-Host "`n===== ISOLATE PREVIOUS OUTPUTS =====" -ForegroundColor Cyan

    if ($HadExe) {
        $ExeOriginal = Join-Path $BackupRoot "atlas-desktop.exe.original"
        Move-Item -LiteralPath $Exe -Destination $ExeOriginal

        if ((Get-FileHash $ExeOriginal -Algorithm SHA256).Hash -ne $ExeManifest[0]) {
            throw "Isolated executable does not match its verified backup."
        }

        $ExeIsolated = $true
    }

    if ($HadBundle) {
        $BundleOriginal = Join-Path $BackupRoot "bundle.original"
        Move-Item -LiteralPath $Bundle -Destination $BundleOriginal

        $MovedManifest = Get-TreeManifest $BundleOriginal
        Assert-TreeManifest $BundleManifest $MovedManifest "Isolated bundle"

        $BundleIsolated = $true
    }

    Set-Location $Desktop
    $env:CARGO_TARGET_DIR = $Target

    Set-AtlasStep 4
    Write-Host "`n===== RELEASE BUILD =====" -ForegroundColor Cyan
    Write-Host "Cargo target: $env:CARGO_TARGET_DIR"

    # Tauri copies resources into release\atlas but never deletes old files there. Clear everything
    # except runtime\ so the readable-core check sees only this build's files without re-deleting
    # thousands of Python stdlib files every build.
    $ReleaseResources = Join-Path $Release "atlas"
    if (Test-Path -LiteralPath $ReleaseResources) {
        Get-ChildItem -LiteralPath $ReleaseResources -Force | Where-Object { $_.Name -ne "runtime" } | Remove-Item -Recurse -Force
    }
    $BuildStarted = $true
    # cargo prints progress on stderr. With "Stop", PowerShell 5.1 turns each stderr line into a
    # terminating error when output is redirected (*>). The exit code below is the real check.
    # Data folder baked into this build. local-build.json is private (never exported):
    # {"data_root": "D:\\some\\folder"}. Without it the app uses %LOCALAPPDATA%\atlas-chat\data.
    # The app uses data_root only when that folder exists on the PC that runs it.
    $LocalBuild = Join-Path $Root "local-build.json"
    $env:ATLAS_BUILD_DATA_ROOT = ""
    if (Test-Path -LiteralPath $LocalBuild) {
        $DataRoot = [string]((Get-Content -LiteralPath $LocalBuild -Raw | ConvertFrom-Json).data_root)
        if (-not [string]::IsNullOrWhiteSpace($DataRoot)) {
            $env:ATLAS_BUILD_DATA_ROOT = $DataRoot.Trim()
        }
    }
    if ($env:ATLAS_BUILD_DATA_ROOT) {
        Write-Host "Data folder for this build: $env:ATLAS_BUILD_DATA_ROOT (from local-build.json)"
        if (-not (Test-Path -LiteralPath $env:ATLAS_BUILD_DATA_ROOT)) {
            Write-Host "WARNING: that folder does not exist on this PC, so the app here uses %LOCALAPPDATA%\atlas-chat\data." -ForegroundColor Yellow
        }
    } else {
        Write-Host "Data folder for this build: %LOCALAPPDATA%\atlas-chat\data (no local-build.json)"
    }

    $ErrorActionPreference = "Continue"
    & npm run tauri -- build --bundles nsis --config $CoreConfig
    $BuildExit = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    Remove-Item Env:ATLAS_BUILD_DATA_ROOT -ErrorAction SilentlyContinue

    if ($BuildExit -ne 0) {
        throw "Tauri build failed with exit code $BuildExit."
    }

    Set-AtlasStep 5
    if (!(Test-Path -LiteralPath $Exe -PathType Leaf)) {
        throw "New release executable missing: $Exe"
    }

    if (!(Test-Path -LiteralPath $Nsis -PathType Container)) {
        throw "New NSIS output directory missing: $Nsis"
    }

    $Installers = @(Get-ChildItem -LiteralPath $Nsis -Filter "*.exe" -File)

    if ($Installers.Count -eq 0) {
        throw "No NSIS installer was generated."
    }

    & $BundledPython (Join-Path $Root "compile_core.py") --check $ReleaseResources
    if ($LASTEXITCODE -ne 0) {
        throw "The build output holds readable core .py files (listed above). Do not ship this installer."
    }

    $ExeHash = (Get-FileHash $Exe -Algorithm SHA256).Hash
    if ([string]::IsNullOrWhiteSpace($ExeHash)) {
        throw "Executable hash verification failed."
    }

    foreach ($Installer in $Installers) {
        $InstallerHash = (Get-FileHash $Installer.FullName -Algorithm SHA256).Hash
        if ([string]::IsNullOrWhiteSpace($InstallerHash)) {
            throw "Installer hash verification failed: $($Installer.FullName)"
        }
    }

    $BuildVerified = $true
    Complete-AtlasProgress

    Write-Host "`n===== RELEASE BUILD VERIFIED =====" -ForegroundColor Green
    Write-Host "Executable: $Exe"
    Write-Host "Executable SHA256: $ExeHash"

    foreach ($Installer in $Installers) {
        Write-Host "`nInstaller: $($Installer.FullName)"
        Write-Host "Size: $($Installer.Length) bytes"
        Write-Host "SHA256: $((Get-FileHash $Installer.FullName -Algorithm SHA256).Hash)"
    }

    Write-Host "`nPrevious outputs preserved at: $BackupRoot"
}
catch {
    $BuildError = $_
    Write-Host "`nBUILD FAILED. CHECKING SAFE RESTORATION." -ForegroundColor Red
    Invoke-Rollback

    throw $BuildError
}
finally {
    Stop-AtlasProgress
    if (!$BuildVerified -and !$RolledBack -and ($BuildStarted -or $ExeIsolated -or $BundleIsolated)) {
        Write-Host "`nBuild interrupted. CHECKING SAFE RESTORATION." -ForegroundColor Yellow
        Invoke-Rollback
    }
    if ($HadTargetVariable) {
        $env:CARGO_TARGET_DIR = $PreviousTarget
    }
    else {
        Remove-Item Env:CARGO_TARGET_DIR -ErrorAction SilentlyContinue
    }

    Set-Location $PreviousLocation
}

if (!$BuildVerified) {
    throw "Release build did not reach verified completion."
}

Write-Host "`nATLAS RELEASE BUILD VERIFIED. NOTHING WAS INSTALLED." -ForegroundColor Green
Write-Host ("Build started:   {0:yyyy-MM-dd HH:mm:ss}" -f $BuildStarted) -ForegroundColor Green
Write-Host ("Build finished:  {0:yyyy-MM-dd HH:mm:ss}" -f (Get-Date)) -ForegroundColor Green
Write-Host ("Total build time: {0:mm\:ss} (minutes:seconds)" -f $BuildTimer.Elapsed) -ForegroundColor Green

# Next steps (printed only; this script never installs or launches anything).
$NewInstaller = @(Get-ChildItem -LiteralPath $Nsis -Filter "*.exe" -File)[0].FullName
$InstalledExe = Join-Path $Root "app\atlas-desktop.exe"
Write-Host "`n===== HOW TO INSTALL AND LAUNCH THE UPDATED APP =====" -ForegroundColor Cyan
Write-Host "1. Close Atlas Chat if it is open (also check the system tray)."
Write-Host "2. Run the installer. New installs go to %LOCALAPPDATA%\atlas-chat\app (updates keep your existing folder) and keep your data:"
Write-Host "   Start-Process `"$NewInstaller`""
Write-Host "3. Launch the updated app after the installer finishes:"
Write-Host "   Start-Process `"$InstalledExe`""
Write-Host "   (or use the Start menu shortcut named Atlas Chat)"
Write-Host "4. If something is wrong, the previous release files are in:"
Write-Host "   $BackupRoot"

