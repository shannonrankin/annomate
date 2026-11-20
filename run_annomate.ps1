# Launch Annomate Web Platform + Auto-Open Browser
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Error "Virtual environment not found at $PythonExe. Double-click Start_Annomate.bat for automatic first-time setup."
}

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  annomate · Bioacoustic Annotation & Cloud Metadata Platform" -ForegroundColor Cyan
Write-Host "  Web Platform : http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "  Docs Hub     : http://127.0.0.1:8000/guide" -ForegroundColor Green
Write-Host "  Marimo Studio: http://127.0.0.1:2718 (auto-started on Review)" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Cyan

Start-Job -ScriptBlock { Start-Sleep -Seconds 2; Start-Process "http://127.0.0.1:8000" } | Out-Null
& $PythonExe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
