from fastapi import APIRouter, HTTPException
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


async def _do_pull(model: str):
    import httpx, logging
    logger = logging.getLogger(__name__)
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            r = await client.post("http://localhost:11434/api/pull", json={"name": model, "stream": False})
            if r.status_code == 200:
                logger.info(f"Modelo {model} descargado OK")
            else:
                logger.warning(f"Error descargando {model}: {r.text[:200]}")
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
