@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sincronizar_vmix.ps1" %*
echo.
pause
