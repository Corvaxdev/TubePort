@echo off
rem SPDX-License-Identifier: MIT
rem Copyright (c) 2026 nanomicron
setlocal
title TubePort tool setup
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-Tools.ps1"
if errorlevel 1 (
  echo.
  echo Setup failed. Review the message above and try again.
  pause
  exit /b 1
)
echo.
pause
