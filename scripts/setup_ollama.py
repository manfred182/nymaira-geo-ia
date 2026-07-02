"""
Detecta/configura Ollama para usar modelos locales.
Nymaira funciona sin esto (usa transformers), pero con Ollama es más rápido.
"""
import subprocess
import sys
import platform
from pathlib import Path


def check_ollama() -> bool:
    try:
        r = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def install_ollama():
    system = platform.system()
    print(f"Sistema detectado: {system}")

    if system == "Darwin":
        print("Descarga Ollama desde: https://ollama.com/download")
        print("O con Homebrew: brew install ollama")
    elif system == "Linux":
        print("Instala con: curl -fsSL https://ollama.com/install.sh | sh")
    elif system == "Windows":
        print("Descarga Ollama desde: https://ollama.com/download")
        print("O con winget: winget install Ollama.Ollama")
    else:
        print("Sistema no soportado para instalación automática.")
        return

    print()
    print("Luego ejecuta:")
    print("  ollama pull qwen2.5:0.5b")
    print("  ollama serve")
    print()


def pull_model(model_name: str = "qwen2.5:0.5b"):
    if not check_ollama():
        print("Ollama no está instalado.")
        install_ollama()
        return False

    print(f"Descargando modelo {model_name}...")
    r = subprocess.run(["ollama", "pull", model_name])
    if r.returncode == 0:
        print(f"✓ Modelo {model_name} descargado")
        return True
    else:
        print(f"✗ Error descargando {model_name}")
        return False


if __name__ == "__main__":
    if check_ollama():
        print("✓ Ollama detectado")
        model = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:0.5b"
        pull_model(model)
    else:
        print("Ollama no instalado.")
        install_ollama()
