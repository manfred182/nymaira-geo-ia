"""Chatbot engine with real-time spatial analysis, multi-source search, and capability evaluation."""

from __future__ import annotations
import asyncio, json, logging, re
from typing import AsyncIterator

logger = logging.getLogger(__name__)


# ── Detección de coordenadas ──────────────────────────────────────

_COORD_PATTERNS = [
    # lat, lon  o  lon, lat entre paréntesis/brackets
    re.compile(r'[\(\[]\s*(-?\d{1,3}(?:\.\d+)?)\s*[,;]\s*(-?\d{1,3}(?:\.\d+)?)\s*[\)\]]'),
    # lat: X lon: Y  |  latitude X longitude Y
    re.compile(r'lat(?:itud)?[:\s]+(-?\d{1,3}(?:\.\d+)?)[,\s]+lon(?:gitud)?[:\s]+(-?\d{1,3}(?:\.\d+)?)'),
    # N 4.57° W 74.29° (grados decimales)
    re.compile(r'N\s*(-?\d{1,3}(?:\.\d+)?)[°].*?[EW]\s*(-?\d{1,3}(?:\.\d+)?)[°]', re.I),
    # número decimal, número decimal (genérico) – solo si ambos son rangos plausibles de Colombia
    re.compile(r'(-?\d{1,2}\.\d{3,})\s*,\s*(-?\d{2,3}\.\d{3,})'),
]

_COL_LAT = (-5.0, 13.5)
_COL_LON = (-82.0, -65.0)


def _detectar_coordenadas(message: str) -> dict | None:
    """Extrae la primera coordenada válida del mensaje y devuelve un GeoJSON Point."""
    for pat in _COORD_PATTERNS:
        for m in pat.finditer(message):
            try:
                a, b = float(m.group(1)), float(m.group(2))
                # Intentar determinar orden lat/lon
                lat, lon = (a, b) if _COL_LAT[0] <= a <= _COL_LAT[1] and _COL_LON[0] <= b <= _COL_LON[1] else (b, a)
                if _COL_LAT[0] <= lat <= _COL_LAT[1] and _COL_LON[0] <= lon <= _COL_LON[1]:
                    return {
                        "type": "FeatureCollection",
                        "features": [{
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [lon, lat]},
                            "properties": {"origen": "chat", "lat": lat, "lon": lon},
                        }],
                    }
            except (ValueError, IndexError):
                continue
    return None

# ── Catalogo de capacidades ─────────────────────────────────────

CAPABILITIES: dict[str, dict] = {
    "cruce_espacial": {
        "label": "🌐 Cruce de información espacial",
        "puede": True,
        "como": "Sube dos capas en Geo IA > Cruce de Información Espacial, o conéctate a WFS",
        "keywords": ["cruce", "interseccion", "overlay", "superposicion", "cruce de capas"],
    },
    "buscar_colombia": {
        "label": "🇨🇴 Búsqueda en fuentes oficiales de Colombia",
        "puede": True,
        "como": "Usa la pestaña Colombia o pregúntame directamente",
        "keywords": ["buscar", "fuentes", "colombia", "gobierno", "oficial", "norma", "ley", "decreto"],
    },
    "catastro": {
        "label": "🏛️ Información catastral general",
        "puede": True,
        "como": "Te explico procesos, trámites, y busco información pública",
        "keywords": ["catastro", "matricula", "avaluo", "lindero", "predio", "tramite"],
    },
    "wfs_conexion": {
        "label": "📡 Conexión a servidores WFS/WMS colombianos",
        "puede": True,
        "como": "En Geo IA > Servicios WFS/WMS Colombia, selecciona un servidor",
        "keywords": ["wfs", "wms", "servidor", "capas", "igac", "ideam", "upra"],
    },
    "archivos_espaciales": {
        "label": "📂 Lectura de archivos espaciales (SHP, KML, KMZ, GDB, GeoJSON, GPKG, GeoTIFF)",
        "puede": True,
        "como": "Sube el archivo en Geo IA o adjúntalo en el chat",
        "keywords": ["shp", "kml", "kmz", "shapefile", "geojson", "gdb", "geopackage", "archivo espacial"],
    },
    "clasificar_imagen": {
        "label": "🛰️ Clasificación de imágenes satelitales",
        "puede": True,
        "como": "Sube la imagen en Geo IA > Clasificación de Imágenes",
        "keywords": ["clasificar", "imagen", "satelital", "satelite"],
    },
    "calcular_area": {
        "label": "📏 Cálculo de área, perímetro, centroides",
        "puede": True,
        "como": "Sube un archivo espacial en Geo IA y usa los botones de consulta",
        "keywords": ["area", "perimetro", "centroide", "medir", "calcular"],
    },
    "validar_lindero": {
        "label": "📐 Validación de linderos (polígonos)",
        "puede": True,
        "como": "Usa la pestaña Validación para ingresar coordenadas",
        "keywords": ["validar", "lindero", "poligono", "coordenadas"],
    },
    "documentos_rag": {
        "label": "📄 Consulta de documentos (RAG)",
        "puede": True,
        "como": "Sube documentos en la pestaña Documentos y haz preguntas",
        "keywords": ["documento", "pdf", "rag", "escritura", "leer documento"],
    },
    "procesamiento_qgis": {
        "label": "⚙️ Procesamiento geoespacial con QGIS (buffer, clip, dissolve, centroides, intersección)",
        "puede": True,
        "como": "Pídeme directamente: 'haz buffer de 100m', 'recorta esta capa', 'calcula centroides'",
        "keywords": ["buffer", "clip", "recortar", "dissolve", "disolver", "centroide", "interseccion", "union", "reproyectar", "simplificar"],
    },
    "voz": {
        "label": "🎤 Entrada por voz",
        "puede": True,
        "como": "Presiona el botón 🎤 en el chat y habla",
        "keywords": ["voz", "hablar", "dictar", "microfono"],
    },
    "predio_especifico": {
        "label": "🔍 Consulta de un predio específico por matrícula",
        "puede": False,
        "razon": "Los datos de matrícula requieren consulta directa en el SNRP (Supernotariado) con autenticación. Puedo explicarte cómo hacerlo.",
        "keywords": ["matricula inmobiliaria", "numero de matricula", "consultar predio", "mi predio", "mi terreno"],
    },
    "descargar_archivos": {
        "label": "⬇️ Descargar archivos automáticamente",
        "puede": False,
        "razon": "No puedo iniciar descargas. Puedo darte los enlaces para que los descargues manualmente.",
        "keywords": ["descargar", "download", "bajar archivo"],
    },
    "igac_catastro": {
        "label": "🏛️ Catastro IGAC - Base Nacional 10-2025",
        "puede": True,
        "como": "Consulta predios catastrales, estadísticas y datos geoespaciales del IGAC directamente",
        "keywords": ["igac", "catastro", "base catastral", "predio", "matricula", "avaluo", "geoportal igac"],
    },
    "normatividad_catastral": {
        "label": "⚖️ Normatividad catastral colombiana (Resolución 1040 de 2023)",
        "puede": True,
        "como": "Pregúntame sobre la Resolución 1040, procedimientos catastrales, avalúos, conservación catastral",
        "keywords": ["resolucion 1040", "normatividad", "norma", "procedimiento catastral", "conservacion catastral", "avaluo catastral", "formacion catastral", "actualizacion catastral", "1040 de 2023"],
    },
    "ia_externa": {
        "label": "🤖 Conexión a IAs externas (ChatGPT, Claude, Gemini)",
        "puede": False,
        "razon": "Nymaira funciona 100% local con modelos open-source. No depende de servicios cloud externos.",
        "keywords": ["chatgpt", "claude", "gemini", "gpt", "inteligencia artificial externa", "ia online"],
    },
    "correo": {
        "label": "📧 Enviar correos o notificaciones",
        "puede": False,
        "razon": "No tengo acceso a servicios de correo. Puedo preparar el contenido para que lo envíes.",
        "keywords": ["correo", "email", "notificar", "enviar"],
    },
    "legal": {
        "label": "⚖️ Determinaciones legales o jurídicas",
        "puede": False,
        "razon": "No soy abogado ni puedo dar asesoría legal. Consulta con un profesional del derecho.",
        "keywords": ["legal", "abogado", "demanda", "juicio", "asesoria legal", "juridico"],
    },
    "ia_propia": {
        "label": "🧠 Modelos de IA locales: Ollama, OCR, Whisper, GLiNER",
        "puede": True,
        "como": "Ya están integrados. Pregúntame lo que necesites.",
        "keywords": ["ia", "inteligencia artificial", "modelo", "red neuronal", "machine learning"],
    },
}


def _evaluar_solicitud(message: str) -> dict:
    """Evalua si Nymaira puede cumplir una solicitud y devuelve diagnostico."""
    m = message.lower()
    capacidades_coincidentes = []
    capacidades_no_disponibles = []

    for cid, cap in CAPABILITIES.items():
        if any(kw in m for kw in cap.get("keywords", [])):
            if cap.get("puede"):
                capacidades_coincidentes.append(cap)
            else:
                capacidades_no_disponibles.append(cap)

    return {
        "puede": len(capacidades_coincidentes) > 0,
        "no_puede": len(capacidades_no_disponibles) > 0,
        "capacidades": capacidades_coincidentes,
        "limitaciones": capacidades_no_disponibles,
        "tiene_coincidencias": len(capacidades_coincidentes) + len(capacidades_no_disponibles) > 0,
    }


def _extraer_tema(message: str) -> tuple[str | None, bool, bool]:
    """Clasifica la consulta: (categoria, directo_api, usar_wfs)."""
    m = message.lower()

    if any(w in m for w in ("cruce espacial", "cruce de informacion", "cruce", "overlay",
                            "superposicion", "interseccion capas", "cruce de capas",
                            "cruce predio", "cruce ambiental", "cruce catastral",
                            "analisis espacial", "analisis geoespacial")):
        return "todas", False, True
    if any(w in m for w in ("catastr", "matricula", "avaluo", "lindero", "predio",
                            "registro", "igac", "snr", "snrp", "geoport", "icde",
                            "cartograf", "predial", "codigo catastral", "geoportal")):
        return "catastral", True, False
    if any(w in m for w in ("buffer", "clip", "recort", "dissolve", "disolver",
                            "centroid", "reproyect", "simplif", "fix geometry",
                            "procesamiento", "procesar capa", "qgis")):
        return "todas", False, True
    if any(w in m for w in ("ambient", "licencia ambient", "ideam", "anla", "siac",
                            "parque nacional", "car", "agua", "bosque", "fauna",
                            "flora", "mineria", "hidrocarbur", "anh", "anm", "clima",
                            "cambio climatico", "ecosistem", "cuenca")):
        return "ambiental", False, False
    if any(w in m for w in ("productiv", "agricol", "rural", "upra", "tierra",
                            "cultivo", "agro", "agrosavia", "ica", "finagro",
                            "banco agrario", "frontera agricola", "aptitud suelo")):
        return "productiva", False, False
    if any(w in m for w in ("salud", "educacion", "trabajo", "icbf", "sena",
                            "dps", "ciencia", "cultura", "deporte", "bienestar")):
        return "social", False, False
    if any(w in m for w in ("hacienda", "impuesto", "dian", "comercio", "sic",
                            "banco repub", "financier", "superfinancier",
                            "presupuesto", "econom")):
        return "economica", False, False
    if any(w in m for w in ("transporte", "via", "invia", "ani", "aerocivil",
                            "mintic", "telecomunicacion", "infraestructur",
                            "energia", "minas")):
        return "infraestructura", False, False
    if any(w in m for w in ("colombia", "gobierno", "datos abiertos", "nacion",
                            "nacional", "oficial", "presidencia", "justicia",
                            "ley", "norma", "decreto", "constitucion")):
        return "catastral", False, False
    if any(w in m for w in ("igac", "catastro", "matricula", "predio", "avaluo",
                            "base catastral", "geoportal", "codigo catastral",
                            "registro catastral", "cartografia basica")):
        return "catastral", True, False

    return None, False, False


async def _buscar_en_wfs(tema: str, limit: int = 3) -> list[str]:
    """Consulta servidores WFS colombianos en vivo y devuelve descripciones."""
    from geoia.websearch.wfs_colombia import listar_servidores, wfs_get_capabilities
    lines: list[str] = []
    consultados = 0
    exitosos = 0

    servidores = listar_servidores()
    if tema and tema != "todas":
        servidores = [s for s in servidores if s.get("categoria") == tema]
    servidores = servidores[:limit + 3]

    async def consultar(srv: dict) -> str | None:
        nonlocal consultados, exitosos
        try:
            url = srv.get("url_wfs", "")
            if not url:
                return None
            consultados += 1
            caps = await wfs_get_capabilities(url)
            if "error" in caps:
                return None
            exitosos += 1
            capas = caps.get("capas", [])
            if not capas:
                return None
            top = [c["name"] for c in capas[:5]]
            return (
                f"• **{srv['nombre']}** (categoría: {srv.get('categoria','')})\n"
                f"  Capas disponibles: {', '.join(top)}\n"
                f"  Total: {len(capas)} capas | WFS: {url}"
            )
        except Exception:
            return None

    resultados = await asyncio.gather(*[consultar(s) for s in servidores], return_exceptions=True)
    for r in resultados:
        if isinstance(r, str):
            lines.append(r)

    if lines:
        lines.insert(0, f"🌐 **{exitosos} servidores WFS colombianos conectados en vivo** ({consultados} intentados):")
    return lines


async def _buscar_en_web(query: str, num: int = 6) -> list[dict]:
    """Busca en multiple proveedores web en paralelo."""
    import httpx
    from urllib.parse import quote_plus

    results: list[dict] = []
    seen_urls: set[str] = set()

    async def ddg() -> list[dict]:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
            async with httpx.AsyncClient(timeout=8, follow_redirects=True) as c:
                r = await c.get(url, headers=headers)
                if r.status_code == 200:
                    return _parse_ddg(r.text, num)
        except Exception:
            pass
        return []

    async def google_fallback() -> list[dict]:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "es-ES,es;q=0.9",
            }
            url = f"https://www.google.com/search?q={quote_plus(query)}&hl=es"
            async with httpx.AsyncClient(timeout=8, follow_redirects=True) as c:
                r = await c.get(url, headers=headers)
                if r.status_code == 200:
                    return _parse_google(r.text, num)
        except Exception:
            pass
        return []

    # Ejecutar ambas busquedas en paralelo
    ddg_results, google_results = await asyncio.gather(ddg(), google_fallback())

    for r in ddg_results + google_results:
        url = r.get("url", "") or r.get("title", "")
        if url not in seen_urls and url.strip():
            seen_urls.add(url)
            results.append(r)
        if len(results) >= num:
            break

    return results


def _parse_ddg(html: str, num: int) -> list[dict]:
    from html.parser import HTMLParser
    results: list[dict] = []
    cur = {}
    in_snippet = False

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            nonlocal in_snippet, cur
            a = dict(attrs)
            if tag == "a" and "result__a" in a.get("class", ""):
                cur["url"] = a.get("href", "")
            if tag == "a" and "result__a" in a.get("class", ""):
                cur["title"] = ""
            if tag == "span" and "result__snippet" in a.get("class", ""):
                in_snippet = True
        def handle_data(self, data):
            nonlocal cur
            if "title" in cur and cur["title"] == "":
                cur["title"] = data.strip()
            if in_snippet:
                cur["snippet"] = cur.get("snippet", "") + data
        def handle_endtag(self, tag):
            nonlocal in_snippet
            if tag == "span" and in_snippet:
                if cur.get("title"):
                    results.append(dict(cur))
                cur = {}
                in_snippet = False
    P().feed(html)
    return results[:num]


def _parse_google(html: str, num: int) -> list[dict]:
    """Extrae resultados de HTML de Google."""
    import re
    results = []
    # Buscar patrones tipicos de resultados de Google
    # div.g > div > a > h3  (titulo), div.g > div > span (snippet)
    for match in re.finditer(r'<a[^>]*href="(/url\?q=[^"&]+[^"]*)"[^>]*>(.*?)</a>', html):
        url_match = re.search(r'q=([^&]+)', match.group(1))
        url = ""
        if url_match:
            from urllib.parse import unquote
            url = unquote(url_match.group(1))
        title = re.sub(r'<[^>]+>', '', match.group(2)).strip()
        if title and url and not url.startswith("http"):
            continue
        if title and url:
            results.append({"title": title, "url": url, "snippet": "", "source": "google"})
        if len(results) >= num:
            break
    return results


# ── Modelo más rápido disponible (caché global) ─────────────────────────────
_FASTEST_MODEL: str | None = None

# Preferencia: modelos pequeños primero (más rápidos), 7B como último recurso
_MODEL_SPEED_PRIORITY = [
    "gemma2:2b", "qwen2.5:3b", "llama3.2:3b", "phi3:mini",
    "qwen2.5:7b", "llama3.1:8b", "mistral:7b", "llama3.2:1b",
    "qwen2.5:0.5b", "smollm2:360m",
]


async def _get_fastest_model() -> str:
    global _FASTEST_MODEL
    if _FASTEST_MODEL:
        return _FASTEST_MODEL
    try:
        import httpx
        async with httpx.AsyncClient(timeout=2) as c:
            r = await c.get("http://localhost:11434/api/tags")
            if r.status_code == 200:
                installed = {m["name"] for m in r.json().get("models", [])}
                for candidate in _MODEL_SPEED_PRIORITY:
                    if candidate in installed or any(candidate in n for n in installed):
                        _FASTEST_MODEL = candidate
                        logger.info(f"Modelo seleccionado: {_FASTEST_MODEL}")
                        return _FASTEST_MODEL
                # Si no hay ninguno conocido, usar el primero disponible
                if installed:
                    _FASTEST_MODEL = next(iter(installed))
                    return _FASTEST_MODEL
    except Exception:
        pass
    return "qwen2.5:7b"


async def _warmup_ollama():
    """Pre-carga el modelo en memoria para que la primera respuesta sea rápida."""
    try:
        import httpx
        model = await _get_fastest_model()
        async with httpx.AsyncClient(timeout=30) as c:
            await c.post("http://localhost:11434/api/chat", json={
                "model": model,
                "messages": [{"role": "user", "content": "hola"}],
                "stream": False,
                "options": {"num_predict": 1},
            })
        logger.info(f"Modelo {model} pre-cargado en memoria")
    except Exception:
        pass


async def _buscar_en_api_colombia(message: str) -> list[str]:
    """Consulta APIs directas colombianas incluyendo IGAC."""
    from geoia.websearch.api_colombia import search_all_apis
    try:
        return await search_all_apis(message)
    except Exception:
        return []


class ChatbotEngine:
    def __init__(self):
        self.sessions: dict[str, list[dict]] = {}
        self.spatial_data: dict[str, dict | None] = {}

    def set_spatial_data(self, session_id: str, geojson: dict | None):
        self.spatial_data[session_id] = geojson

    def get_spatial_data(self, session_id: str) -> dict | None:
        return self.spatial_data.get(session_id)

    async def _call_ollama(self, messages: list[dict]) -> str:
        from geoia.core.llm import get_llm
        llm = get_llm()
        if llm and hasattr(llm, 'chat'):
            try:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, llm.chat, messages, 600)
            except Exception:
                pass
        try:
            import httpx
            async with httpx.AsyncClient(timeout=25) as client:
                r = await client.post(
                    "http://localhost:11434/api/chat",
                    json={"model": await _get_fastest_model(), "messages": messages, "stream": False,
                          "options": {"num_predict": 300, "temperature": 0.3, "num_ctx": 2048,
                                      "num_thread": 0, "num_gpu": 99, "top_k": 20}},
                )
                if r.status_code == 200:
                    return r.json().get("message", {}).get("content", "")
        except Exception:
            pass
        return ""

    async def chat(self, message: str, session_id: str = "default", geojson: dict | None = None) -> str:
        # Auto-detectar coordenadas en el mensaje si no viene geojson explícito
        if not geojson:
            geojson = _detectar_coordenadas(message)
        if geojson:
            self.set_spatial_data(session_id, geojson)
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        self.sessions[session_id].append({"role": "user", "content": message})
        respuesta = await self._generate_response(message, self.sessions[session_id], session_id=session_id)
        self.sessions[session_id].append({"role": "assistant", "content": respuesta})
        return respuesta

    async def stream_chat(
        self, message: str, session_id: str = "default", geojson: dict | None = None
    ) -> AsyncIterator[str]:
        """Genera la respuesta token a token. Primero emite el contexto no-LLM, luego hace streaming del LLM."""
        if not geojson:
            geojson = _detectar_coordenadas(message)
        if geojson:
            self.set_spatial_data(session_id, geojson)
            yield "```geojson-point\n" + json.dumps(geojson, ensure_ascii=False) + "\n```\n\n"
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        self.sessions[session_id].append({"role": "user", "content": message})

        # ── Verificar si es cruce/WFS para delegar al método full (devuelve texto completo) ──
        categoria, _, usar_wfs = _extraer_tema(message)
        if usar_wfs and self.get_spatial_data(session_id):
            respuesta = await self._generate_response(message, self.sessions[session_id], session_id=session_id)
            self.sessions[session_id].append({"role": "assistant", "content": respuesta})
            yield respuesta
            return

        # ── Respuesta rápida por keywords (sin LLM) ──
        from geoia.core.llm import _responder
        rapida = _responder(message)
        if rapida:
            self.sessions[session_id].append({"role": "assistant", "content": rapida})
            yield rapida
            return

        # ── System prompt base — arranca streaming INMEDIATAMENTE ──
        system = (
            "Eres Nymaira, experta en catastro colombiano y SIG. "
            "Respondes siempre en español, de forma clara y concisa (máx 250 palabras). "
            "Usas emojis con moderación. "
            "Conoces: IGAC Base Catastral 10-2025, Resolución IGAC 1040/2023, SNRP, UPRA, IDEAM, "
            "servidores WFS/WMS colombianos, normativa de catastro multipropósito. "
            "Si hay coordenadas en el mensaje, ofrece visualizarlas en el mapa. "
            "Sé directa y útil."
        )

        # ── Solo buscar en web si el mensaje claramente lo necesita ──
        _PALABRAS_WEB = ("resolución", "decreto", "norma", "ley ", "acuerdo", "precio",
                         "trámite", "requisito", "plazo", "2024", "2025", "2026",
                         "gobierno", "portal", "igac", "snrp", "upra")
        necesita_web = len(message) > 50 and any(p in message.lower() for p in _PALABRAS_WEB)
        if necesita_web:
            try:
                web_results = await asyncio.wait_for(_buscar_en_web(message, 3), timeout=3)
                if web_results:
                    titulos = "\n".join(f"• {r.get('title','')[:100]}" for r in web_results[:3])
                    system += f"\n\nReferencias web recientes:\n{titulos}"
            except Exception:
                pass

        history = self.sessions[session_id][-4:]
        chat_messages = [{"role": "system", "content": system}] + history

        # ── Streaming desde Ollama ──
        full_response = ""
        async for token in self._stream_ollama(chat_messages):
            full_response += token
            yield token

        if not full_response:
            fallback = self._fallback_sin_llm(message, "", [], [], [])
            self.sessions[session_id].append({"role": "assistant", "content": fallback})
            yield fallback
            return

        self.sessions[session_id].append({"role": "assistant", "content": full_response})

    async def _stream_ollama(self, messages: list[dict]) -> AsyncIterator[str]:
        """Stream tokens desde Ollama usando el modelo más rápido disponible."""
        import httpx
        model = await _get_fastest_model()
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                async with client.stream(
                    "POST",
                    "http://localhost:11434/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": True,
                        "options": {
                            "temperature": 0.3,
                            "num_predict": 300,
                            "num_ctx": 2048,
                            "num_thread": 0,   # 0 = usar todos los cores disponibles
                            "num_gpu": 99,     # offloading a GPU si existe
                            "top_k": 20,       # menos candidatos = más rápido
                            "repeat_penalty": 1.0,
                            "mirostat": 0,
                        },
                    },
                ) as response:
                    if response.status_code != 200:
                        return
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            if content:
                                yield content
                            if data.get("done"):
                                break
                        except (json.JSONDecodeError, KeyError):
                            continue
        except Exception as e:
            logger.debug(f"_stream_ollama error: {e}")

    async def _realizar_cruce_geojson(self, geojson: dict, message: str, categoria: str) -> str | None:
        """Toma un GeoJSON cargado, consulta WFS relevante en su bbox y hace overlay real."""
        import json
        try:
            import geopandas as gpd
            from geoia.websearch.wfs_colombia import listar_servidores, wfs_get_capabilities, wfs_get_features
        except ImportError:
            logger.warning("_realizar_cruce_geojson: geopandas no disponible")
            return None

        features = geojson.get("features", [])
        if not features:
            logger.warning("_realizar_cruce_geojson: sin features")
            return None

        try:
            gdf_user = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
            if gdf_user.empty:
                logger.warning("_realizar_cruce_geojson: GeoDataFrame vacio")
                return None
            minx, miny, maxx, maxy = gdf_user.total_bounds
            area_m2 = float(gdf_user.to_crs("EPSG:3857").area.sum())
            area_ha = area_m2 / 10_000
            if area_ha > 100_000:
                logger.info(f"_realizar_cruce_geojson: area muy grande ({area_ha:.0f} ha)")
                return None
        except Exception as e:
            logger.warning(f"_realizar_cruce_geojson: error parsing: {e}")
            return None

        # ── Priorizar servidores WFS según la categoría y keywords ──
        servidores = listar_servidores(categoria)
        if not servidores:
            servidores = listar_servidores()
        
        # Ordenar por relevancia: primero los de la misma categoría, luego por keywords
        def score_servidor(srv):
            score = 0
            if srv.get("categoria") == categoria:
                score += 10
            name = (srv.get("nombre", "") + srv.get("descripcion", "")).lower()
            keywords = {
                "catastral": ["catastro", "matricula", "predio", "lindero", "avaluo", "geoportal", "igac"],
                "ambiental": ["ideam", "ambiente", "ecosistema", "parque", "area protegida", "bosque"],
                "productiva": ["upra", "agricultura", "rural", "suelo", "aptitud"],
            }.get(categoria, [])
            for kw in keywords:
                if kw in name:
                    score += 5
            return score
        
        servidores = sorted(servidores, key=score_servidor, reverse=True)[:6]
        logger.info(f"_realizar_cruce_geojson: probando {len(servidores)} servidores ({categoria}), bbox={minx:.2f},{miny:.2f},{maxx:.2f},{maxy:.2f}")

        async def consultar_capas(srv):
            url = srv.get("url_wfs", "")
            if not url:
                return None
            try:
                caps = await asyncio.wait_for(wfs_get_capabilities(url), timeout=5)
                if "error" in caps:
                    logger.debug(f"  {srv['nombre']}: error capabilities: {caps.get('error','')[:50]}")
                    return None
                capas = caps.get("capas", [])
                if not capas:
                    return None
                keywords = {
                    "catastral": ["predio", "catastro", "parcela", "lote", "manzana"],
                    "ambiental": ["ecosistema", "bosque", "cuenca", "parque", "area protegida"],
                    "productiva": ["aptitud", "suelo", "cultivo", "agricola", "rural"],
                }.get(categoria, [])
                ranked = sorted(capas, key=lambda c: sum(1 for kw in keywords if kw in c.get("name","").lower()), reverse=True)
                top = ranked[0] if ranked else (capas[0] if capas else None)
                if top:
                    logger.info(f"  {srv['nombre']}: capa seleccionada = {top['name']}")
                    return {"servidor": srv, "capa": top}
                return None
            except asyncio.TimeoutError:
                logger.debug(f"  {srv['nombre']}: timeout capabilities")
                return None
            except Exception as e:
                logger.debug(f"  {srv['nombre']}: exception: {e}")
                return None

        resultados = await asyncio.gather(*[consultar_capas(s) for s in servidores], return_exceptions=True)
        resultados = [r for r in resultados if isinstance(r, dict) and r.get("capa")]

        if not resultados:
            # No hay WFS disponibles: intentar con Overpass API (OpenStreetMap)
            logger.warning(f"_realizar_cruce_geojson: todos los WFS fallaron. Intentando Overpass API...")
            try:
                from geoia.websearch.overpass_api import buscar_entidades_cercanas, overpass_to_geojson
                overpass_result = await asyncio.wait_for(
                    buscar_entidades_cercanas([minx, miny, maxx, maxy], categoria or "all", limit=50),
                    timeout=25
                )
                if overpass_result and overpass_result.get("count", 0) > 0:
                    geojson_osm = overpass_result["geojson"]
                    gdf_osm = gpd.GeoDataFrame.from_features(geojson_osm.get("features", []), crs="EPSG:4326")
                    if not gdf_osm.empty:
                        gdf_user_m = gdf_user.to_crs("EPSG:3857")
                        gdf_osm_m = gdf_osm.to_crs("EPSG:3857")
                        try:
                            result_overlay = gpd.overlay(gdf_user_m, gdf_osm_m, how="intersection")
                        except Exception:
                            result_overlay = None

                        if result_overlay is not None and not result_overlay.empty:
                            result_overlay = result_overlay.to_crs("EPSG:4326")
                            overlay_area = float(result_overlay.to_crs("EPSG:3857").area.sum())
                            overlay_count = len(result_overlay)
                            overlay_geojson = json.loads(result_overlay.to_json())
                            minx_r, miny_r, maxx_r, maxy_r = result_overlay.total_bounds
                            resumen = overpass_result.get("resumen", {})
                            resumen_str = ", ".join(f"{k}: {v}" for k, v in resumen.items()) if resumen else "varios"
                            return (
                                f"## ✅ Cruce espacial completado (fuente: OpenStreetMap)\n\n"
                                f"📄 **Tu capa**: {len(features)} geometrías ({area_ha:.1f} ha)\n"
                                f"📡 **OpenStreetMap**: {overpass_result['count']} entidades ({resumen_str})\n\n"
                                f"### 🔗 Resultado del cruce (intersección)\n"
                                f"- **{overlay_count}** geometrías resultantes\n"
                                f"- **{overlay_area:,.0f} m²** ({overlay_area/10_000:,.1f} ha | {overlay_area/1_000_000:,.2f} km²)\n\n"
                                f"### 📍 Extensión\n"
                                f"- **{minx_r:.6f}, {miny_r:.6f}** a **{maxx_r:.6f}, {maxy_r:.6f}**\n\n"
                                f"```geojson-cruce\n{json.dumps(overlay_geojson, ensure_ascii=False)}\n```\n"
                            )
            except Exception as e:
                logger.warning(f"overpass fallback failed: {e}")

            # Último fallback: servidores conocidos manualmente
            servidores_disponibles = listar_servidores()[:5]
            intentados = [s.get("nombre", "") for s in servidores[:6]]
            sugerencias = []
            for srv in servidores_disponibles:
                sugerencias.append(f"• **{srv['nombre']}** ({srv.get('categoria','')})")
            logger.warning(f"_realizar_cruce_geojson: todos los WFS y Overpass fallaron. Intentados: {intentados}")
            return (
                f"## 🌐 Cruce espacial\n\n"
                f"📄 **Tu archivo espacial está cargado** ({len(features)} geometrías, {area_ha:.1f} ha)\n\n"
                f"❌ Los servidores WFS y OpenStreetMap no respondieron este momento.\n"
                f"Servidores intentados: {', '.join(intentados)}\n\n"
                f"**Servidores disponibles que podrías usar manualmente:**\n"
                f"{'\n'.join(sugerencias[:5])}\n\n"
                f"**Para hacer el cruce:**\n"
                f"1️⃣ Ve a la pestaña **Geo IA** 🛰️\n"
                f"2️⃣ En '🇨🇴 Servicios WFS/WMS Colombia', selecciona uno de los servidores listados arriba\n"
                f"3️⃣ Consulta las capas disponibles y elige dos para cruzar\n"
                f"4️⃣ En '🌐 Cruce de Información Espacial', cárgalas y ejecuta la operación\n\n"
                f"¿Quieres que intente conectar a algún servidor específico?"
            )

        mejor = resultados[0]
        capa = mejor["capa"]
        srv = mejor["servidor"]
        logger.info(f"_realizar_cruce_geojson: consultando {srv['nombre']}/{capa['name']}")

        bbox = [minx, miny, maxx, maxy]
        result_wfs = await wfs_get_features(srv.get("url_wfs", ""), capa["name"], bbox=bbox, max_features=100)

        if "error" in result_wfs or not result_wfs.get("features"):
            logger.warning(f"_realizar_cruce_geojson: sin features WFS: {result_wfs.get('error', 'vacio')[:80]}")
            return None

        features_wfs = result_wfs["features"]
        logger.info(f"_realizar_cruce_geojson: {len(features_wfs)} features WFS obtenidas")
        gdf_wfs = gpd.GeoDataFrame.from_features(features_wfs, crs="EPSG:4326")
        if gdf_wfs.empty:
            return None

        gdf_user_m = gdf_user.to_crs("EPSG:3857")
        gdf_wfs_m = gdf_wfs.to_crs("EPSG:3857")

        try:
            result_overlay = gpd.overlay(gdf_user_m, gdf_wfs_m, how="intersection")
        except Exception as e:
            logger.warning(f"_realizar_cruce_geojson: overlay error: {e}")
            result_overlay = None

        if result_overlay is None or result_overlay.empty:
            return (
                f"## ✅ Cruce espacial completado\n\n"
                f"📄 **Tu capa**: {len(features)} geometrías, {area_ha:.1f} ha\n"
                f"📡 **{srv['nombre']}** — capa `{capa['name']}`: {len(features_wfs)} geometrías\n\n"
                f"❌ **Sin intersección** entre tu área y los datos de {srv['nombre']}.\n"
                f"Las capas no se superponen en el área solicitada."
            )

        result_overlay = result_overlay.to_crs("EPSG:4326")
        overlay_area = float(result_overlay.to_crs("EPSG:3857").area.sum())
        overlay_count = len(result_overlay)
        overlay_geojson = json.loads(result_overlay.to_json())
        minx_r, miny_r, maxx_r, maxy_r = result_overlay.total_bounds

        # ── Descripción de columnas ──
        COL_DESCRIPTIONS = {
            "id": "Identificador único para cada entidad intersectada",
            "Name": "Nombre de la entidad intersectada",
            "description": "Descripción del área o entidad intersectada",
            "timestamp": "Fecha y hora en que se realizó el corte",
            "begin": "Ubicación inicial (latitud y longitud)",
            "end": "Ubicación final (latitud y longitud)",
            "altitudeMode": "Estado de la altura del área (mayor, menor o igual a 100 metros)",
            "tessellate": "Si se está utilizando el método de corte de telescopio",
            "extrude": "Si se está utilizando el método de extrusión",
            "visibility": "Estado visual de la entidad intersectada",
            "geometry": "Geometría espacial del resultado ( punto, línea o polígono )",
        }

        # ── Construir tabla de columnas ──
        col_names = [c for c in result_overlay.columns if c != "geometry"]
        tabla_cols = ""
        for col in col_names:
            desc = COL_DESCRIPTIONS.get(col, "Campo adicional del resultado")
            tabla_cols += f"| {col} | {desc} |\n"

        # ── Construir tabla de datos (primeras 10 filas) ──
        tabla_datos = ""
        header = "| " + " | ".join(col_names) + " |"
        sep = "| " + " | ".join(["---"] * len(col_names)) + " |"
        tabla_datos += header + "\n" + sep + "\n"
        for _, row in result_overlay.head(10).iterrows():
            vals = []
            for col in col_names:
                val = str(row.get(col, ""))[:50]
                vals.append(val)
            tabla_datos += "| " + " | ".join(vals) + " |\n"

        logger.info(f"_realizar_cruce_geojson: overlay exitoso: {overlay_count} geom, {overlay_area:.0f} m2")
        return (
            f"## ✅ Cruce espacial completado con éxito\n\n"
            f"📄 **Tu capa**: {len(features)} geometrías ({area_ha:.1f} ha)\n"
            f"📡 **{srv['nombre']}** — capa `{capa['name']}`: {len(features_wfs)} geometrías\n\n"
            f"### 🔗 Resultado del cruce (intersección)\n"
            f"- **{overlay_count}** geometrías resultantes\n"
            f"- **{overlay_area:,.0f} m²** ({overlay_area/10_000:,.1f} ha | {overlay_area/1_000_000:,.2f} km²)\n\n"
            f"### 📍 Extensión\n"
            f"- **{minx_r:.6f}, {miny_r:.6f}** a **{maxx_r:.6f}, {maxy_r:.6f}**\n\n"
            f"### 📋 Columnas\n"
            f"| Columna | Descripción |\n"
            f"|---------|------------|\n"
            f"{tabla_cols}\n"
            f"### 📊 Datos (primeras {min(10, overlay_count)} filas)\n"
            f"{tabla_datos}\n"
            f"```geojson-cruce\n{json.dumps(overlay_geojson, ensure_ascii=False)}\n```\n"
        )

    def reset_session(self, session_id: str):
        self.sessions.pop(session_id, None)
        self.spatial_data.pop(session_id, None)

    async def _generate_response(self, message: str, history: list[dict], session_id: str | None = None) -> str:
        from geoia.core.llm import _responder
        eval_result = _evaluar_solicitud(message)

        # ── Respuesta inmediata si hay limitaciones (no_puede) ──
        if eval_result.get("limitaciones") and not eval_result.get("capacidades"):
            partes = [f"❌ **{cap['label']}** — {cap.get('razon', 'No disponible')}" for cap in eval_result["limitaciones"]]
            return "## 🔍 Evaluación de tu solicitud\n\n" + "\n\n".join(partes)

        categoria, directo_api, usar_wfs = _extraer_tema(message)
        session_id = session_id or "default"

        # ── 1. Busqueda en vivo (paralelo) con timeout global ──
        tasks = []
        tasks.append(asyncio.wait_for(_buscar_en_web(message, 4), timeout=5))
        if categoria:
            from geoia.websearch.colombia import search_colombia
            tasks.append(asyncio.wait_for(search_colombia(message, categoria, num_por_fuente=1), timeout=5))
        else:
            tasks.append(asyncio.sleep(0, result=[]))
        tasks.append(asyncio.wait_for(_buscar_en_wfs(categoria or "catastral", 2 if usar_wfs else 1), timeout=6))
        tasks.append(asyncio.wait_for(_buscar_en_api_colombia(message) if directo_api else asyncio.sleep(0, result=[]), timeout=5))

        # ── 2. Si es catastro directo (IGAC), buscar en IGAC ──
        if categoria == "catastral" and directo_api:
            from geoia.websearch.datos_gov_co import search_igac_datasets
            tasks.append(asyncio.wait_for(search_igac_datasets(message, categoria, limit=2), timeout=5))

        # ── 2b. Consultar RAG para normatividad catastral ──
        es_norma = any(kw in message.lower() for kw in ("resolucion", "1040", "norma", "procedimiento catastral",
                        "conservacion catastral", "formacion catastral", "actualizacion catastral",
                        "avaluo catastral", "reglamento", "decreto", "ley"))
        if es_norma:
            from geoia.rag.engine import RAGEngine
            rag = RAGEngine()
            tasks.append(asyncio.wait_for(
                asyncio.to_thread(rag.query, message, 5),
                timeout=15
            ))
        else:
            tasks.append(asyncio.sleep(0, result=None))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        web_results = results[0] if not isinstance(results[0], Exception) else []
        colombia_results = results[1] if not isinstance(results[1], Exception) else []
        wfs_lines = results[2] if not isinstance(results[2], Exception) else []
        api_results = results[3] if not isinstance(results[3], Exception) else []
        igac_results = results[4] if len(results) > 4 and not isinstance(results[4], Exception) else []
        rag_result = results[5] if len(results) > 5 and not isinstance(results[5], Exception) else None

        # ── 2. Si es cruce y tenemos datos espaciales en sesion, hacer el cruce real ──
        if usar_wfs:
            geojson_sesion = self.get_spatial_data(session_id)
            if geojson_sesion:
                try:
                    resultado_cruce = await asyncio.wait_for(
                        self._realizar_cruce_geojson(geojson_sesion, message, categoria or "catastral"),
                        timeout=60
                    )
                    if resultado_cruce:
                        return self._resumir_cruce_y_sugerir_siguientes(resultado_cruce, geojson_sesion, message)
                except asyncio.TimeoutError:
                    logger.warning("_generate_response: cruce timeout")
                    return self._responder_con_archivo_cargado(session_id)
                except Exception:
                    pass
            # Fallback: mostrar WFS disponibles
            if wfs_lines:
                respuesta = "✅ **Cruce de información espacial — conectando con servidores colombianos en vivo**\n\n"
                respuesta += "\n".join(wfs_lines[:6])
                if web_results:
                    respuesta += "\n\n**Información web relacionada:**\n"
                    for r in web_results[:3]:
                        respuesta += f"• {r.get('title', '')[:100]}\n"
                if api_results:
                    respuesta += "\n**Datos de APIs directas:**\n"
                    for r in api_results[:3]:
                        respuesta += f"• {r.get('title', '')[:100]}\n"
                respuesta += (
                    "\n\n📌 **Para hacer el cruce:**\n"
                    "1️⃣ Ve a la pestaña **Geo IA** 🛰️\n"
                    "2️⃣ En '🇨🇴 Servicios WFS/WMS Colombia', selecciona un servidor y haz clic en Conectar\n"
                    "3️⃣ Consulta las capas disponibles y elige dos para cruzar\n"
                    "4️⃣ En '🌐 Cruce de Información Espacial', cárgalas y ejecuta la operación\n\n"
                    "¿Quieres que intente conectar a algún servidor específico?"
                )
                return respuesta

            # Sin WFS disponible y sin cruce real: mensaje util
            if self.get_spatial_data(session_id):
                return self._responder_con_archivo_cargado(session_id)

        # ── 3. Respuesta rápida si hay keywords conocidos (y no es cruce) ──
        rapida = _responder(message)
        if rapida:
            return rapida

        # ── 4. Procesamiento QGIS (buffer, clip, centroides, etc.) ──
        msg_lower = message.lower()
        if self.get_spatial_data(session_id) and any(kw in msg_lower for kw in ("buffer", "centroid", "disolver", "dissolve", "reproyect", "simplif", "fix")):
            geojson_sesion = self.get_spatial_data(session_id)
            if geojson_sesion:
                try:
                    from geoia.geo.processing import buffer as qgis_buffer, centroids as qgis_centroids, dissolve as qgis_dissolve, reproject as qgis_reproject, fix_geometries as qgis_fix, simplify_geometries as qgis_simplify, qgis_available
                    if qgis_available():
                        result = None
                        if "buffer" in msg_lower:
                            import re as _re2
                            m = _re2.search(r"(\d+)\s*m", msg_lower)
                            dist = float(m.group(1)) if m else 100
                            result = qgis_buffer(geojson_sesion, dist)
                        elif "centroid" in msg_lower:
                            result = qgis_centroids(geojson_sesion)
                        elif "disolver" in msg_lower or "dissolve" in msg_lower:
                            result = qgis_dissolve(geojson_sesion)
                        elif "reproyect" in msg_lower:
                            result = qgis_reproject(geojson_sesion)
                        elif "simplif" in msg_lower:
                            result = qgis_simplify(geojson_sesion)

                        if result and "error" not in result:
                            feat_count = len(result.get("features", 0))
                            block = "```geojson-result\n" + json.dumps(result, ensure_ascii=False) + "\n```"
                            return (f"## ✅ Procesamiento QGIS completado\n\n"
                                    f"Operación aplicada a tu capa: **{feat_count}** geometrías resultantes\n\n{block}")
                except ImportError:
                    pass
                except Exception as e:
                    logger.warning(f"QGIS processing failed: {e}")

        # ── 5. Construir contexto para LLM ──
        contexto_piezas: list[str] = []
        if web_results:
            contexto_piezas.append("**Resultados web:**")
            for r in web_results[:4]:
                contexto_piezas.append(f"• {r.get('title','')[:100]}")

        if colombia_results:
            contexto_piezas.append(f"\n**Fuentes Colombia ({categoria or 'general'}):**")
            for r in colombia_results[:4]:
                contexto_piezas.append(f"• {r.get('title','')[:100]} — {r.get('snippet','')[:100]}")

        if wfs_lines:
            contexto_piezas.append("\n**WFS:**")
            contexto_piezas.extend(wfs_lines[:4])

        if api_results:
            contexto_piezas.append("\n**APIs:**")
            for r in api_results[:3]:
                contexto_piezas.append(f"• {r.get('title','')[:100]}")

        if igac_results:
            contexto_piezas.append("\n**IGAC - Catastro Nacional:**")
            for r in igac_results[:3]:
                contexto_piezas.append(f"• {r.get('title','')[:100]}")

        if rag_result and rag_result.get("answer") and "No hay documentos" not in rag_result["answer"] and "No se encontr" not in rag_result["answer"]:
            contexto_piezas.append("\n**Normatividad catastral (documentos indexados):**")
            contexto_piezas.append(f"• {rag_result['answer'][:500]}")
            contexto_piezas.append(f"  Fuentes: {', '.join(rag_result.get('sources', []))}")

        contexto = "\n".join(contexto_piezas)

        # ── 6. Si hay RAG con normatividad, responder directamente ──
        if rag_result and rag_result.get("answer") and "No hay documentos" not in rag_result["answer"] and "No se encontr" not in rag_result["answer"]:
            parts = [f"## ⚖️ Según la normatividad catastral\n\n{rag_result['answer'][:1000]}"]
            if rag_result.get("sources"):
                parts.append(f"\n\n📄 **Fuentes:** {', '.join(rag_result['sources'])}")
            if contexto.strip():
                parts.append(f"\n\n---\n{contexto[:800]}")
            return "\n".join(parts)

        # ── 7. LLM con contexto real ──
        prompt = (
            "Eres Nymaira, experta en catastro colombiano y Sistemas de Información Geográfica (SIG). "
            "Respondes SIEMPRE en español, de forma clara, estructurada y precisa. "
            "Usas encabezados markdown (##, ###), listas con •, y emojis temáticos cuando ayudan a la claridad.\n\n"
            "Capacidades integradas:\n"
            "• QGIS: buffer, clip, dissolve, centroides, reproyectar, simplificar\n"
            "• IGAC Base Catastral Nacional 10-2025: predios, avalúos, geometrías\n"
            "• WFS/WMS colombianos: IGAC, IDEAM, UPRA, ANH, ANM en vivo\n"
            "• RAG sobre Resolución 1040 de 2023 y normatividad catastral\n"
            "• Detección automática de coordenadas en el chat\n\n"
            "Si el usuario pega coordenadas, las detectas y ofreces mostrarlas en el mapa. "
            "Si hay datos espaciales cargados, los analizas. "
            "Máx 400 palabras. Responde al punto, sin relleno."
        )
        if contexto.strip():
            prompt += "\n\nDatos en vivo:\n" + contexto[:2000]

        chat_messages = [{"role": "system", "content": prompt}] + history[-6:]
        ollama_resp = await self._call_ollama(chat_messages)

        if ollama_resp:
            resp = ollama_resp[:1000]
            if contexto.strip():
                resp += "\n\n---\n" + contexto[:1000]
            return resp

        # ── 7. Fallback inteligente sin LLM ──
        return self._fallback_sin_llm(message, contexto, wfs_lines, colombia_results, web_results)

    def _fallback_sin_llm(self, message: str, contexto: str, wfs_lines: list, colombia: list, web: list) -> str:
        """Respuesta útil cuando Ollama no está disponible."""
        m = message.lower()
        partes: list[str] = []

        # Detectar tema y dar respuesta dirigida
        if any(w in m for w in ("catastro", "matricula", "avaluo", "predio", "lindero")):
            partes.append(
                "## 🏛️ Información catastral\n\n"
                "Para consultas catastrales en Colombia puedes:\n\n"
                "- **IGAC** — [geoportal.igac.gov.co](https://geoportal.igac.gov.co) para consulta de predios\n"
                "- **SNRP** — portal de la Supernotariado para matrícula inmobiliaria\n"
                "- **Catastro municipal** — oficina del municipio correspondiente\n\n"
                "¿Quieres que busque información específica en fuentes oficiales?"
            )
        elif any(w in m for w in ("buffer", "capa", "cruce", "spatial", "geojson", "shapefile", "kml")):
            partes.append(
                "## 🗺️ Análisis espacial\n\n"
                "Carga tu archivo en el chat (📎) y puedo:\n"
                "- Cruzarlo con capas WFS colombianas (IGAC, UPRA, IDEAM)\n"
                "- Calcular área, perímetro y centroides\n"
                "- Hacer buffer, dissolve o reproyección con QGIS\n\n"
                "¿Qué operación necesitas realizar?"
            )
        elif any(w in m for w in ("norma", "resolucion", "ley", "decreto", "1040", "procedimiento")):
            partes.append(
                "## ⚖️ Normatividad catastral\n\n"
                "La normatividad catastral colombiana principal incluye:\n\n"
                "- **Resolución IGAC 1040 de 2023** — procedimientos de formación, actualización y conservación catastral\n"
                "- **Ley 1955 de 2019** — Plan Nacional de Desarrollo, catastro multipropósito\n"
                "- **Decreto 148 de 2020** — operadores catastrales habilitados\n\n"
                "Sube documentos en la pestaña **Documentos** para consultarlos directamente."
            )
        else:
            partes.append(
                f"## 💬 Respuesta a tu consulta\n\n"
                f"Recibí tu pregunta sobre: *{message[:120]}*\n\n"
                "En este momento el modelo de lenguaje local no está disponible. "
                "Para activarlo, instala y ejecuta **Ollama** con el comando:\n"
                "```\nollama run qwen2.5:7b\n```\n\n"
                "Mientras tanto puedo ayudarte con búsquedas en fuentes oficiales. ¿Qué información necesitas?"
            )

        if web:
            partes.append("\n## 🌐 Resultados web relacionados")
            for r in web[:3]:
                t = r.get("title", "")[:100]
                u = r.get("url", "")
                partes.append(f"- [{t}]({u})" if u else f"- {t}")

        if colombia:
            partes.append("\n## 🇨🇴 Fuentes oficiales colombianas")
            for r in colombia[:3]:
                partes.append(f"- {r.get('title','')[:100]}")

        if wfs_lines:
            partes.append("\n## 📡 Servidores WFS disponibles")
            partes.extend(wfs_lines[:3])

        return "\n\n".join(partes)

    def _responder_con_archivo_cargado(self, session_id: str) -> str:
        """Responder cuando hay archivo espacial cargado pero no hay WFS disponibles."""
        geojson = self.get_spatial_data(session_id)
        if not geojson:
            return "## 🌐 Cruce espacial\n\nNo hay archivo espacial en la sesión."

        features = geojson.get("features", [])
        if not features:
            return "## 🌐 Cruce espacial\n\nEl archivo espacial no tiene geometrías."

        # Calcular estadísticas básicas
        try:
            import geopandas as gpd
            gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
            minx, miny, maxx, maxy = gdf.total_bounds
            area_m2 = float(gdf.to_crs("EPSG:3857").area.sum())
            area_ha = area_m2 / 10_000
            count = len(gdf)
        except Exception:
            count = len(features)
            area_ha = 0

        return (
            "## 🌐 Cruce espacial\n\n"
            f"📄 **Tu archivo espacial está cargado** ({count} geometrías, {area_ha:.1f} ha)\n\n"
            "Los servidores WFS colombianos no respondieron (pueden estar lentos o fuera de servicio). "
            "Esto es temporal — los servidores gubernamentales a veces tardan.\n\n"
            "**Opciones:**\n"
            "1️⃣ **Intentar de nuevo** — Espera unos segundos y vuelve a enviar tu consulta\n"
            "2️⃣ **Ver en mapa** — Ir a la pestaña **Geo IA** 🛰️ para ver tu archivo en el mapa\n"
            "3️⃣ **Cruce manual** — En Geo IA, selecciona un servidor WFS y conecta manualmente\n"
            "4️⃣ **Preguntar** — Hazme preguntas sobre el área de tu archivo (catastro, ambiental, etc.)\n\n"
            "¿Qué prefieres hacer?"
        )

    def _resumir_cruce_y_sugerir_siguientes(self, resultado_cruce: str, geojson: dict, mensaje_original: str) -> str:
        """Resumir resultado de cruce y sugerir próximos pasos."""
        import re

        # Extraer información del resultado
        lines = resultado_cruce.split('\n')
        count_line = None
        area_line = None

        for line in lines:
            if '**geometrías resultantes**' in line:
                count_line = line
            elif '**m²** (' in line and 'ha' in line:
                area_line = line

        if not count_line:
            m = re.search(r'(\d+)\s+geometrías? resultantes', resultado_cruce)
            if m:
                count_line = f"- **{m.group(1)}** geometrías resultantes"

        if not area_line:
            m = re.search(r'(\d+,?\d*\s+m²)\s+\(([^)]+)\s+ha\s+\|\s+([^)]+)\s+km²\)', resultado_cruce)
            if m:
                area_line = f"- **{m.group(1)}** ({m.group(2)} ha | {m.group(3)} km²)"

        # Construir respuesta conversacional
        respuesta = resultado_cruce.split("```geojson-cruce")[0]

        respuesta += (
            "\n**¿Qué quieres hacer ahora?**\n"
            "• 📊 Calcular área, perímetro o centroides de la intersección\n"
            "• 🗺️ Ver el resultado en el mapa (ya está listo para dibujar)\n"
            "• 🔍 Consultar información adicional sobre las entidades intersectadas\n"
            "• 📋 Exportar el GeoJSON para usar en otro software\n"
            "• 🌐 Intentar cruzar con otra capa (¿tienes otra capa espacial?)\n\n"
            "¿Qué prefieres hacer?"
        )

        if '```geojson-cruce' in resultado_cruce:
            respuesta += "\n\n📎 El cruce incluye GeoJSON que se puede descargar o ver en el mapa."

        return respuesta
