$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

$arguments = @(
  '--noconfirm',
  '--clean',
  '--onefile',
  '--windowed',
  '--name', 'Pawchy Downloader',
  '--paths', "$projectRoot\src",
  '--distpath', $projectRoot,
  '--workpath', "$projectRoot\build\pyinstaller",
  '--specpath', "$projectRoot\build",
  "$projectRoot\pawchy_exe.py"
)

$localTools = Join-Path $projectRoot '.build-tools'
if (Test-Path -LiteralPath "$localTools\PyInstaller") {
  python -c "import sys; sys.path.insert(0, sys.argv[1]); from PyInstaller.__main__ import run; run(sys.argv[2:])" $localTools @arguments
} else {
  python -m PyInstaller @arguments
}

Write-Host "EXE hazır: $projectRoot\Pawchy Downloader.exe"
