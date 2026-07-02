"""Redirige todos los caches de modelos AI a la carpeta portable models/.cache/."""

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_CACHE_DIR = _PROJECT_ROOT / "models" / ".cache"

_CACHE_MAP = {
    "HF_HOME": _CACHE_DIR / "huggingface",
    "TORCH_HOME": _CACHE_DIR / "torch",
    "TRANSFORMERS_CACHE": _CACHE_DIR / "huggingface" / "transformers",
    "SENTENCE_TRANSFORMERS_HOME": _CACHE_DIR / "sentence-transformers",
    "XDG_CACHE_HOME": _CACHE_DIR,
    "PADDLE_HOME": _CACHE_DIR / "paddle",
    "WHISPER_CACHE_DIR": _CACHE_DIR / "whisper",
    "GLINER_CACHE_DIR": _CACHE_DIR / "gliner",
    "MPLCONFIGDIR": _CACHE_DIR / "matplotlib",
}

for var, path in _CACHE_MAP.items():
    if var not in os.environ:
        path.mkdir(parents=True, exist_ok=True)
        os.environ[var] = str(path)
