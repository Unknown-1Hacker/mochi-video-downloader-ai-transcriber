@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\bootstrap.ps1"
if errorlevel 1 (echo Setup needs attention. & pause & exit /b 1)
