"""Ingesta el PDF de la Resolución 1040 en ChromaDB."""
import sys, time, gc, logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from geoia.rag.engine import RAGEngine
from geoia.core.config import settings

pdf_path = settings.data_dir / "documents" / "resolucion_1040_de_2023.pdf"
if not pdf_path.exists():
    print(f"ERROR: PDF no encontrado en {pdf_path}")
    sys.exit(1)

size_mb = pdf_path.stat().st_size / (1024 * 1024)
print(f"Ingestando {pdf_path.name} ({size_mb:.1f} MB)...")
start = time.time()

content = pdf_path.read_bytes()
engine = RAGEngine()

chunks = engine.ingest_document(pdf_path.name, content)
elapsed = time.time() - start

print(f"COMPLETADO: {chunks} chunks en {elapsed:.0f}s ({elapsed/60:.1f}min)")
gc.collect()
