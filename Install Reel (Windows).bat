@echo off
echo Installing Reel...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\windows\install.ps1"
pause
