# Starts the transcription server (Windows PowerShell 5.1 or 7).
# Run from this folder after creating the venv (see README.md):
#   powershell -ExecutionPolicy Bypass -File .\iniciar.ps1
# Settings come from environment variables; values below are only defaults.
# To use it from another machine, set TRANSCRICAO_HOST=0.0.0.0 AND a TRANSCRICAO_API_KEY,
# and keep the port closed to the internet (use a VPN or a firewall rule).

$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot

if (-not $env:TRANSCRICAO_HOST) { $env:TRANSCRICAO_HOST = '127.0.0.1' }
if (-not $env:TRANSCRICAO_PORTA) { $env:TRANSCRICAO_PORTA = '8000' }
if (-not $env:TRANSCRICAO_IDLE_SEGUNDOS) { $env:TRANSCRICAO_IDLE_SEGUNDOS = '300' }
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
$env:PYTHONUTF8 = '1'

$python = Join-Path $dir '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Error "venv not found: $python (create it first, see README.md)"
}

# Keep the previous log for troubleshooting.
foreach ($f in 'servidor.out.log', 'servidor.err.log') {
    $p = Join-Path $dir $f
    if (Test-Path $p) { Move-Item $p "$p.prev" -Force }
}

# Start-Process redirection avoids PowerShell 5 turning uvicorn stderr logging into errors.
$proc = Start-Process $python -ArgumentList 'servidor_transcricao.py' `
    -WorkingDirectory $dir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $dir 'servidor.out.log') `
    -RedirectStandardError (Join-Path $dir 'servidor.err.log')
Write-Host "Server started (PID $($proc.Id)) on http://$($env:TRANSCRICAO_HOST):$($env:TRANSCRICAO_PORTA)"
$proc.WaitForExit()
exit $proc.ExitCode
