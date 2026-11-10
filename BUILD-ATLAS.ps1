[CmdletBinding()]
param([switch]$SkipTauriBundle)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Desktop = Join-Path $Root 'atlas-rust-desktop'
if (-not (Test-Path (Join-Path $Desktop 'package.json'))) { throw 'Atlas Desktop source is missing.' }
Write-Host '== Atlas Desktop: install locked frontend dependencies =='
Push-Location $Desktop
try {
  npm ci
  if ($LASTEXITCODE -ne 0) { throw "npm ci failed: $LASTEXITCODE" }
  Write-Host '== Atlas Desktop: TypeScript + Vite build =='
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "npm run build failed: $LASTEXITCODE" }
  Write-Host '== Atlas Desktop: Rust format/check/test =='
  Push-Location (Join-Path $Desktop 'src-tauri')
  try {
    cargo fmt --all
    if ($LASTEXITCODE -ne 0) { throw "cargo fmt failed: $LASTEXITCODE" }
    cargo check --locked
    if ($LASTEXITCODE -ne 0) { throw "desktop cargo check failed: $LASTEXITCODE" }
    cargo test --locked
    if ($LASTEXITCODE -ne 0) { throw "desktop cargo test failed: $LASTEXITCODE" }
  } finally { Pop-Location }
  if (-not $SkipTauriBundle) {
    Write-Host '== Atlas Desktop: package NSIS/MSI =='
    npm run tauri build
    if ($LASTEXITCODE -ne 0) { throw "Tauri bundle failed: $LASTEXITCODE" }
  }
} finally { Pop-Location }
Write-Host '== Chat queue JavaScript regression tests =='
Push-Location $Root
try {
  node validation-tests\test_chat_queue.js atlas-rust-desktop\src-tauri\resources\atlas\index.html
  if ($LASTEXITCODE -ne 0) { throw "Chat queue source checks failed: $LASTEXITCODE" }
  node validation-tests\test_chat_queue_runtime.js atlas-rust-desktop\src-tauri\resources\atlas\index.html
  if ($LASTEXITCODE -ne 0) { throw "Chat queue runtime checks failed: $LASTEXITCODE" }
  Push-Location $Desktop
  try {
    node validation-tests\test_chat_queue.js src-tauri\resources\atlas\index.html
    if ($LASTEXITCODE -ne 0) { throw "Desktop chat queue checks failed: $LASTEXITCODE" }
  } finally { Pop-Location }
} finally { Pop-Location }
Write-Host '== Existing Atlas Python + contract regression tests =='
Push-Location $Root
try {
  python -m unittest discover -s tests -p "test_*.py" -v
  if ($LASTEXITCODE -ne 0) { throw "Atlas unittest suite failed: $LASTEXITCODE" }
  python -m unittest discover -s validation-tests -p "test_*.py" -v
  if ($LASTEXITCODE -ne 0) { throw "Root validation-tests failed: $LASTEXITCODE" }
  Push-Location atlas-rust-desktop\validation-tests
  try {
    python -m unittest discover -p "test_*.py" -v
    if ($LASTEXITCODE -ne 0) { throw "Desktop validation-tests failed: $LASTEXITCODE" }
  } finally { Pop-Location }
  python -m compileall -q -x '(^|[\\/])(\.atlas[^\\/]*|target|runtime|node_modules|build|dist)([\\/]|$)' .
  if ($LASTEXITCODE -ne 0) { throw "compileall failed: $LASTEXITCODE" }
} finally { Pop-Location }
Write-Host 'Atlas build and tests completed successfully.'
