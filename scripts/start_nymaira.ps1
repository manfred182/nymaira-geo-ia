#Requires -Version 5.1
<#
.SYNOPSIS
  Arranque confiable de Nymaira.
.DESCRIPTION
  1. Fija OLLAMA_MODELS a una ruta SIN acento (D:\ollama-models) — la app de bandeja
     de Ollama corrompe rutas con `´`, por eso solo veía el modelo 7b.
  2. Verifica que el daemon de Ollama exponga el modelo del chat (qwen2.5:1.5b);
     si no, lo reinicia con la configuración correcta (auto-reparación).
  3. Arranca el servidor de Nymaira en http://127.0.0.1:8602
  Ejecutar:  .\scripts\start_nymaira.ps1
#>
$ErrorActionPreference = "Stop"

$OllamaModels = "D:\Ollama Models"          # carpeta del usuario (sin acento; el espacio no da problema)
$ModeloChat   = "qwen2.5:1.5b"
$Puerto       = 8602
$ProyectoDir  = Split-Path -Parent $PSScriptRoot
$OllamaExe    = "$env:USERPROFILE\AppData\Local\Programs\Ollama\ollama.exe"

# ── 1. Variables de entorno (persistentes + sesión actual) ────────────
[Environment]::SetEnvironmentVariable('OLLAMA_MODELS', $OllamaModels, 'User')
[Environment]::SetEnvironmentVariable('OLLAMA_MAX_LOADED_MODELS', '1', 'User')  # RAM justa: 1 modelo a la vez
$env:OLLAMA_MODELS = $OllamaModels
$env:OLLAMA_MAX_LOADED_MODELS = '1'

function Get-OllamaModelos {
    try { return (Invoke-RestMethod "http://localhost:11434/api/tags" -TimeoutSec 3).models.name }
    catch { return @() }
}

# ── 2. Verificar/auto-reparar el daemon de Ollama ─────────────────────
$modelos = Get-OllamaModelos
if ($modelos -notcontains $ModeloChat) {
    Write-Host "Ollama no expone $ModeloChat (ve: $($modelos -join ', ')). Reiniciando daemon..." -ForegroundColor Yellow
    Get-Process ollama, 'ollama app' -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep 2
    Start-Process $OllamaExe serve -WindowStyle Hidden
    Start-Sleep 5
    $modelos = Get-OllamaModelos
}
if ($modelos -contains $ModeloChat) {
    Write-Host "OK - Ollama expone: $($modelos -join ', ')" -ForegroundColor Green
} else {
    Write-Host "ADVERTENCIA - Ollama sigue sin ver $ModeloChat. Revisa la instalacion." -ForegroundColor Red
}

# ── 3. Arrancar Nymaira ───────────────────────────────────────────────
Set-Location $ProyectoDir
$py = Join-Path $ProyectoDir "venv\Scripts\python.exe"
Write-Host "Arrancando Nymaira en http://127.0.0.1:$Puerto ..." -ForegroundColor Cyan
Write-Host "(Abre http://127.0.0.1:$Puerto en el navegador. Ctrl+C para detener.)" -ForegroundColor DarkGray
# uvicorn escribe sus logs por stderr; en PowerShell 5.1 eso dispara NativeCommandError
# y con ErrorActionPreference='Stop' mataría el servidor. Se baja a 'Continue' aquí.
$ErrorActionPreference = "Continue"
& $py -m uvicorn geoia.api.main:app --host 127.0.0.1 --port $Puerto
