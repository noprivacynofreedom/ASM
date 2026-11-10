param([switch]$Dev)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Project = Split-Path -Parent $Root

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { throw 'Rust/Cargo is missing.' }
if (-not (Get-Command rustc -ErrorAction SilentlyContinue)) { throw 'rustc is missing.' }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'Node.js/npm is missing.' }

$Linker = Get-Command link.exe -ErrorAction SilentlyContinue
if (-not $Linker) {
  $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
  if (Test-Path $vswhere) {
    $vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if ($vs) {
      $vcvars = Join-Path $vs 'VC\Auxiliary\Build\vcvars64.bat'
    }
  }
  throw 'MSVC linker link.exe was not found.'
}

$env:ATLAS_PROJECT_ROOT = $Project
Push-Location $Root
try {
  if (-not (Test-Path 'node_modules\@tauri-apps\cli')) {
    Write-Host 'Installing desktop frontend/build dependencies...' -ForegroundColor Cyan
    npm install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' }
  }
  
  if ($Dev) {
    npm run tauri dev
  } else {
    Write-Host 'Compiling production client assets...' -ForegroundColor Cyan
    npm run tauri build
    if ($LASTEXITCODE -ne 0) { throw 'Tauri release build failed.' }
    
    # [FIX 1] Define the path to your final generated NSIS setup installer file
    $InstallerExe = Join-Path $Root 'src-tauri\target\release\bundle\nsis\Atlas Chat_0.1.1_x64-setup.exe'
    if (-not (Test-Path $InstallerExe)) { throw "Tauri completed but setup installer artifact wasn't found at: $InstallerExe" }
    
    # [FIX 2] Dynamically locate the correct 64-bit Windows SDK signature utility
    # [FIX 2] Locate the 64-bit Windows SDK signature utility (Checking shell environment variables first)
    $SignTool = Get-Command signtool.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
    if (-not $SignTool) {
        $SignTool = (Get-ChildItem -Path "C:\Program Files (x86)\Windows Kits\10\bin\*\x64" -Filter "signtool.exe" -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
    }

    if ($SignTool) {
        Write-Host "Signing final installation bundle using: $SignTool" -ForegroundColor Cyan
        & $SignTool sign /a /fd SHA256 /un "Atlas Chat Local Development" $InstallerExe
    } else {
        Write-Host "Warning: signtool.exe not found. Skipping binary signature block." -ForegroundColor Yellow
    }


    # [FIX 3] Run the newly compiled installer completely silently to refresh shortcuts and files
    Write-Host "Deploying update silently and refreshing desktop shortcuts..." -ForegroundColor Green
    Start-Process -FilePath $InstallerExe -ArgumentList "/S" -Wait

    # Refresh Windows Shell icon cache
    Write-Host "Refreshing Windows Shell icon cache..." -ForegroundColor Cyan
    $code = '[DllImport("shell32.dll")] public static extern void SHChangeNotify(int wEventId, int uFlags, IntPtr dwItem1, IntPtr dwItem2);'
    $type = Add-Type -MemberDefinition $code -Name "Shell32" -Namespace "WinAPI" -PassThru
    $type::SHChangeNotify(0x08000000, 0x0000, [IntPtr]::Zero, [IntPtr]::Zero)

    Write-Host "End-to-End Build and Shortcut Update Succeeded!" -ForegroundColor Green
    Write-Host "To open your newly compiled version, you must click your desktop shortcut yourself." -ForegroundColor Yellow
  }
} finally { Pop-Location }