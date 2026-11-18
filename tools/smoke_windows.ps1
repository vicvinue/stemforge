# Prueba de humo de una StemForge empaquetada para Windows (carpeta portable o ya instalada):
# separa 8 s de audio sintético con Demucs (CPU) y abre el servidor para consultar /api/info.
#
#   powershell -ExecutionPolicy Bypass -File tools\smoke_windows.ps1 [-AppDir dist\StemForge]
param([string]$AppDir = (Join-Path $PSScriptRoot "..\dist\StemForge"))
$ErrorActionPreference = "Stop"
$AppDir = (Resolve-Path $AppDir).Path
$Py = Join-Path $AppDir "python\python.exe"
$Work = Join-Path ([IO.Path]::GetTempPath()) ("stemforge-smoke-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $Work | Out-Null

function Invoke-Native([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe terminó con código $LASTEXITCODE" }
}

Write-Host "==> Audio de prueba"
$Song = Join-Path $Work "Canción de prueba.wav"   # nombre con tilde y espacios a propósito
Invoke-Native $Py @("-I", "-B", "-X", "utf8", "-c", @"
import sys, numpy as np, soundfile as sf
sr = 44100; t = np.arange(sr * 8) / sr
kick = np.sin(2 * np.pi * 55 * t) * np.exp(-(t % 0.5) * 18)
bass = 0.3 * np.sign(np.sin(2 * np.pi * 82.4 * t))
voice = 0.2 * np.sin(2 * np.pi * (440 + 30 * np.sin(2 * np.pi * 5 * t)) * t)
y = (0.4 * kick + 0.3 * bass + voice).astype(np.float32)
sf.write(sys.argv[1], np.stack([y, y], 1), sr)
"@, $Song)

Write-Host "==> CLI: separación stems4_fast (descarga Demucs la primera vez)"
$Out = Join-Path $Work "salida"
Invoke-Native (Join-Path $AppDir "stemforge.cmd") @("--info")
Invoke-Native (Join-Path $AppDir "stemforge.cmd") @($Song, "-m", "stems4_fast", "-f", "flac", "-o", $Out)
$Files = Get-ChildItem $Out -Recurse -File -Filter *.flac
$Files | ForEach-Object { Write-Host ("    {0}  {1:N0} KB" -f $_.Name, ($_.Length / 1KB)) }
if ($Files.Count -lt 4) { throw "Se esperaban al menos 4 stems FLAC y hay $($Files.Count)" }
if (-not (Get-ChildItem $Out -Recurse -File -Filter stemforge.json)) { throw "Falta stemforge.json" }

Write-Host "==> Servidor: /api/info"
$Port = 8765
$Proc = Start-Process -FilePath $Py -ArgumentList @("-I", "-B", "-X", "utf8", "-m", "stemforge.app", "--browser", "--port", "$Port") `
    -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Work "app.out") -RedirectStandardError (Join-Path $Work "app.err")
try {
    $Html = $null
    for ($i = 0; $i -lt 60 -and -not $Html; $i++) {
        Start-Sleep -Milliseconds 500
        try { $Html = (Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing).Content } catch { }
    }
    if (-not $Html) { Get-Content (Join-Path $Work "app.err") -ErrorAction SilentlyContinue; throw "El servidor no respondió" }
    $Token = [regex]::Match($Html, 'TOKEN\s*=\s*"([^"]+)"').Groups[1].Value
    if (-not $Token) { throw "No se encontró el token en la página" }
    $Info = Invoke-RestMethod "http://127.0.0.1:$Port/api/info" -Headers @{ "x-stemforge-token" = $Token }
    Write-Host "    sistema: $($Info.device.system) · CUDA: $($Info.device.cuda) · salida: $($Info.settings.output_dir)"
    if ($Info.device.system -ne "Windows") { throw "device.system = $($Info.device.system)" }
} finally {
    Stop-Process -Id $Proc.Id -Force -ErrorAction SilentlyContinue
}

Remove-Item $Work -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "✅ Prueba de humo superada"
