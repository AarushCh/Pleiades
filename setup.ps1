#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$WithOllama = $args -contains "-WithOllama"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

Step "Python environment"
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $launcher = if (Get-Command uv -EA SilentlyContinue) { "uv" } else { "py" }
    if ($launcher -eq "uv") { uv venv --python 3.13 .venv } else { py -3 -m venv .venv }
}
if (Get-Command uv -EA SilentlyContinue) {
    uv pip install --python $py -r requirements.txt
} else {
    & $py -m pip install --upgrade pip
    & $py -m pip install -r requirements.txt
}

Step "Configuration"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env - add an API key, or use -WithOllama for a local model."
}

Step "Vector index"
& $py -m src.ingest

if ($WithOllama) {
    Step "Ollama"
    if (-not (Get-Command ollama -EA SilentlyContinue)) {
        Write-Host "Installing Ollama via winget..."
        winget install --id Ollama.Ollama --exact --silent `
            --accept-package-agreements --accept-source-agreements
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                    [Environment]::GetEnvironmentVariable("Path", "User")
    }

    $model = "llama3"
    foreach ($line in (Get-Content ".env" -EA SilentlyContinue)) {
        if ($line -match "^OLLAMA_MODEL=(.+)$") { $model = $Matches[1].Trim() }
    }

    try { Invoke-WebRequest "http://localhost:11434/api/tags" -TimeoutSec 3 -UseBasicParsing | Out-Null }
    catch { Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden; Start-Sleep 5 }

    Write-Host "Pulling $model (~4.7 GB, one time)..."
    ollama pull $model
}

Step "Backend check"
& $py -m src.llm

Write-Host "`nReady." -ForegroundColor Green
Write-Host "  .venv\Scripts\streamlit run src\app.py"
Write-Host "  .venv\Scripts\python -m src.cli --demo"
