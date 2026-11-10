$ErrorActionPreference = "Stop"

$ProjectRoot = if ($env:ATLAS_PROJECT_ROOT) { $env:ATLAS_PROJECT_ROOT } else { $PSScriptRoot }
$DesktopExe = Join-Path $ProjectRoot "atlas-rust-desktop\src-tauri\target\release\atlas-desktop.exe"
$InstalledExe = Join-Path $ProjectRoot "installed\atlas-desktop.exe"
$LogRoot = Join-Path $env:APPDATA "dev.atlas.chat\logs"
$LogFile = Join-Path $LogRoot "startup.log"
$Mutex = $null
$MutexOwned = $false
$DesktopProcess = $null

New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null

function Write-AtlasLog {
    param([string]$Message)
    $Line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Add-Content -LiteralPath $LogFile -Value $Line
    Write-Host $Line
}

try {
    if (-not (Test-Path $ProjectRoot)) {
        throw "Atlas project directory is missing: $ProjectRoot"
    }

    Set-Location $ProjectRoot
    $env:ATLAS_PROJECT_ROOT = $ProjectRoot

    # Hold this lock for the entire desktop session, not just startup.
    $Mutex = [System.Threading.Mutex]::new(
        $false,
        "Local\AtlasChat.Desktop.Launcher"
    )

    try {
        $MutexOwned = $Mutex.WaitOne(0, $false)
    }
    catch [System.Threading.AbandonedMutexException] {
        $MutexOwned = $true
        Write-AtlasLog "Recovered abandoned launcher lock."
    }

    if (-not $MutexOwned) {
        Write-AtlasLog "Another Atlas launcher session owns the lock. Duplicate launch prevented."
        exit 0
    }

    Write-AtlasLog "Single-instance launcher lock acquired."

    foreach ($Required in @(
        "atlas-rust-desktop\src-tauri\resources\atlas\server.py",
        "settings.json",
        "agents\atlas_agent_runtime.py"
    )) {
        if (-not (Test-Path (Join-Path $ProjectRoot $Required))) {
            throw "Required Atlas file missing: $Required"
        }
    }

    if (Test-Path $InstalledExe) {
        $SelectedExe = $InstalledExe
    }
    elseif (Test-Path $DesktopExe) {
        $SelectedExe = $DesktopExe
        $env:ATLAS_PROJECT_ROOT = $ProjectRoot
    }
    else {
        throw "No Atlas Desktop executable found. Build the Rust desktop first."
    }

    $SelectedExe = (Resolve-Path $SelectedExe).Path
    Write-AtlasLog "Selected desktop executable: $SelectedExe"

    $Existing = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "atlas-desktop.exe" -and
        $_.ExecutablePath -and
        $_.ExecutablePath -ieq $SelectedExe
    })

    if ($Existing.Count -gt 0) {
        Write-AtlasLog "Matching Atlas Desktop process already exists. Duplicate launch prevented."
        exit 0
    }

    $Listeners = @(Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue)

    foreach ($Listener in $Listeners) {
        $Owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($Listener.OwningProcess)" -ErrorAction SilentlyContinue

        if (-not $Owner -or $Owner.CommandLine -notmatch [regex]::Escape($ProjectRoot)) {
            throw "Port 8090 is occupied by an unverified process (PID $($Listener.OwningProcess)). Nothing was terminated."
        }

        Write-AtlasLog "Existing Atlas backend listener detected: PID $($Listener.OwningProcess)."
    }

    Write-AtlasLog "Launching Atlas Desktop. Launcher lock remains held until desktop exits."

    $DesktopProcess = Start-Process `
        -FilePath $SelectedExe `
        -WorkingDirectory (Split-Path -Parent $SelectedExe) `
        -PassThru

    Write-AtlasLog "Atlas Desktop started. PID: $($DesktopProcess.Id)"

    $DesktopProcess.WaitForExit()
    Write-AtlasLog "Atlas Desktop exited with code $($DesktopProcess.ExitCode)."

}
catch {
    Write-AtlasLog "STARTUP FAILED: $($_.Exception.Message)"
    throw
}
finally {
    if ($MutexOwned -and $null -ne $Mutex) {
        try { $Mutex.ReleaseMutex() } catch {}
    }
    if ($null -ne $Mutex) {
        $Mutex.Dispose()
    }
    Write-AtlasLog "Launcher lock released."
}
