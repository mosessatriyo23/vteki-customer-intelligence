# Stops only this project's Docker Compose services. Keeps PostgreSQL volume/data.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker tidak ditemukan.' }
    $priorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & docker compose down
        $stopExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $priorPreference
    }
    if ($stopExit -ne 0) { throw 'docker compose down gagal.' }
    Write-Host 'VTEKI berhenti. Data PostgreSQL tetap aman.' -ForegroundColor Green
} catch {
    Write-Host "GAGAL: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
