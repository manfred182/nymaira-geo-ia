from __future__ import annotations
import asyncio
import hashlib
import os
import re
import tempfile
from pathlib import Path
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from functools import lru_cache

router = APIRouter()

# Voz femenina colombiana
TTS_VOICE = "es-CO-SalomeNeural"
TTS_RATE = "+0%"
TTS_VOLUME = "+0%"

# Cache directory for TTS audio files
CACHE_DIR = Path("models/cache/tts")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# In-memory LRU cache for hot responses
_in_memory_cache: dict[str, bytes] = {}
_IN_MEMORY_MAX = 20


class TTSRequest(BaseModel):
    text: str
    voice: str = TTS_VOICE
    rate: str = TTS_RATE
    volume: str = TTS_VOLUME


def _text_hash(text: str, voice: str) -> str:
    return hashlib.sha256(f"{voice}:{text}".encode()).hexdigest()


_EMOJI_RE = re.compile(
    r'[\U0001F300-\U0001FAFF'
    r'\U0001F600-\U0001F64F'
    r'\U0001F680-\U0001F6FF'
    r'\U0001F900-\U0001F9FF'
    r'\U00002600-\U000027BF'
    r'\U0001F1E6-\U0001F1FF'
    r'\U0000FE00-\U0000FE0F'
    r']+', re.UNICODE)


def _clean_text_for_tts(text: str) -> str:
    """Limpia texto para TTS: remueve emojis, markdown, URLs y HTML."""
    t = str(text or '')
    # Bloques de código completos
    t = re.sub(r'```[\s\S]*?```', '. ', t)
    # Código inline
    t = re.sub(r'`([^`]*)`', r'\1', t)
    # Links [texto](url) -> texto
    t = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', t)
    # URLs desnudas
    t = re.sub(r'https?://\S+', '', t)
    # HTML tags
    t = re.sub(r'<[^>]+>', '', t)
    # Emojis
    t = _EMOJI_RE.sub('', t)
    # Markdown: encabezados (## Título), énfasis (**negrita**, _cursiva_)
    t = re.sub(r'^\s{0,3}#{1,6}\s*', '', t, flags=re.M)
    t = re.sub(r'[*_]{1,3}', '', t)
    # Viñetas y citas al inicio de línea
    t = re.sub(r'^\s*[•\-•]\s+', '', t, flags=re.M)
    # Símbolos de tabla/cita/subrayado sueltos
    t = t.replace('•', ' ').replace('|', ' ').replace('>', ' ').replace('~', '')
    # Saltos de línea múltiples
    t = re.sub(r'\n{3,}', '\n\n', t)
    # Espacios múltiples
    t = re.sub(r' {2,}', ' ', t)
    return t.strip()


async def generate_tts_audio(text: str, voice: str = TTS_VOICE, rate: str = TTS_RATE, volume: str = TTS_VOLUME) -> bytes:
    """Genera audio TTS usando edge-tts con voz femenina colombiana y caché."""
    import edge_tts
    
    if not text or not text.strip():
        raise ValueError("Texto vacío")
    
    # Limpiar emojis y markdown
    text = _clean_text_for_tts(text)
    if not text:
        raise ValueError("Texto vacío después de limpiar")
    
    # Limitar longitud para evitar timeouts
    if len(text) > 5000:
        text = text[:5000] + "..."
    
    text_clean = text
    h = _text_hash(text_clean, voice)
    
    # 1. Check in-memory cache (fastest)
    if h in _in_memory_cache:
        return _in_memory_cache[h]
    
    # 2. Check disk cache
    cache_path = CACHE_DIR / f"{h}.mp3"
    if cache_path.exists():
        data = cache_path.read_bytes()
        # Also store in memory for subsequent requests
        _add_to_memory_cache(h, data)
        return data
    
    # 3. Generate via edge-tts
    communicate = edge_tts.Communicate(text_clean, voice, rate=rate, volume=volume)
    
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name
    
    try:
        await communicate.save(tmp_path)
        
        with open(tmp_path, "rb") as f:
            audio_data = f.read()
        
        # Save to both caches
        cache_path.write_bytes(audio_data)
        _add_to_memory_cache(h, audio_data)
        
        return audio_data
    finally:
        try:
            os.unlink(tmp_path)
        except:
            pass


def _add_to_memory_cache(h: str, data: bytes) -> None:
    _in_memory_cache[h] = data
    if len(_in_memory_cache) > _IN_MEMORY_MAX:
        oldest = next(iter(_in_memory_cache))
        del _in_memory_cache[oldest]


@router.post("")
async def text_to_speech(req: TTSRequest):
    """Convierte texto a voz usando voz femenina colombiana (es-CO-SalomeNeural)."""
    try:
        audio_data = await generate_tts_audio(
            req.text, 
            req.voice, 
            req.rate, 
            req.volume
        )
        
        return Response(
            content=audio_data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": 'inline; filename="nymaira_tts.mp3"',
                "Cache-Control": "public, max-age=3600"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error TTS: {str(e)}")


@router.get("/voices")
async def list_voices():
    """Lista voces disponibles en español."""
    import edge_tts
    voices = await edge_tts.list_voices()
    spanish_voices = [v for v in voices if v["Locale"].startswith("es-")]
    colombian = [v for v in spanish_voices if v["Locale"] == "es-CO"]
    
    # Count cache
    disk_cache_count = len(list(CACHE_DIR.glob("*.mp3"))) if CACHE_DIR.exists() else 0
    
    return {
        "colombian": colombian,
        "all_spanish": spanish_voices,
        "recommended": "es-CO-SalomeNeural (femenina colombiana)",
        "cache": {
            "in_memory": len(_in_memory_cache),
            "on_disk": disk_cache_count,
            "max_memory": _IN_MEMORY_MAX,
            "cache_dir": str(CACHE_DIR)
        }
    }


@router.post("/clear-cache")
async def clear_tts_cache():
    """Limpia el caché de audio TTS."""
    cleared = 0
    if CACHE_DIR.exists():
        for f in CACHE_DIR.glob("*.mp3"):
            try:
                f.unlink()
                cleared += 1
            except:
                pass
    _in_memory_cache.clear()
    return {"cleared": cleared, "status": "ok"}