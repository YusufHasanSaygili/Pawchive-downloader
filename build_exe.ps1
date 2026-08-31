$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

$arguments = @(
  '--noconfirm',
  '--clean',
  '--onefile',
  '--windowed',
  '--name', 'Pawchive Downloader',
  '--exclude-module', 'numpy',
  '--exclude-module', 'PIL',
  '--exclude-module', 'pydantic',
  '--exclude-module', 'psutil',
  '--exclude-module', 'setuptools',
  '--paths', "$projectRoot\src",
  '--distpath', $projectRoot,
  '--workpath', "$projectRoot\build\pyinstaller",
  '--specpath', "$projectRoot\build",
  "$projectRoot\pawchive_exe.py"
)

$localTools = Join-Path $projectRoot '.build-tools'
if (Test-Path -LiteralPath "$localTools\PyInstaller") {
  python -c "import sys; sys.path.insert(0, sys.argv[1]); from PyInstaller.__main__ import run; run(sys.argv[2:])" $localTools @arguments
} else {
  python -m PyInstaller @arguments
}
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$exePath = Join-Path $projectRoot 'Pawchive Downloader.exe'
if (-not (Test-Path -LiteralPath $exePath)) {
  throw "Build finished without creating $exePath"
}
Write-Host "EXE ready: $exePath"
