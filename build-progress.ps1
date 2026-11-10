# build-progress.ps1 - live step board for build-release.ps1.
# Display only: it never changes what the build does. Dot-sourced by build-release.ps1.
# Every function swallows its own errors so a display problem cannot fail a build.
# Keep this file ASCII only (Windows PowerShell 5.1 reads BOM-less files as ANSI).

$script:AtlasStepNames = @(
    "Check bundled backend",
    "Back up existing outputs",
    "Isolate previous outputs",
    "Build app and installer (front end, Rust, makensis)",
    "Verify executable and installer"
)
$script:AtlasStepState = @("todo", "todo", "todo", "todo", "todo")
$script:AtlasStepSeconds = @(0, 0, 0, 0, 0)
$script:AtlasCurrent = -1
$script:AtlasStepStart = $null
$script:AtlasRunStart = $null
$script:AtlasShared = $null
$script:AtlasShell = $null
$script:AtlasHandle = $null
$script:AtlasOldTitle = $null

function Format-AtlasTime {
    param([double]$Seconds)
    $total = [int][math]::Floor($Seconds)
    $minutes = [int][math]::Floor($total / 60)
    $rest = $total % 60
    return ("{0:00}:{1:00}" -f $minutes, $rest)
}

function Write-AtlasRow {
    param([string]$Icon, [string]$IconColor, [string]$Text)
    Write-Host ("  {0} " -f $Icon) -NoNewline -ForegroundColor $IconColor
    Write-Host $Text -ForegroundColor White
}

# Dark Kanban board: green check = done, yellow dot = running, grey circle = waiting.
function Show-AtlasBoard {
    try {
        $check = [string][char]0x2713
        $dot = [string][char]0x25CF
        $circle = [string][char]0x25CB
        $elapsed = (Get-Date) - $script:AtlasRunStart
        $count = $script:AtlasStepNames.Count
        $number = [math]::Max($script:AtlasCurrent + 1, 0)
        Write-Host ""
        Write-Host ("===== ATLAS BUILD BOARD // step {0} of {1} // total {2} =====" -f $number, $count, (Format-AtlasTime $elapsed.TotalSeconds)) -ForegroundColor White
        Write-Host "Completed" -ForegroundColor White
        $any = $false
        for ($i = 0; $i -lt $count; $i++) {
            if ($script:AtlasStepState[$i] -eq "done") {
                Write-AtlasRow $check "Green" ("{0} ({1})" -f $script:AtlasStepNames[$i], (Format-AtlasTime $script:AtlasStepSeconds[$i]))
                $any = $true
            }
        }
        if (!$any) { Write-Host "  none yet" -ForegroundColor Gray }
        Write-Host "In progress" -ForegroundColor White
        $any = $false
        for ($i = 0; $i -lt $count; $i++) {
            if ($script:AtlasStepState[$i] -eq "active") {
                Write-AtlasRow $dot "Yellow" ("{0} (live timer is in the window title)" -f $script:AtlasStepNames[$i])
                $any = $true
            }
        }
        if (!$any) { Write-Host "  none" -ForegroundColor Gray }
        Write-Host "Remaining" -ForegroundColor White
        $any = $false
        for ($i = 0; $i -lt $count; $i++) {
            if ($script:AtlasStepState[$i] -eq "todo") {
                Write-AtlasRow $circle "Gray" $script:AtlasStepNames[$i]
                $any = $true
            }
        }
        if (!$any) { Write-Host "  none" -ForegroundColor Gray }
    }
    catch { }
}

# Starts a background timer that keeps the window title alive: spinner, step, what is
# running (Rust compile or makensis), step time and total time.
function Start-AtlasProgress {
    try {
        $script:AtlasRunStart = Get-Date
        $script:AtlasOldTitle = [Console]::Title
        $script:AtlasShared = [hashtable]::Synchronized(@{
            Stop      = $false
            Index     = 0
            Count     = $script:AtlasStepNames.Count
            Name      = "starting"
            RunStart  = $script:AtlasRunStart
            StepStart = $script:AtlasRunStart
        })
        $script:AtlasShell = [powershell]::Create()
        $null = $script:AtlasShell.AddScript({
            param($Shared)
            $frames = @("|", "/", "-", "\")
            $tick = 0
            $limit = (Get-Date).AddHours(3)
            while ((-not $Shared.Stop) -and ((Get-Date) -lt $limit)) {
                try {
                    $now = Get-Date
                    $run = [int]($now - $Shared.RunStart).TotalSeconds
                    $step = [int]($now - $Shared.StepStart).TotalSeconds
                    $activity = ""
                    if (Get-Process -Name makensis -ErrorAction SilentlyContinue) { $activity = " - packing installer (makensis)" }
                    elseif (Get-Process -Name rustc, cargo -ErrorAction SilentlyContinue) { $activity = " - compiling Rust" }
                    $runText = "{0:00}:{1:00}" -f [math]::Floor($run / 60), ($run % 60)
                    $stepText = "{0:00}:{1:00}" -f [math]::Floor($step / 60), ($step % 60)
                    [Console]::Title = ("Atlas build {0} step {1}/{2}: {3}{4} | step {5} | total {6}" -f $frames[$tick % 4], $Shared.Index, $Shared.Count, $Shared.Name, $activity, $stepText, $runText)
                }
                catch { }
                $tick++
                Start-Sleep -Milliseconds 400
            }
        }).AddArgument($script:AtlasShared)
        $script:AtlasHandle = $script:AtlasShell.BeginInvoke()
    }
    catch { }
}

function Set-AtlasStep {
    param([int]$Number)
    try {
        $index = $Number - 1
        $now = Get-Date
        if ($script:AtlasCurrent -ge 0) {
            $script:AtlasStepState[$script:AtlasCurrent] = "done"
            $script:AtlasStepSeconds[$script:AtlasCurrent] = ($now - $script:AtlasStepStart).TotalSeconds
        }
        $script:AtlasCurrent = $index
        $script:AtlasStepStart = $now
        $script:AtlasStepState[$index] = "active"
        if ($script:AtlasShared) {
            $script:AtlasShared.Index = $Number
            $script:AtlasShared.Name = $script:AtlasStepNames[$index]
            $script:AtlasShared.StepStart = $now
        }
        Show-AtlasBoard
    }
    catch { }
}

# Marks the last running step done and prints the final board.
function Complete-AtlasProgress {
    try {
        $now = Get-Date
        if ($script:AtlasCurrent -ge 0) {
            $script:AtlasStepState[$script:AtlasCurrent] = "done"
            $script:AtlasStepSeconds[$script:AtlasCurrent] = ($now - $script:AtlasStepStart).TotalSeconds
        }
        Show-AtlasBoard
    }
    catch { }
}

function Stop-AtlasProgress {
    try {
        if ($script:AtlasShared) { $script:AtlasShared.Stop = $true }
        if ($script:AtlasShell) {
            if ($script:AtlasHandle) { [void]$script:AtlasHandle.AsyncWaitHandle.WaitOne(2000) }
            $script:AtlasShell.Dispose()
        }
        if ($script:AtlasOldTitle) { [Console]::Title = $script:AtlasOldTitle }
    }
    catch { }
    $script:AtlasShell = $null
    $script:AtlasShared = $null
}
