@echo off & title GEOIA & cd /d "%~dp0" || (echo [ERROR] Carpeta invalida & pause & exit /b 1)

REM === REDIRIGIR TODOS LOS CACHES A LA CARPETA PORTATIL ===
set "HF_HOME=%CD%\models\.cache\huggingface"
set "TORCH_HOME=%CD%\models\.cache\torch"
set "TRANSFORMERS_CACHE=%CD%\models\.cache\huggingface\transformers"
set "SENTENCE_TRANSFORMERS_HOME=%CD%\models\.cache\sentence-transformers"
set "XDG_CACHE_HOME=%CD%\models\.cache"
set "PADDLE_HOME=%CD%\models\.cache\paddle"
set "WHISPER_CACHE_DIR=%CD%\models\.cache\whisper"
set "GLINER_CACHE_DIR=%CD%\models\.cache\gliner"
set "MPLCONFIGDIR=%CD%\models\.cache\matplotlib"
if not exist "%CD%\models\.cache" mkdir "%CD%\models\.cache"

cls
echo ============================================
echo  GEOIA v0.1.0 - IA Catastral
echo  Iniciando...
echo ============================================
echo.
if not exist "venv\Scripts\python.exe" (echo Creando entorno virtual... & where py >nul 2>&1 && (py -m venv venv) || (python -m venv venv) || (echo [ERROR] Fallo venv & pause & exit /b 1) & echo [OK] Entorno virtual creado)
if not exist "venv\.deps_ok" (echo Instalando dependencias... & venv\Scripts\python.exe -m pip install --upgrade pip -q & venv\Scripts\python.exe -m pip install -e . --no-warn-script-location || (echo [ERROR] Fallo instalacion & pause & exit /b 1) & copy nul venv\.deps_ok >nul & echo [OK] Dependencias instaladas)
if not exist "models\huggingface\Qwen\Qwen2.5-0.5B-Instruct\model.safetensors" (echo Descargando modelos... & venv\Scripts\python scripts\download_models.py & echo [OK] Modelos listos)
echo.
taskkill /f /im python.exe 2>nul 1>nul
if not exist "data\logs" mkdir data\logs >nul
powershell -WindowStyle Hidden -Command "Start-Process -FilePath 'venv\Scripts\python.exe' -ArgumentList '-m uvicorn geoia.api.main:app --host 127.0.0.1 --port 8000' -WindowStyle Hidden -RedirectStandardOutput 'data\logs\server.log' -RedirectStandardError 'data\logs\server.err' -WorkingDirectory '%CD%'"
echo Esperando servidor...
setlocal enabledelayedexpansion
for /l %%i in (1,1,40) do (
    >nul 2>&1 powershell -Command "try{$r=Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 1; if($r.StatusCode -eq 200){exit 0}}catch{}; exit 1"
    if !errorlevel! equ 0 goto SERVER_UP
    timeout /t 1 /nobreak >nul
)
:SERVER_UP
endlocal
echo.
echo ============================================
echo  GEOIA LISTO
echo ============================================
echo.
start "" http://127.0.0.1:8000
exit