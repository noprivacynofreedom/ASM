@echo off
setlocal
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if exist "%VSWHERE%" (
  for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSROOT=%%i"
)
if defined VSROOT (
  if exist "%VSROOT%\Common7\Tools\VsDevCmd.bat" call "%VSROOT%\Common7\Tools\VsDevCmd.bat" -arch=amd64 -host_arch=amd64
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build-Atlas-Rust-Test.ps1" %*
exit /b %ERRORLEVEL%
