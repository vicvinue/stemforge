# Empaqueta StemForge como app autónoma para Windows x64:
#   dist\StemForge\                    Python + dependencias + ffmpeg incluidos (carpeta portable)
#   dist\StemForge-<versión>-Setup.exe instalador (si Inno Setup 6 está instalado)
#
# La app no depende de esta carpeta ni de un Python del sistema. Los modelos NO se incluyen:
# se descargan solos la primera vez en %LOCALAPPDATA%\StemForge\models.
#
#   powershell -ExecutionPolicy Bypass -File build_windows.ps1            # PyTorch CPU (≈ 0,6 GB)
#   powershell -ExecutionPolicy Bypass -File build_windows.ps1 -Cuda      # PyTorch CUDA (≈ 3 GB)
#   ... -NoInstaller                                                     # solo la carpeta
#
# Requisitos: uv (https://astral.sh/uv) e Inno Setup 6 (https://jrsoftware.org) para el instalador.
param(
    [switch]$Cuda,
    [string]$CudaIndex = "https://download.pytorch.org/whl/cu128",
    [switch]$NoInstaller
)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

function Invoke-Native([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe terminó con código $LASTEXITCODE" }
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "Falta uv: https://astral.sh/uv" }

$PyVer = "3.12"
$Version = (Select-String -Path pyproject.toml -Pattern '^version = "(.*)"').Matches[0].Groups[1].Value
$Dist = Join-Path $Root "dist"
$App = Join-Path $Dist "StemForge"
$Py = Join-Path $App "python"
$PyExe = Join-Path $Py "python.exe"

Write-Host "==> StemForge $Version ($(if ($Cuda) {'CUDA'} else {'CPU'}))"
if (Test-Path $App) { Remove-Item $App -Recurse -Force }
New-Item -ItemType Directory -Path $App | Out-Null

Write-Host "==> Python $PyVer portable (python-build-standalone vía uv)"
Invoke-Native uv @("python", "install", $PyVer)
$SrcPy = (& uv python find --managed-python $PyVer | Select-Object -First 1).Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $SrcPy)) { throw "No se encontró el Python $PyVer de uv" }
Copy-Item (Split-Path $SrcPy -Parent) $Py -Recurse
Remove-Item (Join-Path $Py "Lib\EXTERNALLY-MANAGED") -Force -ErrorAction SilentlyContinue
foreach ($d in "Lib\test", "Lib\idlelib", "Lib\tkinter", "Lib\turtledemo", "tcl", "include", "libs", "Scripts") {
    Remove-Item (Join-Path $Py $d) -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "==> Dependencias"
Invoke-Native uv @("pip", "install", "--python", $PyExe, "--no-cache", $Root)
if ($Cuda) {
    Write-Host "==> PyTorch con CUDA"
    Invoke-Native uv @("pip", "install", "--python", $PyExe, "--no-cache", "--reinstall-package", "torch",
                       "--extra-index-url", $CudaIndex, "torch")
}

Write-Host "==> Limpieza"
$Site = Join-Path $Py "Lib\site-packages"
foreach ($d in "torch\include", "torch\share\cmake") {
    Remove-Item (Join-Path $Site $d) -Recurse -Force -ErrorAction SilentlyContinue
}
# .lib/.pdb solo sirven para compilar o depurar. Scripts\ tiene .exe con la ruta del build.
Get-ChildItem $Py -Recurse -File -Include *.pdb, *.lib | Remove-Item -Force
Remove-Item (Join-Path $Py "Scripts") -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $Site -Directory -Filter "stemforge-*.dist-info" |
    ForEach-Object { Remove-Item (Join-Path $_.FullName "direct_url.json") -Force -ErrorAction SilentlyContinue }

Write-Host "==> Bytecode"
Get-ChildItem $Py -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
& $PyExe -I -B -X utf8 -m compileall -q -f -j 0 --invalidation-mode unchecked-hash (Join-Path $Py "Lib") *> $null

Write-Host "==> Comprobación"
Invoke-Native $PyExe @("-I", "-B", "-X", "utf8", "-c",
    "import torch, webview, clr, audio_separator.separator, imageio_ffmpeg, stemforge.server; " +
    "print('    torch', torch.__version__, '| CUDA:', torch.cuda.is_available())")

Write-Host "==> Lanzadores"
Copy-Item (Join-Path $Root "stemforge\web\StemForge.ico") (Join-Path $App "StemForge.ico")
Set-Content -Path (Join-Path $App "Abrir StemForge.cmd") -Encoding ASCII -Value @(
    "@echo off",
    "rem Abre StemForge sin instalar (carpeta portable).",
    'start "" "%~dp0python\pythonw.exe" -I -B -X utf8 -m stemforge.app %*'
)
Set-Content -Path (Join-Path $App "stemforge.cmd") -Encoding ASCII -Value @(
    "@echo off",
    "rem CLI: stemforge.cmd cancion.mp3 -m stems4",
    '"%~dp0python\python.exe" -I -B -X utf8 -m stemforge %*'
)
Copy-Item (Join-Path $Root "LICENSE") (Join-Path $App "LICENSE.txt")

$Size = (Get-ChildItem $App -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
Write-Host ("==> Tamaño: {0:N2} GB" -f $Size)

if ($NoInstaller) { Write-Host "✅ Listo: $App"; exit 0 }

$Iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $Iscc) {
    $Iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
              "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Iscc) {
    Write-Warning "Inno Setup 6 no está instalado: solo se creó la carpeta $App (winget install JRSoftware.InnoSetup)"
    exit 0
}
Write-Host "==> Instalador"
$IsccArgs = @("/Q", "/DAppVersion=$Version", "/DSourceDir=$App", "/DOutputDir=$Dist")
if ($Cuda) { $IsccArgs += "/DCuda=1" }
Invoke-Native $Iscc ($IsccArgs + (Join-Path $Root "installer\StemForge.iss"))
Write-Host "✅ Listo: $Dist\StemForge-$Version-Setup.exe"
