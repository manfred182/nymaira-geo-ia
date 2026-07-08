from __future__ import annotations
import os
from geoia.core.config import settings


def setup_hf_env():
    """Configura variables de entorno para usar modelos locales."""
    os.environ["HF_HOME"] = str(settings.hf_cache_dir)
    os.environ["HF_HUB_CACHE"] = str(settings.hf_cache_dir / "hub")
    os.environ["TRANSFORMERS_CACHE"] = str(settings.hf_cache_dir / "transformers")
    os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(settings.models_dir / "sentence-transformers")
    os.environ["TORCH_HOME"] = str(settings.models_dir / "torch")
    os.environ["XDG_CACHE_HOME"] = str(settings.models_dir / ".cache")

    for d in [settings.hf_cache_dir, settings.models_dir]:
        d.mkdir(parents=True, exist_ok=True)


def get_model_status() -> dict:
    """Reporta qué modelos están disponibles localmente."""
    from pathlib import Path

    status = {}

    embedding_path = settings.embedding_model_path
    vit_path = settings.vit_model_path
    llm_path = settings.local_llm_model_path

    # Verificar sentence-transformers
    if embedding_path.exists():
        n_files = len(list(embedding_path.rglob("*")))
        status["sentence_transformer"] = {
            "disponible": True,
            "ruta": str(embedding_path),
            "archivos": n_files,
        }
    else:
        status["sentence_transformer"] = {
            "disponible": False,
            "ruta": str(embedding_path),
        }

    # Verificar ViT
    if vit_path.exists():
        n_files = len(list(vit_path.rglob("*")))
        status["vit_classifier"] = {
            "disponible": True,
            "ruta": str(vit_path),
            "archivos": n_files,
        }
    else:
        status["vit_classifier"] = {
            "disponible": False,
            "ruta": str(vit_path),
        }

    # Verificar LLM local
    if llm_path.exists():
        n_files = len(list(llm_path.rglob("*")))
        status["llm_local"] = {
            "disponible": True,
            "ruta": str(llm_path),
            "archivos": n_files,
        }
    else:
        status["llm_local"] = {
            "disponible": False,
            "ruta": str(llm_path),
        }

    # Verificar FAISS (vector DB)
    import faiss as _faiss
    faiss_path = settings.data_dir / "faiss_db" / "index.faiss"
    if faiss_path.exists():
        try:
            idx = _faiss.read_index(str(faiss_path))
            n_vectors = idx.ntotal
            status["vectordb"] = {
                "disponible": True,
                "motor": "FAISS",
                "vectores": n_vectors,
            }
        except Exception:
            status["vectordb"] = {"disponible": True, "motor": "FAISS"}
    else:
        status["vectordb"] = {"disponible": False}

    status["models_dir_size_mb"] = _dir_size_mb(settings.models_dir)

    return status


def _dir_size_mb(path) -> float:
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except Exception:
        pass
    return round(total / (1024 * 1024), 2)
