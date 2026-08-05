#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "No virtualenv. Run .\setup.ps1 first." }

$target = if ($args.Count) { $args[0] } else { "app" }

switch ($target) {
    "app" {
        if (-not (Test-Path "frontend\dist\index.html")) {
            Write-Host "Building frontend..." -ForegroundColor Cyan
            Push-Location frontend; npm install; npm run build; Pop-Location
        }
        Write-Host "http://localhost:8000" -ForegroundColor Green
        & $py -m uvicorn api.main:app --port 8000
    }
    "dev" {
        Write-Host "API on :8000, Vite on :5173" -ForegroundColor Green
        Start-Process $py -ArgumentList "-m", "uvicorn", "api.main:app", "--port", "8000", "--reload"
        Push-Location frontend; npm run dev; Pop-Location
    }
    "cli"       { & $py -m src.cli @($args | Select-Object -Skip 1) }
    "demo"      { & $py -m src.cli --demo }
    "streamlit" { & $py -m streamlit run src\app.py }
    "test"      { & $py -m pytest }
    "eval"      { & $py eval\run_eval.py @($args | Select-Object -Skip 1) }
    "ingest"    { & $py -m src.ingest --rebuild }
    "backend"   { & $py -m src.llm }
    default {
        Write-Host "Usage: .\run.ps1 [target]"
        Write-Host "  app        build frontend and serve the full stack on :8000 (default)"
        Write-Host "  dev        API with reload plus the Vite dev server"
        Write-Host "  cli        interactive terminal client"
        Write-Host "  demo       scripted walkthrough"
        Write-Host "  streamlit  alternative Streamlit UI"
        Write-Host "  test       pytest suite"
        Write-Host "  eval       retrieval recall benchmark"
        Write-Host "  ingest     rebuild the vector index"
        Write-Host "  backend    report the live model backend"
    }
}
