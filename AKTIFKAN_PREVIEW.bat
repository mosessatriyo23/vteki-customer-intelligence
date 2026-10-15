@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  VTEKI - AKTIFKAN PREVIEW DASHBOARD TANPA LOGIN
echo  -------------------------------------------------
echo.
where python >nul 2>&1
if errorlevel 1 (
  echo Python tidak ditemukan. Jalankan launcher ini lewat terminal VS Code yang bisa menjalankan Python.
  pause
  exit /b 1
)
python "%~dp0AKTIFKAN_PREVIEW_DASHBOARD.py"
if errorlevel 1 (
  echo.
  echo Pemasangan gagal. Periksa pesan di atas.
  pause
  exit /b 1
)
echo.
echo Jika Vite sedang berjalan, refresh http://localhost:5173
 echo Jika memakai Docker, jalankan: docker compose up -d --build web
pause
