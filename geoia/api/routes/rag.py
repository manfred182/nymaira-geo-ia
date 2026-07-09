from __future__ import annotations
import asyncio
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

_engine = None
_engine_lock = asyncio.Lock()


async def get_engine():
    global _engine
    if _engine is None:
        async with _engine_lock:
            if _engine is None:
                from geoia.rag.engine import RAGEngine
                _engine = await asyncio.to_thread(RAGEngine)
    return _engine


def get_engine_sync():
    global _engine
    if _engine is None:
        from geoia.rag.engine import RAGEngine
        _engine = RAGEngine()
    return _engine


class RAGQueryRequest(BaseModel):
    query: str
    top_k: int = 5


class RAGQueryResponse(BaseModel):
    response: str
    sources: list[str]


class RAGIngestURLRequest(BaseModel):
    url: str
    filename: str | None = None


@router.post("/query", response_model=RAGQueryResponse)
async def query(req: RAGQueryRequest):
    try:
        engine = await get_engine()
        result = await asyncio.to_thread(engine.query, req.query, req.top_k)
        return RAGQueryResponse(response=result["answer"], sources=result["sources"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest")
async def ingest(file: UploadFile = File(...)):
    try:
        engine = await get_engine()
        content = await file.read()
        # upsert: si la fuente ya existe con contenido nuevo, la REEMPLAZA (no duplica).
        res = await asyncio.to_thread(engine.upsert_document, file.filename, content)
        return {"message": f"Documento {res['status']}", "filename": file.filename,
                "status": res["status"], "chunks": res["chunks"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/source/{source}")
async def delete_source(source: str):
    """Retira TODOS los chunks de una fuente (p. ej. una resolución derogada)."""
    try:
        engine = await get_engine()
        removed = await asyncio.to_thread(engine.delete_source, source)
        return {"message": f"Fuente '{source}' eliminada", "chunks_removidos": removed}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def stats():
    """Estado de la base: total de vectores y fuentes cargadas."""
    try:
        engine = await get_engine()
        from collections import Counter
        por_fuente = Counter(m.get("source", "?") for m in engine.metadatas)
        return {
            "total_vectores": engine.index.ntotal if engine.index else 0,
            "fuentes": [{"source": s, "chunks": n} for s, n in por_fuente.most_common()],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest-url")
async def ingest_url(req: RAGIngestURLRequest):
    import os
    import httpx
    from urllib.parse import urlparse
    from geoia.websearch.dns_cache import resolve

    host = urlparse(req.url).hostname
    if host:
        resolve(host)

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            r = await client.get(req.url)
            r.raise_for_status()
            content = r.content
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo descargar {req.url}: {e}")

    filename = req.filename or os.path.basename(urlparse(req.url).path) or "documento.pdf"

    try:
        engine = await get_engine()
        res = await asyncio.to_thread(engine.upsert_document, filename, content)
        return {
            "message": f"Documento descargado y {res['status']}",
            "filename": filename,
            "status": res["status"],
            "chunks": res["chunks"],
            "size_kb": len(content) // 1024,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
