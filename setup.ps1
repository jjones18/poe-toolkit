# POE Toolkit fresh Windows setup. Run from a cloned checkout.
param(
    [switch]$SkipInstalls,
    [switch]$Force,
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

function Write-Status { param([string]$Message) Write-Host "[*] $Message" -ForegroundColor Cyan }
function Write-Success { param([string]$Message) Write-Host "[+] $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "[!] $Message" -ForegroundColor Yellow }
function Invoke-Native {
    param([scriptblock]$Command, [string]$FailureMessage)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code $LASTEXITCODE)"
    }
}

function Find-Python {
    $candidates = @(
        "python", "python3",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python312\python.exe", "C:\Python311\python.exe", "C:\Python310\python.exe"
    )
    foreach ($candidate in $candidates) {
        try {
            $raw = & $candidate --version 2>&1
            if ($raw -match "Python (\d+)\.(\d+)") {
                $version = [version]::new([int]$Matches[1], [int]$Matches[2])
                if ($version -ge [version]"3.10") { return $candidate }
            }
        } catch { }
    }
    return $null
}

function Has-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

Write-Host "POE Toolkit setup" -ForegroundColor Magenta
$pythonPath = Find-Python
$nodeOk = $false
if (Has-Command "node") {
    try {
        $nodeMajor = [int]((& node --version).TrimStart("v").Split(".")[0])
        $nodeOk = $nodeMajor -ge 18
    } catch { $nodeOk = $false }
}
$tesseractOk = Test-Path "C:\Program Files\Tesseract-OCR\tesseract.exe"
$braveOk = (Test-Path "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe") -or
           (Test-Path "$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\Application\brave.exe")

if (-not $SkipInstalls) {
    if (-not (Has-Command "winget") -and (-not $pythonPath -or -not $nodeOk -or -not $tesseractOk -or -not $braveOk)) {
        throw "winget is required to install missing prerequisites. Install them manually or rerun with -SkipInstalls."
    }
    if (-not $pythonPath) {
        Invoke-Native { winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements } "Python installation failed"
    }
    if (-not $nodeOk) {
        Invoke-Native { winget install OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements } "Node.js installation failed"
    }
    if (-not $tesseractOk) {
        Invoke-Native { winget install UB-Mannheim.TesseractOCR --silent --accept-package-agreements --accept-source-agreements } "Tesseract installation failed"
    }
    if (-not $braveOk) {
        Invoke-Native { winget install Brave.Brave --silent --accept-package-agreements --accept-source-agreements } "Brave installation failed"
    }

    $pythonPath = Find-Python
    if (-not $pythonPath -or -not (Has-Command "node") -or -not (Has-Command "npm")) {
        throw "A newly installed prerequisite is not visible on PATH. Restart PowerShell and rerun setup.ps1."
    }
}

$configBase = if ($env:APPDATA) { $env:APPDATA } elseif ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME "AppData\Roaming" }
$userConfigDir = Join-Path $configBase "poe-toolkit"
$userConfigPath = Join-Path $userConfigDir "user_config.json"
$templatePath = Join-Path $scriptDir "config\user_config.template.json"
New-Item -ItemType Directory -Path $userConfigDir -Force | Out-Null
$currentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls $userConfigDir /inheritance:r /grant:r "${currentIdentity}:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Warn "Could not restrict the config directory ACL automatically." }
if (-not (Test-Path $userConfigPath) -or $Force) {
    Copy-Item $templatePath $userConfigPath -Force
    Write-Success "Created private config: $userConfigPath"
} else {
    Write-Success "Preserved existing config: $userConfigPath"
}

if (-not $SkipInstalls) {
    $venvDir = Join-Path $scriptDir ".venv"
    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Invoke-Native { & $pythonPath -m venv $venvDir } "Virtual environment creation failed"
    }
    Invoke-Native { & $venvPython -m pip install --upgrade pip } "pip upgrade failed"
    Invoke-Native { & $venvPython -m pip install -e ".[full]" } "Python dependency installation failed"
    Push-Location (Join-Path $scriptDir "trade_service")
    try {
        Invoke-Native { npm ci } "Node dependency installation failed"
    } finally {
        Pop-Location
    }
    Write-Success "Dependencies installed"
} else {
    Write-Warn "Dependency installation skipped by request."
}

Write-Success "Setup complete"
Write-Host "Config: $userConfigPath"
Write-Host "Run: .\.venv\Scripts\python.exe src\main.py"
if (-not $NonInteractive -and $Host.Name -eq "ConsoleHost") {
    Write-Host "Press any key to exit..." -ForegroundColor DarkGray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
