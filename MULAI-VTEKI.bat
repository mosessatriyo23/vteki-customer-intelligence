@echo off
setlocal
cd /d "%~dp0"
title VTEKI Customer Intelligence - Mulai Semua Layanan
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-VTEKI.ps1"
set "status=%ERRORLEVEL%"
if not "%status%"=="0" (
  echo.
  echo Gagal menjalankan VTEKI. Baca pesan di atas.
  pause
)
exit /b %status%
