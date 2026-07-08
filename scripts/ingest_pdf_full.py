"""Ingesta completa del PDF offline, con logs y manejo de memoria."""
import sys, os, time, gc, logging
from pathlib import Path

# Config
BASE = Path(__file__).parent.parent
os.chdir(str(BASE))
sys.path.insert(0, str(BASE))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(str(BASE / "data" / "logs" / "ingest_pdf.log"))],
)
log = logging.getLogger("ingest")

# Imports
from geoia.rag.engine import RAGEngine
from geoia.core.config import settings

pdf_path = settings.data_dir / "documents" / "resolucion_1040_de_2023.pdf"
if not pdf_path.exists():
    log.error(f"PDF no encontrado: {pdf_path}")
    sys.exit(1)

size_mb = pdf_path.stat().st_size / (1024 * 1024)
log.info(f"Iniciando ingesta de {pdf_path.name} ({size_mb:.1f} MB)")

start = time.time()
content = pdf_path.read_bytes()
log.info(f"PDF leído: {len(content)} bytes en {time.time()-start:.1f}s")

engine = RAGEngine()
log.info("RAG Engine inicializado")

chunks = engine.ingest_document(pdf_path.name, content)
elapsed = time.time() - start

log.info(f"INGESTA COMPLETADA: {chunks} chunks en {elapsed:.0f}s ({elapsed/60:.1f} min)")

# Verify
import chromadb
c = chromadb.PersistentClient(str(settings.vector_db_path))
col = c.get_or_create_collection("documentos_catastrales")
log.info(f"Total en ChromaDB: {col.count()} chunks")

# Cleanup
del engine
gc.collect()
log.info("Done")
