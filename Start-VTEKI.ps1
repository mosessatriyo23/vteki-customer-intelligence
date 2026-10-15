# VTEKI Customer Intelligence: one-click Windows launcher (Docker Compose)
# Place this file in the repository root, alongside docker-compose.yml.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

function Info([string]$message) { Write-Host "[VTEKI] $message" -ForegroundColor Cyan }
function Fail([string]$message) { throw $message }

function New-RandomSecret([int]$byteCount) {
    $bytes = New-Object 'System.Byte[]' $byteCount
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Test-DockerReady {
    try {
        & docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Test-HttpReady([string]$url) {
    try {
        $result = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
        return ($result.StatusCode -eq 200)
    } catch { return $false }
}

try {
    if (-not (Test-Path -LiteralPath (Join-Path $root 'docker-compose.yml') -PathType Leaf)) {
        Fail 'Letakkan Start-VTEKI.ps1 dan MULAI-VTEKI.bat di folder utama project (sejajar docker-compose.yml).'
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Fail 'Docker belum ditemukan. Install Docker Desktop untuk Windows, lalu jalankan kembali MULAI-VTEKI.bat.'
    }

    if (-not (Test-DockerReady)) {
        Info 'Docker Engine belum berjalan. Mencoba membuka Docker Desktop ...'
        $desktopCandidates = @(
            (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
            (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe')
        )
        $desktop = $desktopCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
        if ($desktop) {
            Start-Process -FilePath $desktop | Out-Null
            for ($i = 0; $i -lt 60; $i++) {
                if (Test-DockerReady) { break }
                Start-Sleep -Seconds 3
            }
        }
    }
    if (-not (Test-DockerReady)) {
        Fail 'Docker Desktop belum siap. Buka Docker Desktop, tunggu sampai Engine Running, kemudian coba lagi.'
    }
    & docker compose version | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail 'Docker Compose tidak tersedia. Perbarui Docker Desktop.' }

    # Generate strong local-only credentials exactly once; never rewrite an existing .env.
    $envPath = Join-Path $root '.env'
    $createdEnv = $false
    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
        $postgresPassword = New-RandomSecret 30
        $jwtSecret = New-RandomSecret 48
        $adminPassword = New-RandomSecret 24
        $adminEmail = 'admin@vteki.local'
        $content = @(
            'POSTGRES_USER=postgres'
            "POSTGRES_PASSWORD=$postgresPassword"
            'POSTGRES_DB=vteki_intelligence'
            "DATABASE_URL=postgresql+psycopg://postgres:${postgresPassword}@db:5432/vteki_intelligence"
            "JWT_SECRET=$jwtSecret"
            'ACCESS_TOKEN_TTL_MINUTES=30'
            'PIPELINE_INTERVAL_MINUTES=15'
            "BOOTSTRAP_ADMIN_EMAIL=$adminEmail"
            "BOOTSTRAP_ADMIN_PASSWORD=$adminPassword"
        ) -join "`n"
        [System.IO.File]::WriteAllText($envPath, $content + "`n", (New-Object System.Text.UTF8Encoding($false)))
        $createdEnv = $true
        Info 'File .env dibuat dengan password acak yang kuat. File ini tidak boleh di-commit.'
    }

    $config = @{}
    foreach ($line in [System.IO.File]::ReadAllLines($envPath)) {
        if ($line -match '^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$') {
            $config[$matches[1]] = $matches[2].Trim('"', "'")
        }
    }
    foreach ($key in @('POSTGRES_PASSWORD', 'JWT_SECRET', 'BOOTSTRAP_ADMIN_EMAIL', 'BOOTSTRAP_ADMIN_PASSWORD')) {
        if (-not $config.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($config[$key])) {
            Fail "Nilai '$key' tidak ada di .env. Isi lebih dulu sebelum menjalankan VTEKI."
        }
    }
    if ($config['POSTGRES_PASSWORD'] -match '^(change-this|replace-with|GANTI_)' -or
        $config['JWT_SECRET'] -match '^(change-this|replace-with|GANTI_)' -or
        $config['BOOTSTRAP_ADMIN_PASSWORD'] -match '^(change-this|replace-with|GANTI_)' -or
        $config['JWT_SECRET'].Length -lt 32 -or $config['BOOTSTRAP_ADMIN_PASSWORD'].Length -lt 12) {
        Fail 'File .env masih memakai contoh/kredensial terlalu pendek. Perbarui dengan password unik dan JWT_SECRET minimal 32 karakter. Jangan mengubah POSTGRES_PASSWORD jika volume DB lama masih dipakai.'
    }

    Info 'Menjalankan PostgreSQL, backend API, worker, dan React/Nginx ...'
    # Docker Compose may print progress on stderr even on success in Windows PowerShell 5.1.
    # Check its exit code explicitly rather than treating every stderr line as fatal.
    $priorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & docker compose up -d --build
        $composeExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $priorPreference
    }
    if ($composeExit -ne 0) {
        Write-Host 'Docker Compose gagal. Kemungkinan port 80/8000/5432 sudah digunakan atau build bermasalah.' -ForegroundColor Yellow
        & docker compose ps
        Fail 'Lihat error Docker Compose di atas. Jangan hentikan proses lain secara paksa.'
    }

    Info 'Menunggu backend API dan website siap (maksimal 3 menit) ...'
    $ready = $false
    for ($i = 0; $i -lt 90; $i++) {
        if ((Test-HttpReady 'http://127.0.0.1:8000/health') -and
            (Test-HttpReady 'http://127.0.0.1/api/health')) {
            $ready = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        Write-Host 'Diagnostik Docker Compose:' -ForegroundColor Yellow
        & docker compose ps
        & docker compose logs --tail 30 api web
        Fail 'Website/API belum siap. Cek log di atas.'
    }

    Info 'Menyiapkan admin pertama (jika database masih kosong) ...'
    $priorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $bootstrapOutput = (& docker compose exec -T api python -m api.bootstrap 2>&1 | Out-String)
        $bootstrapExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $priorPreference
    }
    $newAdmin = $false
    if ($bootstrapExit -eq 0) {
        $newAdmin = $true
        Info 'Akun administrator pertama berhasil dibuat.'
    } elseif ($bootstrapOutput -match 'Bootstrap refused: users already exist') {
        Info 'Akun pengguna sudah ada. Login menggunakan akun lama (tidak diubah).'
    } else {
        Write-Host $bootstrapOutput -ForegroundColor Yellow
        Fail 'Bootstrap admin gagal karena alasan lain. Periksa pesan di atas.'
    }

    Write-Host ''
    Write-Host '====================================================' -ForegroundColor Green
    Write-Host ' VTEKI SUDAH SIAP - WEBSITE: http://localhost' -ForegroundColor Green
    Write-Host ' API DOCS: http://localhost:8000/docs'
    Write-Host '====================================================' -ForegroundColor Green
    if ($newAdmin) {
        Write-Host "Email login       : $($config['BOOTSTRAP_ADMIN_EMAIL'])" -ForegroundColor Yellow
        Write-Host "Password pertama  : $($config['BOOTSTRAP_ADMIN_PASSWORD'])" -ForegroundColor Yellow
        Write-Host 'Simpan password ini secara privat; ada juga di file .env (jangan upload/commit).' -ForegroundColor Yellow
    } elseif ($createdEnv) {
        Write-Host 'Catatan: database sudah punya akun, jadi password admin baru tidak digunakan.' -ForegroundColor Yellow
    }
    Write-Host 'Berhenti: klik STOP-VTEKI.bat (data PostgreSQL tetap disimpan).'
    Write-Host ''

    Start-Process 'http://localhost/' | Out-Null
} catch {
    Write-Host ''
    Write-Host "[GAGAL] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Bila perlu, jalankan: docker compose logs --tail 50 api web db' -ForegroundColor Yellow
    exit 1
}
