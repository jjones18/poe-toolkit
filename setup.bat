@echo off
setlocal
echo POE Toolkit Setup
echo.
echo This creates a private virtual environment and installs prerequisites.
echo Administrator privileges are not required.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -NonInteractive
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" echo Setup failed with exit code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
