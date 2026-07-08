from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncio

router = APIRouter()


@router.get("")
async def model_status():
    from geoia.core.models import get_model_status
    from geoia.models_manager import manager
    from geoia.websearch import searcher

    status = get_model_status()

    try:
        await manager.discover()
        status["llm"] = manager.health()
    except Exception as e:
        status["llm"] = {"error": str(e), "endpoints": 0, "models": []}

    try:
        status["search"] = await searcher.health()
    except Exception as e:
        status["search"] = {"error": str(e)}

    return status


@router.get("/llm/discover")
async def discover_llm():
    """Detecta automáticamente todos los proveedores LLM disponibles."""
    from geoia.models_manager.discovery import discover_endpoints, MODELOS_RECOMENDADOS
    endpoints = await discover_endpoints()
    return {
        "endpoints": endpoints,
        "recomendados": MODELOS_RECOMENDADOS,
        "total": len(endpoints),
    }


@router.get("/llm/ollama")
async def ollama_models():
    """Lista modelos instalados en Ollama."""
    from geoia.models_manager.discovery import get_ollama_available_models, MODELOS_RECOMENDADOS
    instalados = await get_ollama_available_models()
    ids_instalados = {m["name"] for m in instalados}
    recomendados = [
        {**m, "instalado": m["id"] in ids_instalados or any(m["id"] in n for n in ids_instalados)}
        for m in MODELOS_RECOMENDADOS
    ]
    return {"instalados": instalados, "recomendados": recomendados}


class PullRequest(BaseModel):
    model: str


@router.post("/llm/ollama/pull")
async def pull_ollama_model(req: PullRequest):
    """Descarga un modelo de Ollama en segundo plano."""
    import httpx
    model = req.model.strip()
    if not model:
        raise HTTPException(400, "Nombre de modelo requerido")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("http://localhost:11434/api/tags")
            if r.status_code != 200:
                raise HTTPException(503, "Ollama no está corriendo. Ejecuta: ollama serve")
    except httpx.ConnectError:
        raise HTTPException(503, "Ollama no disponible. Instálalo en ollama.com y ejecuta: ollama serve")

    asyncio.create_task(_do_pull(model))
    return {"status": "descargando", "model": model, "message": f"Descargando {model}... puede tardar varios minutos"}


@router.get("/llm/ollama/pull/stream")
async def pull_ollama_stream(model: str):
    """Stream de progreso de descarga de modelo Ollama."""
    model = model.strip()
    if not model:
        raise HTTPException(400, "Nombre de modelo requerido")

    async def event_generator():
        import httpx, json
        try:
            async with httpx.AsyncClient(timeout=600) as client:
                async with client.stream("POST", "http://localhost:11434/api/pull", json={"name": model, "stream": True}) as r:
                    if r.status_code != 200:
                        yield f"data: {json.dumps({'error': 'Ollama error', 'status': r.status_code})}\n\n"
                        return
                    async for line in r.aiter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                status = data.get("status", "")
                                completed = data.get("completed", 0)
                                total = data.get("total", 0)
                                yield f"data: {json.dumps({'status': status, 'completed': completed, 'total': total, 'model': model})}\n\n"
                            except Exception:
                                pass
        except httpx.ConnectError:
            yield f"data: {json.dumps({'error': 'Ollama no disponible'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _do_pull(model: str):
    import httpx, logging
    logger = logging.getLogger(__name__)
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            async with client.stream("POST", "http://localhost:11434/api/pull", json={"name": model, "stream": True}) as r:
                if r.status_code == 200:
                    async for line in r.aiter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                if data.get("status"):
                                    logger.info(f"Pull {model}: {data['status']}")
                            except Exception:
                                pass
                    logger.info(f"Modelo {model} descargado OK")
                else:
                    logger.warning(f"Error descargando {model}: {await r.text()}")
    except Exception as e:
        logger.error(f"Pull {model} falló: {e}")


@router.get("/llm/active")
async def get_active_model():
    """Retorna el modelo LLM activo actual."""
    from geoia.core.config import settings
    import httpx
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            r = await client.get("http://localhost:11434/api/tags")
            if r.status_code == 200:
                models = r.json().get("models", [])
                preferidos = ["qwen2.5:7b", "llama3.1:8b", "mistral:7b", "qwen2.5:3b", "llama3.2:3b", "gemma2:2b"]
                nombres = [m["name"] for m in models]
                for p in preferidos:
                    if p in nombres:
                        return {"provider": "ollama", "model": p, "online": True}
                if nombres:
                    return {"provider": "ollama", "model": nombres[0], "online": True}
    except Exception:
        pass
    return {"provider": "none", "model": None, "online": False}
