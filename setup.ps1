# POE Toolkit - Setup Script
# Run this script after cloning the repository
# Usage: Right-click -> Run with PowerShell (as Administrator)

param(
    [switch]$SkipInstalls,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# Colors for output
function Write-Status { param($msg) Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Success { param($msg) Write-Host "[+] $msg" -ForegroundColor Green }
function Write-Warning { param($msg) Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Error { param($msg) Write-Host "[-] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "       POE Toolkit Setup Script        " -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta
Write-Host ""

# Check if running as admin (needed for some installs)
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Warning "Not running as Administrator. Some installs may fail."
    Write-Warning "Consider re-running: Right-click -> Run as Administrator"
    Write-Host ""
}

# Get script directory (where poe-toolkit is cloned)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Status "Working directory: $scriptDir"
Write-Host ""

# ============================================
# CHECK PREREQUISITES
# ============================================

Write-Host "--- Checking Prerequisites ---" -ForegroundColor Yellow
Write-Host ""

$needsInstall = @()

# Check Python
Write-Status "Checking Python..."
$pythonPath = $null
$pythonVersion = $null

# Check common Python locations
$pythonPaths = @(
    "python",
    "python3",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
    "C:\Python312\python.exe",
    "C:\Python311\python.exe",
    "C:\Python310\python.exe"
)

foreach ($p in $pythonPaths) {
    try {
        $ver = & $p --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 10) {
                $pythonPath = $p
                $pythonVersion = $ver
                break
            }
        }
    } catch { }
}

if ($pythonPath) {
    Write-Success "Python found: $pythonVersion"
} else {
    Write-Warning "Python 3.10+ not found"
    $needsInstall += "python"
}

# Check Node.js
Write-Status "Checking Node.js..."
$nodeVersion = $null
try {
    $nodeVersion = & node --version 2>&1
    if ($nodeVersion -match "v(\d+)") {
        $major = [int]$Matches[1]
        if ($major -ge 18) {
            Write-Success "Node.js found: $nodeVersion"
        } else {
            Write-Warning "Node.js $nodeVersion found but 18+ required"
            $needsInstall += "nodejs"
        }
    }
} catch {
    Write-Warning "Node.js not found"
    $needsInstall += "nodejs"
}

# Check Tesseract
Write-Status "Checking Tesseract OCR..."
$tesseractPaths = @(
    "C:\Program Files\Tesseract-OCR\tesseract.exe",
    "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "$env:LOCALAPPDATA\Tesseract-OCR\tesseract.exe"
)
$tesseractFound = $false
foreach ($t in $tesseractPaths) {
    if (Test-Path $t) {
        $tesseractFound = $true
        Write-Success "Tesseract found: $t"
        break
    }
}
if (-not $tesseractFound) {
    Write-Warning "Tesseract OCR not found"
    $needsInstall += "tesseract"
}

# Check Brave
Write-Status "Checking Brave Browser..."
$bravePaths = @(
    "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    "C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    "$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\Application\brave.exe"
)
$braveFound = $false
foreach ($b in $bravePaths) {
    if (Test-Path $b) {
        $braveFound = $true
        Write-Success "Brave found: $b"
        break
    }
}
if (-not $braveFound) {
    Write-Warning "Brave Browser not found"
    $needsInstall += "brave"
}

Write-Host ""

# ============================================
# INSTALL MISSING PREREQUISITES
# ============================================

if ($needsInstall.Count -gt 0 -and -not $SkipInstalls) {
    Write-Host "--- Installing Missing Prerequisites ---" -ForegroundColor Yellow
    Write-Host ""
    
    # Check if winget is available
    $hasWinget = $false
    try {
        $wingetVer = & winget --version 2>&1
        $hasWinget = $true
        Write-Status "Using winget for installations"
    } catch {
        Write-Warning "winget not available, will use direct downloads"
    }
    
    foreach ($app in $needsInstall) {
        switch ($app) {
            "python" {
                Write-Status "Installing Python 3.12..."
                if ($hasWinget) {
                    & winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
                } else {
                    Write-Warning "Please install Python 3.10+ manually from https://python.org"
                }
            }
            "nodejs" {
                Write-Status "Installing Node.js LTS..."
                if ($hasWinget) {
                    & winget install OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements
                } else {
                    Write-Warning "Please install Node.js 18+ manually from https://nodejs.org"
                }
            }
            "tesseract" {
                Write-Status "Installing Tesseract OCR..."
                if ($hasWinget) {
                    & winget install UB-Mannheim.TesseractOCR --silent --accept-package-agreements --accept-source-agreements
                } else {
                    # Direct download fallback
                    $tesseractUrl = "https://github.com/UB-Mannheim/tesseract/releases/download/v5.3.3/tesseract-ocr-w64-setup-5.3.3.20231005.exe"
                    $tesseractInstaller = "$env:TEMP\tesseract-setup.exe"
                    Write-Status "Downloading Tesseract installer..."
                    Invoke-WebRequest -Uri $tesseractUrl -OutFile $tesseractInstaller
                    Write-Status "Running Tesseract installer (silent)..."
                    Start-Process -FilePath $tesseractInstaller -ArgumentList "/S" -Wait
                    Remove-Item $tesseractInstaller -ErrorAction SilentlyContinue
                }
            }
            "brave" {
                Write-Status "Installing Brave Browser..."
                if ($hasWinget) {
                    & winget install Brave.Brave --silent --accept-package-agreements --accept-source-agreements
                } else {
                    Write-Warning "Please install Brave manually from https://brave.com"
                }
            }
        }
    }
    
    Write-Host ""
    Write-Success "Prerequisite installation complete!"
    Write-Warning "You may need to restart your terminal for PATH changes to take effect."
    Write-Host ""
}

# ============================================
# SETUP USER CONFIG
# ============================================

Write-Host "--- Setting Up Configuration ---" -ForegroundColor Yellow
Write-Host ""

$userConfigPath = Join-Path $scriptDir "config\user_config.json"
$templatePath = Join-Path $scriptDir "config\user_config.template.json"

if (-not (Test-Path $userConfigPath) -or $Force) {
    if (Test-Path $templatePath) {
        Write-Status "Creating user_config.json from template..."
        Copy-Item $templatePath $userConfigPath
        Write-Success "Created config/user_config.json"
        Write-Warning "IMPORTANT: Edit config/user_config.json with your settings:"
        Write-Host "  - session_id: Your POESESSID cookie" -ForegroundColor Gray
        Write-Host "  - account_name: Your PoE account name" -ForegroundColor Gray
        Write-Host "  - league: Current league name" -ForegroundColor Gray
        Write-Host "  - client_log_path: Path to PoE Client.txt" -ForegroundColor Gray
    } else {
        Write-Error "Template file not found: $templatePath"
    }
} else {
    Write-Success "user_config.json already exists (use -Force to overwrite)"
}

Write-Host ""

# ============================================
# INSTALL PYTHON DEPENDENCIES
# ============================================

Write-Host "--- Installing Python Dependencies ---" -ForegroundColor Yellow
Write-Host ""

# Refresh Python path after potential install
$pythonCmd = "python"
try {
    & python --version 2>&1 | Out-Null
} catch {
    try {
        & python3 --version 2>&1 | Out-Null
        $pythonCmd = "python3"
    } catch {
        Write-Error "Python not found. Please restart terminal and run setup again."
    }
}

$requirementsPath = Join-Path $scriptDir "requirements.txt"
if (Test-Path $requirementsPath) {
    Write-Status "Installing Python packages..."
    & $pythonCmd -m pip install -r $requirementsPath --quiet
    Write-Success "Python dependencies installed"
} else {
    Write-Warning "requirements.txt not found"
}

Write-Host ""

# ============================================
# INSTALL NODE.JS DEPENDENCIES
# ============================================

Write-Host "--- Installing Node.js Dependencies ---" -ForegroundColor Yellow
Write-Host ""

$tradeServiceDir = Join-Path $scriptDir "trade_service"
$packageJsonPath = Join-Path $tradeServiceDir "package.json"

if (Test-Path $packageJsonPath) {
    Write-Status "Installing npm packages for Trade Sniper..."
    Push-Location $tradeServiceDir
    try {
        & npm install --silent 2>&1 | Out-Null
        Write-Success "Node.js dependencies installed"
    } catch {
        Write-Warning "npm install failed - Node.js may need PATH refresh"
    }
    Pop-Location
} else {
    Write-Warning "trade_service/package.json not found"
}

Write-Host ""

# ============================================
# COMPLETE
# ============================================

Write-Host "========================================" -ForegroundColor Green
Write-Host "          Setup Complete!              " -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Edit config/user_config.json with your settings" -ForegroundColor White
Write-Host "  2. Run: python src/main.py" -ForegroundColor White
Write-Host "  3. Calibrate your stash overlay (Settings menu)" -ForegroundColor White
Write-Host ""
Write-Host "For Trade Sniper, Brave will be auto-launched from the app." -ForegroundColor Gray
Write-Host ""

# Pause if running interactively
if ($Host.Name -eq "ConsoleHost") {
    Write-Host "Press any key to exit..." -ForegroundColor DarkGray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}

