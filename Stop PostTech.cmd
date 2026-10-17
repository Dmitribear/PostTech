@echo off
powershell.exe -NoProfile -File "%~dp0scripts\start_jury.ps1" -Stop
if errorlevel 1 pause
