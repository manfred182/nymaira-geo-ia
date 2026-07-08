"""Memoria de aprendizaje de Nymaira.

Tres responsabilidades, todas de un solo proceso (seguras con el FAISS del
servidor, ver [[project-rag-modelos]]):

1. **Memoria entre sesiones**: persiste el historial de conversación en disco
   para que sobreviva a los reinicios del servidor (`sessions.json`).
2. **Aprendizaje de preguntas/respuestas**: cuando una respuesta se fundamentó
   en fuentes reales (RAG/web/oficiales), guarda el par pregunta+respuesta en la
   base vectorial para reutilizarlo en consultas futuras similares.
3. **Análisis de preguntas**: registra cada consulta (`questions.jsonl`) y
   produce un informe con los temas más consultados y los vacíos de información.

Todo se envuelve en try/except desde el motor: si la memoria falla, el chat
sigue funcionando igual.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from pathlib import Path

from geoia.core.config import settings

logger = logging.getLogger(__name__)

# Historial máximo que se conserva por sesión (evita que sessions.json crezca sin límite)
_MAX_MSGS_POR_SESION = 60

# Palabras vacías en español para el análisis de temas frecuentes
_STOPWORDS = {
    "que", "como", "cual", "cuales", "para", "por", "con", "los", "las", "una",
    "uno", "del", "the", "y", "o", "a", "de", "en", "el", "la", "un", "es",
    "se", "su", "sus", "al", "lo", "me", "mi", "te", "si", "no", "ha", "hay",
    "son", "esta", "este", "esto", "esa", "ese", "eso", "muy", "mas", "pero",
    "porque", "cuando", "donde", "quien", "sobre", "entre", "tambien", "puede",
    "puedo", "debe", "hacer", "tiene", "tener", "ser", "estar", "necesito",
    "quiero", "dime", "cuentame", "explicame", "hola", "gracias", "favor",
}


class LearningMemory:
    """Singleton de memoria/aprendizaje. Instanciar vía `get_memory()`."""

    def __init__(self):
        # Los .json/.jsonl con Python `open()` manejan bien la ruta con acento;
        # a diferencia de FAISS no necesitan sanear el `´`.
        self.dir = Path(settings.data_dir) / "chat_memory"
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"No se pudo crear {self.dir}: {e}")
        self.sessions_path = self.dir / "sessions.json"
        self.questions_path = self.dir / "questions.jsonl"

    # ── 1. Memoria entre sesiones ────────────────────────────────────────
    def load_sessions(self) -> dict[str, list[dict]]:
        """Carga el historial persistido. Devuelve {} si no hay o si falla."""
        try:
            if self.sessions_path.exists():
                with open(self.sessions_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    n = sum(len(v) for v in data.values())
                    logger.info(f"Memoria: {len(data)} sesiones, {n} mensajes restaurados")
                    return data
        except Exception as e:
            logger.warning(f"No se pudo cargar sessions.json: {e}")
        return {}

    def persist_sessions(self, sessions: dict[str, list[dict]]) -> None:
        """Guarda el historial (acotando cada sesión a los últimos N mensajes).

        Escritura atómica: primero a un .tmp y luego replace, para que un corte a
        mitad de escritura no deje el archivo corrupto."""
        try:
            recorte = {
                sid: msgs[-_MAX_MSGS_POR_SESION:]
                for sid, msgs in sessions.items() if msgs
            }
            tmp = self.sessions_path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(recorte, f, ensure_ascii=False)
            tmp.replace(self.sessions_path)
        except Exception as e:
            logger.warning(f"No se pudo guardar sessions.json: {e}")

    # ── 3. Registro de preguntas (para análisis) ─────────────────────────
    def log_question(
        self, session_id: str, question: str, categoria: str | None,
        es_norma: bool, grounded: bool, n_sources: int,
    ) -> None:
        """Anexa una línea JSONL con la consulta y si se pudo fundamentar."""
        try:
            registro = {
                "ts": time.time(),
                "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
                "session_id": session_id,
                "pregunta": (question or "")[:500],
                "categoria": categoria,
                "es_norma": bool(es_norma),
                "fundamentada": bool(grounded),
                "n_fuentes": int(n_sources),
            }
            with open(self.questions_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(registro, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug(f"No se pudo registrar la pregunta: {e}")

    def analizar(self, limite: int | None = None) -> dict:
        """Informe agregado de las preguntas registradas.

        Devuelve temas más consultados, % de respuestas fundamentadas y los
        "vacíos": preguntas que NO se pudieron fundamentar (candidatas a nutrir
        la base con nuevos documentos)."""
        registros: list[dict] = []
        try:
            if self.questions_path.exists():
                with open(self.questions_path, "r", encoding="utf-8") as f:
                    for linea in f:
                        linea = linea.strip()
                        if linea:
                            try:
                                registros.append(json.loads(linea))
                            except Exception:
                                continue
        except Exception as e:
            logger.warning(f"No se pudo leer questions.jsonl: {e}")

        if limite:
            registros = registros[-limite:]

        total = len(registros)
        if total == 0:
            return {
                "total_preguntas": 0, "sesiones": 0, "fundamentadas": 0,
                "sin_fundamentar": 0, "pct_fundamentadas": 0.0,
                "temas": [], "categorias": [], "vacios": [],
            }

        fundamentadas = sum(1 for r in registros if r.get("fundamentada"))
        sesiones = len({r.get("session_id") for r in registros})

        # Categorías
        cat_counter = Counter(r.get("categoria") or "general" for r in registros)

        # Palabras clave frecuentes (temas)
        palabras: Counter = Counter()
        for r in registros:
            for w in re.findall(r"[a-záéíóúñ]{4,}", (r.get("pregunta") or "").lower()):
                if w not in _STOPWORDS:
                    palabras[w] += 1

        # Vacíos: preguntas sin fuentes, agrupadas por texto normalizado
        vacios_counter: Counter = Counter()
        for r in registros:
            if not r.get("fundamentada"):
                p = (r.get("pregunta") or "").strip()
                if p:
                    vacios_counter[p] += 1

        return {
            "total_preguntas": total,
            "sesiones": sesiones,
            "fundamentadas": fundamentadas,
            "sin_fundamentar": total - fundamentadas,
            "pct_fundamentadas": round(100.0 * fundamentadas / total, 1),
            "temas": [{"palabra": w, "veces": n} for w, n in palabras.most_common(15)],
            "categorias": [{"categoria": c, "veces": n} for c, n in cat_counter.most_common()],
            "vacios": [{"pregunta": p, "veces": n} for p, n in vacios_counter.most_common(15)],
        }


_memory: LearningMemory | None = None


def get_memory() -> LearningMemory:
    global _memory
    if _memory is None:
        _memory = LearningMemory()
    return _memory
