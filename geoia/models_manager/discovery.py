"""Detección automática de endpoints LLM (Ollama, LM Studio, Jan, llama.cpp, OpenAI, etc.)."""

import asyncio
import httpx
from geoia.core.config import settings

# ── Proveedores locales conocidos ────────────────────────────────
_LOCAL_PROVIDERS = [
    {
        "name": "Ollama",
        "base_url": "http://localhost:11434",
        "provider": "ollama",
        "health": "/api/tags",
        "models_key": "models",
        "model_name_key": "name",
    },
    {
        "name": "LM Studio",
        "base_url": "http://localhost:1234/v1",
        "provider": "openai_compat",
        "health": "/models",
        "models_key": "data",
        "model_name_key": "id",
    },
    {
        "name": "Jan AI",
        "base_url": "http://localhost:1337/v1",
        "provider": "openai_compat",
        "health": "/models",
        "models_key": "data",
        "model_name_key": "id",
    },
    {
        "name": "LocalAI",
        "base_url": "http://localhost:8080/v1",
        "provider": "openai_compat",
        "health": "/models",
        "models_key": "data",
        "model_name_key": "id",
    },
    {
        "name": "llama.cpp server",
        "base_url": "http://localhost:8000/v1",
        "provider": "openai_compat",
        "health": "/models",
        "models_key": "data",
        "model_name_key": "id",
    },
    {
        "name": "AnythingLLM",
        "base_url": "http://localhost:3001/api",
        "provider": "openai_compat",
        "health": "/docs",
        "models_key": "data",
        "model_name_key": "id",
    },
]


async def discover_endpoints() -> list[dict]:
    endpoints = []

    # ── Detección paralela de todos los proveedores locales ──
    tasks = [_probe_provider(p) for p in _LOCAL_PROVIDERS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, dict):
            endpoints.append(r)

    # ── GGUF locales (llama-cpp-python directo) ──
    gguf = _scan_gguf_models()
    if gguf:
        endpoints.append(gguf)

    # ── OpenAI (si hay API key) ──
    if settings.openai_api_key:
        endpoints.append({
            "name": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "api_key": settings.openai_api_key,
            "provider": "openai",
            "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        })

    # ── Endpoints configurados manualmente en .env ──
    for ep in settings.llm_endpoints:
        if not any(e["base_url"] == ep["base_url"] for e in endpoints):
            endpoints.append({
                "name": ep.get("name", "Custom"),
                "base_url": ep["base_url"],
                "api_key": ep.get("api_key", ""),
                "provider": ep.get("provider", "openai_compat"),
                "models": ep.get("models", []),
            })

    return endpoints


async def _probe_provider(p: dict) -> dict | None:
    """Prueba si un proveedor local está corriendo y lista sus modelos."""
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            url = p["base_url"].rstrip("/") + p["health"]
            r = await client.get(url)
            if r.status_code not in (200, 201):
                return None

            models = []
            try:
                data = r.json()
                items = data.get(p["models_key"], []) if isinstance(data, dict) else []
                models = [m[p["model_name_key"]] for m in items if isinstance(m, dict)]
            except Exception:
                pass

            return {
                "name": p["name"],
                "base_url": p["base_url"],
                "api_key": "",
                "provider": p["provider"],
                "models": models,
                "online": True,
            }
    except Exception:
        return None


def _scan_gguf_models() -> dict | None:
    """Detecta modelos GGUF en models/llm/ para uso con llama-cpp-python."""
    try:
        llm_dir = settings.llm_models_dir
        if not llm_dir.exists():
            return None
        ggufs = list(llm_dir.glob("*.gguf"))
        if not ggufs:
            return None
        return {
            "name": "GGUF Local (llama-cpp)",
            "base_url": "local://gguf",
            "api_key": "",
            "provider": "gguf",
            "models": [f.name for f in ggufs],
            "paths": {f.name: str(f) for f in ggufs},
            "online": True,
        }
    except Exception:
        return None


async def get_ollama_available_models() -> list[dict]:
    """Modelos instalados en Ollama con metadata."""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get("http://localhost:11434/api/tags")
            if r.status_code == 200:
                return r.json().get("models", [])
    except Exception:
        pass
    return []


# Catálogo de modelos recomendados para catastro/SIG
MODELOS_RECOMENDADOS = [
    {"id": "qwen2.5:7b",    "label": "Qwen 2.5 7B",       "size": "4.7GB", "tag": "⭐ Recomendado", "desc": "Mejor balance calidad/velocidad en español"},
    {"id": "qwen2.5:3b",    "label": "Qwen 2.5 3B",       "size": "2GB",   "tag": "🚀 Ligero",      "desc": "Rápido, bueno para consultas simples"},
    {"id": "llama3.2:3b",   "label": "Llama 3.2 3B",      "size": "2GB",   "tag": "🦙 Meta",        "desc": "Excelente para texto y análisis"},
    {"id": "llama3.1:8b",   "label": "Llama 3.1 8B",      "size": "4.7GB", "tag": "🦙 Meta",        "desc": "Alta calidad, requiere más RAM"},
    {"id": "mistral:7b",    "label": "Mistral 7B",         "size": "4.1GB", "tag": "🌀 Mistral",     "desc": "Muy bueno en español e instrucciones"},
    {"id": "gemma2:2b",     "label": "Gemma 2 2B",         "size": "1.6GB", "tag": "💎 Google",      "desc": "Ultra ligero, ideal para equipos con poca RAM"},
    {"id": "phi4:14b",      "label": "Phi-4 14B",          "size": "8.9GB", "tag": "🔬 Microsoft",   "desc": "Razonamiento avanzado, requiere GPU"},
    {"id": "deepseek-r1:7b","label": "DeepSeek R1 7B",     "size": "4.7GB", "tag": "🧠 Razonamiento","desc": "Especializado en análisis y razonamiento"},
]
