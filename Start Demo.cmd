@echo off
chcp 65001 >nul
title PostTech - Site and Telegram
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_telegram.ps1" -Interactive -OpenBrowser
if errorlevel 1 (
  echo.
  echo Startup failed. Read the message above, fix the issue and try again.
)
echo.
pause
