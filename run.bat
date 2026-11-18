@echo off
chcp 65001 >nul
rem Task entry: run.bat serve / index / images / vision / test / eval / api-test
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
