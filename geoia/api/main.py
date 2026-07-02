from __future__ import annotations
import asyncio, logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from geoia.core.config import settings

from geoia.api.routes import chatbot, rag, geo, automation, models, llm, search, processing

logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    description="IA para procesos catastrales y geoespaciales",
    version="0.3.0",
)

_ollama_started = False


async def _ensure_ollama_model():
    """Auto-descarga Qwen2.5-7B en Ollama si esta disponible."""
    global _ollama_started
    if _ollama_started:
        return
    _ollama_started = True
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("http://localhost:11434/api/tags")
            if r.status_code != 200:
                return
            tags = r.json().get("models", [])
            models_avail = [m["name"] for m in tags]

            # Preferir estos modelos ordenados por calidad
            preferidos = [
                "qwen2.5:7b",
                "phi-4:14b",
                "llama3.1:8b",
                "mistral:7b",
                "qwen2.5:3b",
            ]

            instalado = None
            for p in preferidos:
                if p in models_avail or p.replace(":", ":latest") in models_avail:
                    instalado = p
                    break

            if not instalado:
                # Escoger el mejor disponible dentro de recursos
                logger.info("Descargando Qwen2.5-7B desde Ollama (modelo multilingue optimo)...")
                asyncio.create_task(_pull_model("qwen2.5:7b"))
            else:
                logger.info(f"Ollama ya tiene: {instalado}")
    except Exception as e:
        logger.debug(f"Ollama no disponible: {e}")


async def _pull_model(model: str):
    import httpx
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            r = await client.post(
                "http://localhost:11434/api/pull",
                json={"name": model, "stream": False},
            )
            if r.status_code == 200:
                logger.info(f"Modelo {model} descargado exitosamente")
            else:
                logger.warning(f"Fallo al descargar {model}: {r.text}")
    except Exception as e:
        logger.warning(f"No se pudo descargar {model}: {e}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chatbot.router, prefix="/api/v1/chatbot", tags=["Chatbot"])
app.include_router(llm.router, prefix="/api/v1/llm", tags=["LLM"])
app.include_router(search.router, prefix="/api/v1/search", tags=["Búsqueda"])
app.include_router(rag.router, prefix="/api/v1/rag", tags=["RAG"])
app.include_router(geo.router, prefix="/api/v1/geo", tags=["Geoespacial"])
app.include_router(automation.router, prefix="/api/v1/automation", tags=["Automatización"])
app.include_router(models.router, prefix="/api/v1/models", tags=["Modelos"])
app.include_router(processing.router, prefix="/api/v1/geo", tags=["Procesamiento"])

static_dir = settings.project_root / "geoia" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    async def root():
        return FileResponse(str(static_dir / "index.html"))
else:
    @app.get("/")
    async def root():
        return {"message": "Nymaira API", "docs": "/docs"}


@app.on_event("startup")
async def startup():
    asyncio.create_task(_ensure_ollama_model())
    asyncio.create_task(_warmup_llm())


async def _warmup_llm():
    """Pre-carga el modelo en memoria 3 segundos después de arrancar."""
    await asyncio.sleep(3)
    try:
        from geoia.chatbot.engine import _warmup_ollama
        await _warmup_ollama()
    except Exception:
        pass


@app.get("/models/status")
async def model_status():
    from geoia.core.ai_models import estado_modelos
    return estado_modelos()


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}
