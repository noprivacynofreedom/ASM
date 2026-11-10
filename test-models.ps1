# Tests each model through Atlas Chat (8090 -> llama-swap 8080). Usage:
#   & '.\test-models.ps1' -Models coder,mentor,assist,tasks   (run from the app folder)
param([string[]]$Models = @("coder","mentor","assist","tasks"))
$prompt = "In 2 short sentences: what is one quick way to get a first sale on a new Shopify store?"
foreach ($m in $Models) {
  $body = @{ model = $m; max_tokens = 600; messages = @(@{ role = "user"; content = $prompt }) } | ConvertTo-Json -Depth 5
  $t = [Diagnostics.Stopwatch]::StartNew()
  try {
    $r = Invoke-RestMethod -Uri http://127.0.0.1:8090/v1/chat/completions -Method Post -ContentType "application/json" -Body $body -TimeoutSec 600
    $t.Stop()
    $txt = ($r.choices[0].message.content -replace "\s+", " ").Trim()
    if ($txt.Length -gt 160) { $txt = $txt.Substring(0,160) + "..." }
    "{0,-7} OK   {1,5:N1}s total  {2,5:N1} tok/s  | {3}" -f $m, $t.Elapsed.TotalSeconds, $r.timings.predicted_per_second, $txt
  } catch {
    "{0,-7} FAIL {1}" -f $m, $_.Exception.Message
  }
}
"TESTS DONE"
