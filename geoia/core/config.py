from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Nymaira"
    debug: bool = True

    project_root: Path = Path(__file__).parent.parent.parent
    data_dir: Path = project_root / "data"
    models_dir: Path = project_root / "models"
    hf_cache_dir: Path = models_dir / "huggingface"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # LLM Endpoints (JSON list en .env: [{"name":"Ollama","base_url":"http://localhost:11434"}])
    llm_endpoints: List[dict] = []

    # RAG / Vectores
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_model_path: Path = models_dir / "sentence-transformers" / embedding_model

    # Modelos LLM locales
    llm_models_dir: Path = models_dir / "llm"
    local_llm_model_name: str = "Qwen/Qwen2.5-0.5B-Instruct"
    local_llm_model_path: Path = models_dir / "huggingface" / "Qwen" / "Qwen2.5-0.5B-Instruct"

    # Ollama
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:1.5b"
    ollama_embedding_model: str = "nomic-embed-text"

    # Geoespacial
    vit_model_name: str = "google/vit-base-patch16-224"
    vit_model_path: Path = models_dir / "huggingface" / "google" / "vit-base-patch16-224"

    # WebSearch
    search_cache_ttl: int = 300
    searxng_url: str = "http://localhost:4000"

    # Rutas de datos
    raster_dir: Path = data_dir / "rasters"
    vector_dir: Path = data_dir / "vectors"
    documents_dir: Path = data_dir / "documents"


settings = Settings()
