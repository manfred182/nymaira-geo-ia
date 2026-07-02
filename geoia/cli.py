from __future__ import annotations
"""
Nymaira CLI - Interfaz de línea de comandos multiplataforma
Funciona en Mac, Linux y Windows.
"""
import argparse
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


ROOT = Path(__file__).parent.parent


def _detect_python():
    for cmd in ["python3", "python"]:
        try:
            r = subprocess.run([cmd, "--version"], capture_output=True, text=True)
            if r.returncode == 0:
                return cmd
        except FileNotFoundError:
            continue
    return None


def _get_venv_python():
    if sys.platform == "win32":
        venv_python = ROOT / "venv" / "Scripts" / "python.exe"
    else:
        venv_python = ROOT / "venv" / "bin" / "python"
    return venv_python if venv_python.exists() else None


def _activate_venv_cmd():
    if sys.platform == "win32":
        activate = ROOT / "venv" / "Scripts" / "activate.bat"
        return f'call "{activate}"'
    else:
        activate = ROOT / "venv" / "bin" / "activate"
        return f'source "{activate}"'


def _set_model_env():
    models_dir = ROOT / "models"
    os.environ.setdefault("HF_HOME", str(models_dir / "huggingface"))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(models_dir / "huggingface" / "transformers"))
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(models_dir / "sentence-transformers"))
    os.environ.setdefault("TORCH_HOME", str(models_dir / "torch"))
    os.environ.setdefault("XDG_CACHE_HOME", str(models_dir / ".cache"))


def _ensure_dirs():
    dirs = [
        ROOT / "models" / "huggingface",
        ROOT / "data" / "documents",
        ROOT / "data" / "rasters",
        ROOT / "data" / "vectors",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def cmd_setup(args):
    """Crea entorno virtual e instala dependencias."""
    print("=" * 60)
    print("  Nymaira - Configuración del Entorno")
    print("=" * 60)

    python_cmd = _detect_python()
    if not python_cmd:
        print("\n  [ERROR] Python no encontrado.")
        print("  Descarga Python 3.11+ desde: https://www.python.org/downloads/")
        sys.exit(1)

    r = subprocess.run([python_cmd, "--version"], capture_output=True, text=True)
    print(f"\n  [OK] {r.stdout.strip()} detectado")

    _ensure_dirs()

    # Crear venv
    venv_dir = ROOT / "venv"
    if not venv_dir.exists():
        print("\n  [..] Creando entorno virtual...")
        subprocess.run([python_cmd, "-m", "venv", str(venv_dir)], check=True)
        print("  [OK] Entorno virtual creado")
    else:
        print("\n  [OK] Entorno virtual ya existe")

    # Actualizar pip e instalar
    venv_python = _get_venv_python() or python_cmd
    print("\n  [..] Actualizando pip...")
    subprocess.run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip", "-q"])

    print("\n  [..] Instalando dependencias (puede tomar varios minutos)...")
    extra = ".[dev]" if args.dev else "."
    subprocess.run([str(venv_python), "-m", "pip", "install", "-e", extra, "--no-warn-script-location"])

    print("\n" + "=" * 60)
    print("  INSTALACIÓN COMPLETADA")
    print("=" * 60)
    print(f"\n  Para iniciar:  python -m geoia.cli run")
    print(f"  O también:     {ROOT / 'run.sh'}  (Mac/Linux)")
    print(f"                 {ROOT / 'run.bat'}  (Windows)\n")


def _open_browser(url):
    """Abre el navegador usando múltiples métodos."""
    try:
        webbrowser.open(url)
        return True
    except Exception:
        pass
    for cmd in [
        ["open", url],
        ["xdg-open", url],
        ["python3", "-c", f"import webbrowser; webbrowser.open('{url}')"],
    ]:
        try:
            subprocess.run(cmd, capture_output=True, timeout=5)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return False


def _wait_for_server(url, timeout=60):
    """Espera a que el servidor responda en la URL dada."""
    import urllib.request
    import urllib.error
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = urllib.request.urlopen(url, timeout=2)
            if r.status == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def cmd_run(args):
    """Inicia el servidor Nymaira."""
    os.chdir(ROOT)
    _set_model_env()
    _ensure_dirs()

    venv_python = _get_venv_python()
    if not venv_python:
        print("[ERROR] No hay entorno virtual. Ejecuta: python -m geoia.cli setup")
        sys.exit(1)

    host = args.host
    port = args.port
    url = f"http://localhost:{port}"

    print("=" * 60)
    print("  Nymaira v0.1.0 - IA Catastral y Geoespacial")
    print("=" * 60)
    print(f"\n  Iniciando servidor en {url}")

    # Iniciar uvicorn en segundo plano
    log_dir = ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(log_dir / "server.log", "w")

    cmd = [
        str(venv_python), "-m", "uvicorn",
        "geoia.api.main:app",
        "--host", host,
        "--port", str(port),
    ]
    if args.debug or args.reload:
        cmd.append("--reload")

    server_proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)

    try:
        # Esperar a que el servidor esté listo
        print("  Esperando servidor...")
        ready = _wait_for_server(url + "/health", timeout=60)

        if ready:
            print("  [OK] Servidor listo")
        else:
            print("  Servidor iniciado (puede tardar unos segundos más)")

        print(f"\n  Interfaz:  {url}")
        print(f"  API Docs:  {url}/docs")
        print(f"  Log:       data/logs/server.log")
        print()

        # Abrir navegador
        if not args.no_browser:
            print("  Abriendo navegador...")
            _open_browser(url)

        print("  Presiona ENTER para detener el servidor")
        input()

    except KeyboardInterrupt:
        pass
    finally:
        server_proc.terminate()
        server_proc.wait()
        log_file.close()
        print("\n  Servidor detenido.")


def cmd_download_models(args):
    """Descarga los modelos de IA localmente."""
    os.chdir(ROOT)
    _set_model_env()
    _ensure_dirs()

    venv_python = _get_venv_python()
    if not venv_python:
        print("[ERROR] No hay entorno virtual. Ejecuta: python -m geoia.cli setup")
        sys.exit(1)

    subprocess.run([str(venv_python), str(ROOT / "scripts" / "download_models.py")])


def cmd_status(args):
    """Muestra el estado de modelos y configuración."""
    os.chdir(ROOT)
    _set_model_env()

    from geoia.core.config import settings
    from geoia.core.models import get_model_status, setup_hf_env

    setup_hf_env()

    print("=" * 60)
    print("  Nymaira - Estado del Sistema")
    print("=" * 60)
    print(f"\n  Versión:   {settings.app_name} v0.1.0")
    print(f"  Debug:     {settings.debug}")
    print(f"  Raíz:      {settings.project_root}")
    print(f"\n  --- Directorios ---")
    print(f"  Modelos:   {settings.models_dir}")
    print(f"  Datos:     {settings.data_dir}")
    print(f"  Vectores:  {settings.vector_db_path}")

    if settings.openai_api_key and settings.openai_api_key != "tu-api-key-aqui":
        print(f"\n  OpenAI:    {settings.openai_model} (configurado)")
    else:
        print(f"\n  OpenAI:    No configurado (opcional con modelos locales)")

    # Estado de modelos locales
    print(f"\n  --- Modelos Locales ---")
    status = get_model_status()
    for name, info in status.items():
        if isinstance(info, dict):
            ok = "[OK]" if info.get("disponible") else "[--]"
            extra = f" ({info.get('archivos', '')} archivos)" if info.get("archivos") else ""
            print(f"  {ok} {name}: {info.get('ruta', info.get('archivos', ''))}{extra}")

    print()

    # Detectar entorno virtual
    venv_python = _get_venv_python()
    print(f"  Venv:      {'[OK] disponible' if venv_python else '[--] no creado'}")

    # Listar modelos LLM disponibles
    print(f"\n  --- Modelos de Lenguaje (LLM) ---")
    from geoia.core.llm import _scan_local_models, _check_ollama
    local = _scan_local_models()
    if local:
        for m in local:
            print(f"  [OK] {m['name']}  ({m['size_mb']} MB, {m['format']})")
    else:
        print(f"  - Vacio. Pon archivos .gguf en: {settings.llm_models_dir}")
    ollama = _check_ollama()
    if ollama:
        print(f"  [OK] Ollama disponible en {ollama}")
    else:
        print(f"  - Ollama no detectado (opcional, mas rapido)")
    print()


def cmd_list_models(args):
    """Lista modelos LLM disponibles localmente."""
    from geoia.core.llm import _scan_local_models, _check_ollama

    print("=" * 60)
    print("  Nymaira - Modelos Disponibles")
    print("=" * 60)

    local = _scan_local_models()
    print(f"\n  --- Modelos Locales (models/llm/) ---")
    if local:
        for m in local:
            print(f"  [{m['format']}] {m['name']}")
            print(f"         Ruta: {m['path']}")
            print(f"         Tamaño: {m['size_mb']} MB")
            print()
    else:
        print("  (vacío)")
        print(f"  Pon archivos .gguf en: {settings.llm_models_dir}")
        print()

    ollama_url = _check_ollama()
    if ollama_url:
        try:
            import requests
            r = requests.get(f"{ollama_url}/api/tags", timeout=5)
            if r.status_code == 200:
                models = r.json().get("models", [])
                print(f"  --- Ollama ({len(models)} modelos) ---")
                for m in models:
                    size = m.get("size", 0)
                    size_str = f"{round(size / 1e9, 1)}GB" if size > 1e9 else f"{round(size / 1e6, 1)}MB"
                    print(f"  [OK] {m['name']}  ({size_str})")
        except Exception:
            print("  --- Ollama detectado (no se pudieron listar modelos) ---")
    else:
        print("  --- Ollama ---")
        print("  No detectado. Opcional — instálalo para más velocidad.")
        print()

    print(f"  Para usar un modelo, configúralo en .env:")
    print(f"  LLM_MODEL=nombre-del-modelo")
    print(f"  O simplemente pon un .gguf en {settings.llm_models_dir}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Nymaira - IA para procesos catastrales y geoespaciales",
    )
    subparsers = parser.add_subparsers(dest="command", title="Comandos")

    # setup
    p = subparsers.add_parser("setup", help="Configurar entorno virtual e instalar dependencias")
    p.add_argument("--dev", action="store_true", help="Incluir dependencias de desarrollo")
    p.set_defaults(func=cmd_setup)

    # run
    p = subparsers.add_parser("run", help="Iniciar el servidor web")
    p.add_argument("--host", default="0.0.0.0", help="Host del servidor")
    p.add_argument("--port", type=int, default=8000, help="Puerto del servidor")
    p.add_argument("--no-browser", action="store_true", help="No abrir navegador")
    p.add_argument("--debug", action="store_true", help="Modo debug (recarga automática)")
    p.add_argument("--reload", action="store_true", help="Recarga automática al cambiar código")
    p.set_defaults(func=cmd_run)

    # download-models
    p = subparsers.add_parser("download-models", help="Descargar modelos de IA localmente")
    p.set_defaults(func=cmd_download_models)

    # status
    p = subparsers.add_parser("status", help="Mostrar estado del sistema y modelos")
    p.set_defaults(func=cmd_status)

    # list-models
    p = subparsers.add_parser("list-models", help="Listar modelos LLM disponibles localmente")
    p.set_defaults(func=cmd_list_models)

    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
