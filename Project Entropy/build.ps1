param(
    [string]$Python = 'python',
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9 -]*$')]
    [string]$Name = 'Project Entropy Studio v3'
)

$ErrorActionPreference = 'Stop'
$buildPath = Join-Path $PSScriptRoot '.entropy-build'
$tempPath = Join-Path $buildPath 'tmp'
New-Item -ItemType Directory -Path $buildPath, $tempPath -Force | Out-Null

$previousTemp = $env:TEMP
$previousTmp = $env:TMP
$previousConfig = $env:PYINSTALLER_CONFIG_DIR
$previousBytecode = $env:PYTHONDONTWRITEBYTECODE
Push-Location -LiteralPath $PSScriptRoot
try {
    $env:TEMP = $tempPath
    $env:TMP = $tempPath
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $buildPath 'cache'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    & $Python -m PyInstaller --noconfirm --onefile --windowed --log-level WARN `
        --name $Name --distpath (Join-Path $PSScriptRoot 'dist') `
        --workpath $buildPath --specpath $buildPath entropy_app.py
    if ($LASTEXITCODE -ne 0) { throw 'Entropy executable build failed.' }
    Get-Item -LiteralPath (Join-Path (Join-Path $PSScriptRoot 'dist') ($Name + '.exe'))
}
finally {
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
    $env:PYINSTALLER_CONFIG_DIR = $previousConfig
    $env:PYTHONDONTWRITEBYTECODE = $previousBytecode
    Pop-Location
}
