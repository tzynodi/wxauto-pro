param(
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

try {
    python -c "import PyInstaller" | Out-Null
} catch {
    Write-Host "PyInstaller 未安装，请先执行: python -m pip install pyinstaller" -ForegroundColor Yellow
    exit 1
}

$specFile = if ($OneFile) { "wxauto-pro-onefile.spec" } else { "wxauto-pro.spec" }

Write-Host "开始打包: $specFile" -ForegroundColor Cyan
python -m PyInstaller --clean -y $specFile

Write-Host "打包完成，输出目录: dist" -ForegroundColor Green
