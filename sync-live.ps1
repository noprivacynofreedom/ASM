# sync-live.ps1 - Fast rollout of Python backend + chat UI changes into the live Atlas Chat install.
# Syncs atlas-rust-desktop/src-tauri/resources/atlas into the installed app\atlas folder in seconds,
# skipping Nuitka core compilation and NSIS packaging. Pass -BuildExe to also rebuild atlas-desktop.exe.
# Keep this file ASCII only (Windows PowerShell 5.1 reads BOM-less files as ANSI).
[CmdletBinding()]
param(
    [string]$InstallDir,
    [switch]$CloseApp,
    [switch]$SkipAppCheck,
    [switch]$BuildExe,
    [switch]$Launch,
    [switch]$DryRun,
    [switch]$SkipCheck
)
$ErrorActionPreference = "Stop"
$Timer = [System.Diagnostics.Stopwatch]::StartNew()

$Root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$Desktop = Join-Path $Root "atlas-rust-desktop"
$Tauri = Join-Path $Desktop "src-tauri"
$SourceAtlas = Join-Path $Tauri "resources\atlas"

if (!(Test-Path -LiteralPath $SourceAtlas -PathType Container)) {
    throw "Source resources folder missing: $SourceAtlas"
}

function Resolve-AtlasInstallDir {
    param([string]$Explicit)
    if (-not [string]::IsNullOrWhiteSpace($Explicit)) {
        return [System.IO.Path]::GetFullPath($Explicit)
    }
    $localApp = Join-Path $Root "app"
    if (Test-Path -LiteralPath (Join-Path $localApp "atlas") -PathType Container) {
        return $localApp
    }
    try {
        $regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Atlas Chat"
        if (Test-Path -LiteralPath $regPath) {
            $loc = (Get-ItemProperty -LiteralPath $regPath -Name "InstallLocation" -ErrorAction SilentlyContinue).InstallLocation
            if (-not [string]::IsNullOrWhiteSpace($loc)) {
                $clean = $loc.Trim().Trim('"')
                if (Test-Path -LiteralPath (Join-Path $clean "atlas") -PathType Container) {
                    return $clean
                }
            }
        }
    } catch { }
    if ($env:LOCALAPPDATA) {
        $userApp = Join-Path $env:LOCALAPPDATA "atlas-chat\app"
        if (Test-Path -LiteralPath (Join-Path $userApp "atlas") -PathType Container) {
            return $userApp
        }
    }
    throw "Could not find an existing Atlas Chat install (checked $localApp, registry, and %LOCALAPPDATA%\atlas-chat\app). Run .\build-release.ps1 and the installer once first, or pass -InstallDir."
}

$TargetInstall = Resolve-AtlasInstallDir -Explicit $InstallDir
$DestAtlas = Join-Path $TargetInstall "atlas"
if (!(Test-Path -LiteralPath $DestAtlas -PathType Container)) {
    throw "Installed atlas folder missing: $DestAtlas. Run the installer once first."
}

Write-Host "Source:  $SourceAtlas" -ForegroundColor Cyan
Write-Host "Install: $TargetInstall" -ForegroundColor Cyan
if ($DryRun) {
    Write-Host "MODE: DRY RUN (no files will be changed)" -ForegroundColor Yellow
}

if (-not $SkipCheck) {
    Write-Host "`n===== CHECK BUNDLED BACKEND =====" -ForegroundColor Cyan
    $BundledPython = Join-Path $SourceAtlas "runtime\python\python.exe"
    $PyCmd = if (Test-Path -LiteralPath $BundledPython -PathType Leaf) { $BundledPython } else { "python" }
    & $PyCmd (Join-Path $Root "check-bundle.py")
    if ($LASTEXITCODE -ne 0) {
        throw "Bundle check failed. Live install was not modified."
    }
}

function Assert-AtlasClosedForSync {
    if ($SkipAppCheck -or $DryRun) {
        return
    }
    $appNames = @("atlas-desktop")
    $modelNames = @("llama-swap", "llama-server")
    $apps = @(Get-Process -Name $appNames -ErrorAction SilentlyContinue)
    $models = @(Get-Process -Name $modelNames -ErrorAction SilentlyContinue)
    if (($apps.Count -eq 0) -and ($models.Count -eq 0)) {
        return
    }
    Write-Host "`n===== CHECK RUNNING ATLAS =====" -ForegroundColor Cyan
    foreach ($proc in @($apps + $models)) {
        Write-Host ("  running: {0} (PID {1})" -f $proc.ProcessName, $proc.Id) -ForegroundColor Yellow
    }
    if (-not $CloseApp) {
        $answer = Read-Host "Close Atlas so updated files take effect cleanly? [Y/n]"
        if ($answer -match '^(n|no)$') {
            throw "Sync cancelled. Close Atlas Chat first, or run .\sync-live.ps1 -CloseApp."
        }
    }
    foreach ($proc in $apps) {
        try { [void]$proc.CloseMainWindow() } catch { }
    }
    $deadline = (Get-Date).AddSeconds(20)
    while (((Get-Date) -lt $deadline) -and (@(Get-Process -Name $appNames -ErrorAction SilentlyContinue).Count -gt 0)) {
        Start-Sleep -Milliseconds 400
    }
    $still = @(Get-Process -Name $appNames -ErrorAction SilentlyContinue)
    if ($still.Count -gt 0) {
        $still | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
    $left = @(Get-Process -Name $modelNames -ErrorAction SilentlyContinue)
    if ($left.Count -gt 0) {
        $left | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
    if (@(Get-Process -Name $appNames -ErrorAction SilentlyContinue).Count -gt 0) {
        throw "Atlas is still running and could not be closed."
    }
}

Assert-AtlasClosedForSync

if ($BuildExe) {
    Write-Host "`n===== REBUILD DESKTOP EXE (Vite + Cargo incremental) =====" -ForegroundColor Cyan
    if (!(Test-Path -LiteralPath (Join-Path $Desktop "node_modules\.bin\vite.cmd") -PathType Leaf)) {
        Push-Location $Desktop
        try { & npm.cmd ci; if ($LASTEXITCODE -ne 0) { throw "npm ci failed." } }
        finally { Pop-Location }
    }
    $LocalBuild = Join-Path $Root "local-build.json"
    $env:ATLAS_BUILD_DATA_ROOT = ""
    if (Test-Path -LiteralPath $LocalBuild) {
        $DataRoot = [string]((Get-Content -LiteralPath $LocalBuild -Raw | ConvertFrom-Json).data_root)
        if (-not [string]::IsNullOrWhiteSpace($DataRoot)) {
            $env:ATLAS_BUILD_DATA_ROOT = $DataRoot.Trim()
        }
    }
    try {
        Push-Location $Desktop
        $ErrorActionPreference = "Continue"
        & npm.cmd run build
        $FrontExit = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        if ($FrontExit -ne 0) { throw "Frontend build failed with exit code $FrontExit." }

        Push-Location $Tauri
        $ErrorActionPreference = "Continue"
        & cargo build --release
        $CargoExit = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        if ($CargoExit -ne 0) { throw "Cargo release build failed with exit code $CargoExit." }
    } finally {
        Remove-Item Env:ATLAS_BUILD_DATA_ROOT -ErrorAction SilentlyContinue
        while ((Get-Location).Path -ne $Root -and (Get-Location).Path -match "atlas-rust-desktop") {
            Pop-Location
        }
    }
}

Write-Host "`n===== SYNC RESOURCES TO LIVE INSTALL =====" -ForegroundColor Cyan

$PersonalTop = @(
    "runtime", "data.json", "data", ".atlas", "logs", "bots",
    "exports", "swarm-workspaces", "swarm-output", "settings.local.json"
)
$SkipDirNames = @("__pycache__", ".pytest_cache", ".git")
$SourceBase = (Get-Item -LiteralPath $SourceAtlas).FullName.TrimEnd('\')
$DestBase = (Get-Item -LiteralPath $DestAtlas).FullName.TrimEnd('\')

function Test-SkippedRelPath {
    param([string]$RelPath)
    $parts = $RelPath -split '[\\/]'
    if ($parts.Length -ge 1 -and ($PersonalTop -contains $parts[0])) {
        return $true
    }
    foreach ($p in $parts) {
        if ($SkipDirNames -contains $p) { return $true }
    }
    if ($RelPath -match '\.(pyc|pyo|log|pyd)$') {
        return $true
    }
    return $false
}

$SourceFiles = @{}
foreach ($file in (Get-ChildItem -LiteralPath $SourceBase -File -Recurse)) {
    $rel = $file.FullName.Substring($SourceBase.Length).TrimStart('\')
    if (Test-SkippedRelPath -RelPath $rel) { continue }
    $SourceFiles[$rel] = $file
}

$Updated = 0
$Unchanged = 0
$Removed = 0
$RemovedPyd = 0

foreach ($rel in ($SourceFiles.Keys | Sort-Object)) {
    $src = $SourceFiles[$rel]
    $dst = Join-Path $DestBase $rel
    $needsCopy = $true
    if (Test-Path -LiteralPath $dst -PathType Leaf) {
        $dstItem = Get-Item -LiteralPath $dst
        if ($dstItem.Length -eq $src.Length) {
            $srcHash = (Get-FileHash -LiteralPath $src.FullName -Algorithm SHA256).Hash
            $dstHash = (Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash
            if ($srcHash -eq $dstHash) {
                $needsCopy = $false
            }
        }
    }
    if ($needsCopy) {
        Write-Host "  sync: $rel" -ForegroundColor Green
        if (-not $DryRun) {
            $parent = Split-Path -Parent $dst
            if (!(Test-Path -LiteralPath $parent -PathType Container)) {
                New-Item -ItemType Directory -Path $parent -Force | Out-Null
            }
            Copy-Item -LiteralPath $src.FullName -Destination $dst -Force
        }
        $Updated++
    } else {
        $Unchanged++
    }
}

# Remove compiled .pyd files outside runtime\ so Python runs the synced .py sources,
# and remove stale non-runtime files that were deleted from resources/atlas.
foreach ($file in (Get-ChildItem -LiteralPath $DestBase -File -Recurse)) {
    $rel = $file.FullName.Substring($DestBase.Length).TrimStart('\')
    $parts = $rel -split '[\\/]'
    if ($parts.Length -ge 1 -and ($PersonalTop -contains $parts[0])) { continue }
    if ($file.Extension -eq ".pyd") {
        Write-Host "  clear compiled module: $rel" -ForegroundColor Yellow
        if (-not $DryRun) { Remove-Item -LiteralPath $file.FullName -Force }
        $RemovedPyd++
        continue
    }
    if (Test-SkippedRelPath -RelPath $rel) { continue }
    if ($rel -eq "settings.json") { continue }
    if (-not $SourceFiles.ContainsKey($rel)) {
        Write-Host "  remove stale: $rel" -ForegroundColor Yellow
        if (-not $DryRun) { Remove-Item -LiteralPath $file.FullName -Force }
        $Removed++
    }
}

if ($BuildExe) {
    $BuiltExe = Join-Path $Tauri "target\release\atlas-desktop.exe"
    $DestExe = Join-Path $TargetInstall "atlas-desktop.exe"
    if (!(Test-Path -LiteralPath $BuiltExe -PathType Leaf)) {
        throw "Built executable missing: $BuiltExe"
    }
    Write-Host "  sync: atlas-desktop.exe" -ForegroundColor Green
    if (-not $DryRun) {
        Copy-Item -LiteralPath $BuiltExe -Destination $DestExe -Force
    }
}

Write-Host ("`nSync complete in {0:F2}s: {1} updated, {2} unchanged, {3} stale removed, {4} .pyd cleared." -f $Timer.Elapsed.TotalSeconds, $Updated, $Unchanged, $Removed, $RemovedPyd) -ForegroundColor Cyan

if ($Launch -and -not $DryRun) {
    $ExeToRun = Join-Path $TargetInstall "atlas-desktop.exe"
    if (Test-Path -LiteralPath $ExeToRun -PathType Leaf) {
        Write-Host "Launching $ExeToRun ..." -ForegroundColor Green
        Start-Process -FilePath $ExeToRun
    }
}
