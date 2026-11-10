$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Python launcher (py) not found. Install Python 3 and enable the py launcher.' }
Write-Host 'Installing Atlas knowledge ingestion and local embedding dependencies into Python 3...' -ForegroundColor Cyan
& py -3 -m pip install --user -r (Join-Path $Root 'requirements-knowledge.txt')
if ($LASTEXITCODE -ne 0) { throw 'Knowledge dependency installation failed.' }
if (Get-Command tesseract -ErrorAction SilentlyContinue) {
  Write-Host 'Tesseract OCR detected. Scanned-PDF OCR is available.' -ForegroundColor Green
} else {
  Write-Warning 'Tesseract OCR executable not found. Text PDFs and embeddings work, but scanned-PDF OCR requires Tesseract OCR installed and available on PATH.'
}
Write-Host 'Pre-fetching the local BGE-small embedding model (first run only)...' -ForegroundColor Cyan
& py -3 -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5'); print('BGE-small model ready')"
if ($LASTEXITCODE -ne 0) { Write-Warning 'Embedding model prefetch did not complete. Atlas will use lexical fallback until the model is available; retry this setup step when internet is available.' }
Write-Host 'Knowledge dependencies installed. Embeddings run locally after the one-time model download.' -ForegroundColor Green
