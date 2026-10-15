@echo off
setlocal
cd /d "%~dp0"
title VTEKI Customer Intelligence - Hentikan Layanan
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Stop-VTEKI.ps1"
set "status=%ERRORLEVEL%"
echo.
if "%status%"=="0" (echo Layanan telah dihentikan.) else (echo Terjadi kesalahan. Lihat pesan di atas.)
pause
exit /b %status%
