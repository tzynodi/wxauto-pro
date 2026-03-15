# wxauto-pro 启动脚本 (PowerShell)
# 用法: .\run.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

# 控制台 UTF-8，避免中文乱码
chcp 65001 | Out-Null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# 自动安装依赖（已安装则跳过）
if (Test-Path "requirements.txt") {
    Write-Host "Checking dependencies..." -ForegroundColor Gray
    pip install -r requirements.txt -q 2>$null
    if ($LASTEXITCODE -ne 0) {
        pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Dependency install failed. Run: pip install -r requirements.txt" -ForegroundColor Red
            exit 1
        }
    }
}

Write-Host "Starting wxauto-pro message listener..." -ForegroundColor Cyan
& python main.py
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Startup failed. Check: Python in PATH, pip install -r requirements.txt, WeChat logged in." -ForegroundColor Yellow
    exit 1
}
