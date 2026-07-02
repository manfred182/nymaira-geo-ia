from __future__ import annotations
import json
import asyncio
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()

_engine = None
def get_engine():
    global _engine
    if _engine is None:
        from geoia.chatbot.engine import ChatbotEngine
        _engine = ChatbotEngine()
    return _engine


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    geojson: dict | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str


class UploadResponse(BaseModel):
    filename: str
    content: str
    size_kb: int
    entidades: list[dict] = []
    modelos: list[str] = []
    es_espacial: bool = False
    geojson: dict | None = None
    count: int = 0
    crs: str | None = None
    bounds: list[float] | None = None


class STTResponse(BaseModel):
    texto: str


EXT_ESPACIALES = {".geojson", ".json", ".kml", ".kmz", ".gpkg", ".zip",
                  ".shp", ".dbf", ".prj", ".shx", ".gdb", ".csv", ".xlsx", ".xls",
                  ".tif", ".tiff"}


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        engine = get_engine()
        respuesta = await engine.chat(req.message, req.session_id, geojson=req.geojson)
        return ChatResponse(response=respuesta, session_id=req.session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    import os
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        content = await file.read()
        fname = file.filename or "archivo"
        ext = os.path.splitext(fname)[1].lower()
        size_kb = len(content) // 1024 or 1

        # ── Si es archivo espacial, parsear geometria ──
        if ext in EXT_ESPACIALES or ext == ".kmz" or ".gdb" in fname.lower():
            try:
                from geoia.geo.parsers import info_archivo_espacial
                info = info_archivo_espacial(content, fname)
                if "error" not in info and info.get("type") in ("vector",):
                    resumen = (
                        f"📂 **{fname}** ({info.get('count', 0)} geometrías, "
                        f"CRS: {info.get('crs', 'N/A')})\n"
                    )
                    if info.get("bounds"):
                        b = info["bounds"]
                        resumen += f"🌐 Extensión: {b[0]:.4f}, {b[1]:.4f} a {b[2]:.4f}, {b[3]:.4f}\n"
                    if info.get("columnas"):
                        resumen += f"📋 Columnas: {', '.join(info['columnas'][:10])}\n"

                    # Si es pequeño, incluir GeoJSON completo
                    geojson = info.get("geojson")
                    if geojson:
                        return UploadResponse(
                            filename=fname,
                            content=resumen.strip(),
                            size_kb=size_kb,
                            es_espacial=True,
                            geojson=geojson,
                            count=info.get("count", 0),
                            crs=info.get("crs"),
                            bounds=info.get("bounds"),
                        )

                    # GeoJSON muy grande → solo metadatos
                    return UploadResponse(
                        filename=fname,
                        content=resumen.strip() + "\n(archivo grande, GeoJSON no incluido)",
                        size_kb=size_kb,
                        es_espacial=True,
                        count=info.get("count", 0),
                        crs=info.get("crs"),
                        bounds=info.get("bounds"),
                    )
            except Exception as e:
                logger.debug(f"No es archivo espacial válido: {e}")
                # Fallback a procesamiento normal
                pass

        # ── Archivo normal (documento, imagen, etc.) ──
        try:
            from geoia.core.ai_models import procesar_documento, resumen_documento
            resultado = procesar_documento(fname, content)
            return UploadResponse(
                filename=resultado["nombre"],
                content=resumen_documento(resultado),
                size_kb=size_kb,
                entidades=resultado.get("entidades", []),
                modelos=resultado.get("modelos_usados", []),
            )
        except Exception as e:
            logger.warning(f"Error en procesar_documento: {e}")
            # Fallback: solo devolver metadata del archivo
            return UploadResponse(
                filename=fname,
                content=f"Archivo cargado: {fname}\n\nTipo: {ext}\nTamaño: {size_kb}KB",
                size_kb=size_kb,
            )
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error en upload_file: {e}")
        raise HTTPException(status_code=400, detail=f"Error al procesar archivo: {str(e)}")


@router.post("/stt", response_model=STTResponse)
async def speech_to_text(file: UploadFile = File(...)):
    try:
        content = await file.read()
        from geoia.core.ai_models import transcribir
        texto = transcribir(content)
        if not texto:
            raise HTTPException(status_code=400, detail="No se pudo transcribir el audio. Instala Whisper: pip install openai-whisper")
        return STTResponse(texto=texto)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def chat_stream(req: ChatRequest):
    """SSE endpoint — devuelve tokens a medida que el LLM los genera."""
    engine = get_engine()

    async def generate():
        try:
            async for chunk in engine.stream_chat(req.message, req.session_id, req.geojson):
                yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/reset")
async def reset_session(session_id: str = "default"):
    engine = get_engine()
    engine.reset_session(session_id)
    return {"message": "Sesión reiniciada", "session_id": session_id}
