# Prepara el entorno de desarrollo de StemForge en Windows (x64).
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1           # detecta GPU NVIDIA
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Cpu      # fuerza CPU
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Cuda     # fuerza PyTorch con CUDA
#
# ffmpeg no hace falta: se usa el que trae el paquete imageio-ffmpeg.
param(
    [switch]$Cuda,
    [switch]$Cpu,
    [string]$CudaIndex = "https://download.pytorch.org/whl/cu132"
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Invoke-Native([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe terminó con código $LASTEXITCODE" }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "==> Instalando uv (https://astral.sh/uv)"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

$Py = ".venv\Scripts\python.exe"
Invoke-Native uv @("venv", "--python", "3.12", ".venv")
Invoke-Native uv @("pip", "install", "--python", $Py, "-e", ".[dev]")

$UseCuda = $Cuda -or (-not $Cpu -and (Get-Command nvidia-smi -ErrorAction SilentlyContinue))
if ($UseCuda) {
    Write-Host "==> PyTorch con CUDA (GPU NVIDIA)"
    Invoke-Native uv @("pip", "install", "--python", $Py, "--reinstall-package", "torch",
                       "--extra-index-url", $CudaIndex, "torch")
}
& $Py -c "import torch; print('PyTorch', torch.__version__, '| CUDA:', torch.cuda.is_available())"

Write-Host "✅ Listo. Abre StemForge con run.bat (o build_windows.ps1 para crear el instalador)"
