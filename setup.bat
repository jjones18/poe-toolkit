@echo off
echo POE Toolkit Setup
echo.
echo This will install prerequisites and configure the toolkit.
echo Please run as Administrator for best results.
echo.
pause

:: Run PowerShell script with bypass for execution policy
powershell -ExecutionPolicy Bypass -File "%~dp0setup.ps1"

