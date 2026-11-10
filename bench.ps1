# Benchmarks one model at several --n-cpu-moe values with llama-bench.
# Stops llama-swap first (frees the GPU), restarts it at the end.
# Usage: & '.\bench.ps1' -ToolsDir <tools folder> -Model <path.gguf> -Moe "8,12,16,20" [-Ngl 99]
param([string]$Model, [string]$Moe = "0", [string]$Ngl = "99", [string]$Out = (Join-Path $PSScriptRoot "bench-results.md"),
      [string]$ToolsDir = $env:ATLAS_TOOLS_DIR)
if (-not $ToolsDir) { throw 'Set -ToolsDir or the ATLAS_TOOLS_DIR environment variable (folder with llama-vulkan and llama-swap).' }
# ToolsDir holds llama-vulkan\ and llama-swap\. Override with -ToolsDir or the ATLAS_TOOLS_DIR environment variable.
Get-Process llama-swap, llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 2
"`n## $(Split-Path $Model -Leaf)  ($(Get-Date -Format 'yyyy-MM-dd HH:mm'))" | Add-Content $Out
& (Join-Path $ToolsDir 'llama-vulkan\llama-bench.exe') -m $Model -ngl $Ngl -ncmoe $Moe -fa on -lm none -t 8 -p 512 -n 128 -r 2 2>&1 |
  Where-Object { $_ -match '^\|' } | Tee-Object -FilePath $Out -Append
$Swap = Join-Path $ToolsDir 'llama-swap'
Start-Process -FilePath (Join-Path $Swap 'llama-swap.exe') -ArgumentList "--config `"$(Join-Path $Swap 'config.yaml')`" --listen 127.0.0.1:8080" -WorkingDirectory $Swap -WindowStyle Hidden
"BENCH DONE"
