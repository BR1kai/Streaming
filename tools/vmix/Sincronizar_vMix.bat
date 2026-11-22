@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (py sincronizar_vmix.py %* & goto fin)
where python >nul 2>nul && (python sincronizar_vmix.py %* & goto fin)
echo No encuentro Python en este PC. Avisa y preparo la version sin Python.
:fin
echo.
pause
