@echo off
chcp 65001 >nul
rem Start Neo4j + API. Args are passed through: start.bat -Restart
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
echo.
pause
