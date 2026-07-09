"""Siembra la base RAG UNA vez, offline (con el servidor apagado).

Usa upsert_document (idempotente por hash): re-ejecutarlo no re-embebe lo que no
cambió. Ejecutar:  venv/Scripts/python.exe scripts/seed_offline.py
"""
import sys
import time

from geoia.rag.engine import RAGEngine
from geoia.core.config import settings

r = RAGEngine()
if r.index is None:
    print("ERROR: FAISS no disponible (¿falta faiss-cpu?)", flush=True)
    sys.exit(1)

t0 = time.time()
for carpeta, patron in [(settings.data_dir / "rag_seed", "*.md"),
                        (settings.data_dir / "documents", "*.pdf")]:
    if not carpeta.exists():
        continue
    for path in sorted(carpeta.glob(patron)):
        mb = path.stat().st_size / 1e6
        ts = time.time()
        res = r.upsert_document(path.name, path.read_bytes())
        print(f"{res['status']:>9} {path.name} ({mb:.1f}MB) -> {res['chunks']} chunks "
              f"en {time.time()-ts:.0f}s (ntotal={r.index.ntotal})", flush=True)

print(f"DONE total={r.index.ntotal} tiempo={time.time()-t0:.0f}s", flush=True)
