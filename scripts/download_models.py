import sys
from pathlib import Path

root = Path(__file__).parent.parent
sys.path.insert(0, str(root))

from geoia.core.config import settings
from geoia.core.models import setup_hf_env


def download_all():
    setup_hf_env()
    print("=" * 60)
    print("  Nymaira - Descarga de Modelos Portables")
    print("=" * 60)
    print(f"\nLos modelos se guardaran en: {settings.models_dir}")
    print()

    _download_sentence_transformer()
    _download_vit()
    _download_llm()

    from geoia.core.models import get_model_status
    print("\n" + "=" * 60)
    print("  ESTADO FINAL DE MODELOS")
    print("=" * 60)
    status = get_model_status()
    for name, info in status.items():
        if isinstance(info, dict):
            ok = "[OK]" if info.get("disponible") else "[--]"
            print(f"  {ok} {name}: {info.get('ruta', info.get('archivos', ''))}")
    print(f"\n  Tamano total modelos: {status.get('models_dir_size_mb', 0)} MB")
    print()


def _download_sentence_transformer():
    print("[1/3] Sentence Transformer para embeddings...")
    try:
        from sentence_transformers import SentenceTransformer
        model_name = settings.embedding_model
        save_path = str(settings.embedding_model_path)

        if settings.embedding_model_path.exists():
            print(f"  [OK] Ya descargado en {save_path}")
            return

        print(f"  Descargando {model_name}...")
        model = SentenceTransformer(model_name)
        model.save(save_path)
        print(f"  [OK] Guardado en {save_path}")
    except Exception as e:
        print(f"  [--] Error: {e}")


def _download_vit():
    print("[2/3] Vision Transformer (ViT) para clasificacion...")
    try:
        from transformers import pipeline
        model_name = settings.vit_model_name
        save_path = str(settings.vit_model_path)

        if settings.vit_model_path.exists():
            print(f"  [OK] Ya descargado en {save_path}")
            return

        print(f"  Descargando {model_name}...")
        model = pipeline("image-classification", model=model_name)
        model.save_pretrained(save_path)
        print(f"  [OK] Guardado en {save_path}")
    except Exception as e:
        print(f"  [--] Error: {e}")


def _download_llm():
    print("[3/3] Qwen2.5-0.5B-Instruct (LLM local)...")
    try:
        model_name = settings.local_llm_model_name
        save_path = settings.local_llm_model_path

        has_weights = save_path.exists() and len(list(save_path.rglob("model.safetensors"))) > 0
        if has_weights:
            print(f"  [OK] Ya descargado en {save_path}")
            return

        print(f"  Descargando {model_name} (~1GB)...")
        print("  Esto puede tomar varios minutos...")
        from huggingface_hub import snapshot_download
        snapshot_download(
            model_name,
            local_dir=str(save_path),
            local_dir_use_symlinks=False,
        )
        print(f"  [OK] Guardado en {save_path}")
    except Exception as e:
        print(f"  [--] Error: {e}")


if __name__ == "__main__":
    download_all()
