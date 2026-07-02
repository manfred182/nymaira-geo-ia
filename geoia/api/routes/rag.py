from __future__ import annotations
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

_engine = None
def get_engine():
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
        engine = get_engine()
        result = engine.query(req.query, req.top_k)
        return RAGQueryResponse(response=result["answer"], sources=result["sources"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest")
async def ingest(file: UploadFile = File(...)):
    try:
        engine = get_engine()
        content = await file.read()
        result = engine.ingest_document(file.filename, content)
        return {"message": "Documento ingestado", "filename": file.filename, "chunks": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest-url")
async def ingest_url(req: RAGIngestURLRequest):
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
    import os

    try:
        engine = get_engine()
        chunks = engine.ingest_document(filename, content)
        return {
            "message": "Documento descargado e ingestado",
            "filename": filename,
            "chunks": chunks,
            "size_kb": len(content) // 1024,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
