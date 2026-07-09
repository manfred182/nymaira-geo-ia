"""Chatbot engine with real-time spatial analysis, multi-source search, and capability evaluation."""

from __future__ import annotations
import asyncio, json, logging, re
from typing import AsyncIterator

logger = logging.getLogger(__name__)


# ── Red de seguridad contra degeneración por repetición del LLM ───────
# Colapsa una frase (palabra o grupo de palabras) que se repite de forma
# consecutiva: "de uso público de uso público de uso público" → "de uso público".
_REP_RE = re.compile(r'(\b.{3,60}?\s)(?:\1){2,}', re.DOTALL)
_REP_PALABRA_RE = re.compile(r'\b(\w{2,})(?:\s+\1\b){2,}', re.IGNORECASE)


def _colapsar_repeticiones(texto: str) -> str:
    """Elimina bucles de frases/palabras repetidas que produce un LLM al degenerar."""
    if not texto:
        return texto
    previo = None
    # Aplicar varias pasadas porque un colapso puede destapar otro anidado.
    while previo != texto:
        previo = texto
        texto = _REP_RE.sub(lambda m: m.group(1), texto)
        texto = _REP_PALABRA_RE.sub(lambda m: m.group(1), texto)
    return texto


def _hay_repeticion_degenerada(texto: str, ventana: int = 400) -> bool:
    """True si el final del texto está atrapado en un bucle de repetición."""
    cola = texto[-ventana:]
    return bool(_REP_RE.search(cola) or _REP_PALABRA_RE.search(cola))


# El sistema añade las fuentes REALES al final; el modelo no debe escribir URLs
# (los modelos pequeños inventan enlaces). Esto limpia cualquiera que se cuele.
_URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)


def _sin_urls_inventadas(texto: str) -> str:
    """Quita URLs y líneas 'Fuente/Referencia: http...' generadas por el modelo."""
    if not texto:
        return texto
    lineas = []
    for ln in texto.splitlines():
        bajo = ln.strip().lower()
        if _URL_RE.search(ln) and (bajo.startswith(("fuente", "referencia", "enlace", "url", "http", "nota")) or "http" in bajo):
            continue  # descartar la línea entera de cita inventada
        lineas.append(_URL_RE.sub("", ln))
    return "\n".join(lineas).rstrip()


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


# ── System prompts ───────────────────────────────────────────────

def _build_system_prompt(community_mode: bool = False, contexto_extra: str = "") -> str:
    """Construye el system prompt del LLM. Modo normal = técnico (sin cambios de comportamiento).
    Modo comunidad = lenguaje simple para personas sin formación técnica."""
    if community_mode:
        prompt = (
            "Eres Nymaira, una asistente que ayuda a la gente del común a entender temas de "
            "catastro (los terrenos, sus medidas, sus dueños) y de medio ambiente en Colombia. "
            "Respondes SIEMPRE en español.\n\n"
            "Cómo hablar:\n"
            "• Usa palabras cotidianas, evita tecnicismos.\n"
            "• Si necesitas usar una sigla o palabra técnica (IGAC, WFS, avalúo, lindero, POT, "
            "licencia ambiental, etc.), explícala la primera vez entre paréntesis con una frase muy simple.\n"
            "• Escribe oraciones cortas. Evita párrafos largos.\n"
            "• Usa ejemplos o comparaciones cotidianas cuando ayuden (ej: comparar un avalúo con "
            "\"lo que el gobierno dice que vale tu terreno\").\n"
            "• Máximo 220 palabras.\n"
            "• Siempre que sea posible, termina con un paso concreto que la persona puede hacer, "
            "y una pregunta amable ofreciendo aclarar dudas.\n"
            "• No inventes datos legales ni cifras; si no tienes la información exacta, dilo con "
            "honestidad y recomienda verificar con la entidad oficial (IGAC, autoridad ambiental "
            "regional, alcaldía).\n\n"
            "Tienes acceso a las mismas capacidades de siempre, pero descritas de forma simple si las "
            "mencionas: puedes revisar mapas y planos (QGIS), consultar la información oficial de "
            "terrenos del gobierno (IGAC), conectarte a servicios de mapas en línea del gobierno "
            "(WFS/WMS) y buscar en documentos y normas ya guardados (RAG)."
        )
    else:
        prompt = (
            "Eres Nymaira, experta en CATASTRO MULTIPROPÓSITO de Colombia y Sistemas de "
            "Información Geográfica (SIG). Tu enfoque principal es el catastro; complementas con "
            "análisis ambiental y productivo cuando aportan al catastro. "
            "Respondes SIEMPRE en español con lenguaje claro, preciso e inclusivo. "
            "Usas encabezados markdown (##, ###), listas con •, y emojis temáticos.\n\n"
            "DATOS FIJOS (no los contradigas):\n"
            "• La Resolución 1040 de 2023 es del IGAC y regula el PROCESO CATASTRAL con enfoque "
            "MULTIPROPÓSITO (formación, actualización y conservación catastral, avalúos, gestores "
            "catastrales). NO trata de geología, ni de 'regiones económicas', ni de censos agrarios.\n"
            "• El IGAC es la autoridad catastral nacional; los gestores catastrales operan el catastro.\n\n"
            "Capacidades integradas:\n"
            "• QGIS: buffer, clip, dissolve, centroides, reproyectar, simplificar\n"
            "• IGAC Base Catastral Nacional: predios, avalúos, geometrías\n"
            "• WFS/WMS colombianos: IGAC, IDEAM, UPRA, ANH, ANM en vivo\n"
            "• RAG sobre el texto real de la Resolución 1040 de 2023\n"
            "• Búsqueda web en vivo con fuentes oficiales colombianas\n\n"
            "REGLAS:\n"
            "1. Sé CONCISA y DIRECTA: al punto, sin relleno. Máx 300 palabras.\n"
            "2. NO INVENTES. Usa solo los datos del contexto (RAG/web) y los DATOS FIJOS. Si no "
            "tienes la información, dilo con honestidad y recomienda verificar con el IGAC. Jamás "
            "inventes nombres de leyes, siglas, artículos ni cifras.\n"
            "3. NO ESCRIBAS URLs ni enlaces tú misma; el sistema añade las fuentes reales al final. "
            "Nunca inventes direcciones web.\n"
            "4. NUNCA repitas frases ni palabras; cada idea una sola vez."
        )
    if contexto_extra:
        prompt += contexto_extra
    return prompt


# ── Modelo más rápido disponible (caché global) ─────────────────────────────
_FASTEST_MODEL: str | None = None

# Preferencia: equilibrio calidad/velocidad. El 0.5b es más rápido pero alucina
# en temas normativos; 1.5b es el mejor balance en CPU. Si se quiere más precisión
# (más lento), poner "qwen2.5:3b" de primero.
_MODEL_SPEED_PRIORITY = [
    "qwen2.5:1.5b", "qwen2.5:3b", "qwen2.5:0.5b", "llama3.2:1b",
    "llama3.2:3b", "phi3:mini", "gemma2:2b",
    "qwen2.5:7b", "llama3.1:8b", "mistral:7b",
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
    return "qwen2.5:1.5b"


# Modelo para consultas normativas/catastrales. En este equipo (4 núcleos, sin GPU,
# RAM justa) se prioriza el 1.5b: con el RAG sembrado responde FUNDAMENTADO (preciso)
# y ~2x más rápido que el 3b, y al ser el mismo modelo del chat casual no hay recarga
# (con OLLAMA_MAX_LOADED_MODELS=1). Para más profundidad a costa de velocidad, poner
# "qwen2.5:3b" de primero. Nunca usar 7b aquí (satura la RAM).
_QUALITY_MODEL: str | None = None
_MODEL_QUALITY_PRIORITY = ["qwen2.5:1.5b", "qwen2.5:3b", "llama3.2:3b"]


async def _get_quality_model() -> str:
    global _QUALITY_MODEL
    if _QUALITY_MODEL:
        return _QUALITY_MODEL
    try:
        import httpx
        async with httpx.AsyncClient(timeout=2) as c:
            r = await c.get("http://localhost:11434/api/tags")
            if r.status_code == 200:
                installed = {m["name"] for m in r.json().get("models", [])}
                for candidate in _MODEL_QUALITY_PRIORITY:
                    if candidate in installed or any(candidate in n for n in installed):
                        _QUALITY_MODEL = candidate
                        logger.info(f"Modelo de calidad: {_QUALITY_MODEL}")
                        return _QUALITY_MODEL
    except Exception:
        pass
    return await _get_fastest_model()


async def _warmup_ollama():
    """Pre-carga en memoria SOLO el modelo rápido. En equipos con poca RAM se usa
    OLLAMA_MAX_LOADED_MODELS=1, así que precargar también el 3B solo lo expulsaría;
    el 3B se carga bajo demanda en la primera consulta normativa."""
    import httpx
    modelos = []
    try:
        modelos.append(await _get_fastest_model())
    except Exception:
        return
    for model in modelos:
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                await c.post("http://localhost:11434/api/chat", json={
                    "model": model,
                    "messages": [{"role": "user", "content": "hola"}],
                    "stream": False,
                    "keep_alive": -1,
                    "options": {"num_predict": 1, "num_ctx": 4096},
                })
            logger.info(f"Modelo {model} pre-cargado (keep_alive permanente)")
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
        # Memoria entre sesiones: restaurar el historial persistido en disco.
        try:
            from geoia.chatbot.memory import get_memory
            self._memory = get_memory()
            self.sessions: dict[str, list[dict]] = self._memory.load_sessions()
        except Exception as e:
            logger.warning(f"Memoria no disponible, arrancando en blanco: {e}")
            self._memory = None
            self.sessions = {}
        self.spatial_data: dict[str, dict | None] = {}

    def _persistir(self) -> None:
        """Guarda el historial en disco (best-effort; nunca rompe el chat)."""
        if self._memory:
            try:
                self._memory.persist_sessions(self.sessions)
            except Exception:
                pass

    def _registrar_pregunta(
        self, session_id: str, message: str, categoria: str | None,
        es_norma: bool, grounded: bool, n_sources: int,
    ) -> None:
        """Registra la consulta para el análisis posterior (best-effort)."""
        if self._memory:
            try:
                self._memory.log_question(
                    session_id, message, categoria, es_norma, grounded, n_sources
                )
            except Exception:
                pass

    async def _aprender_qa(self, message: str, respuesta: str, titulos: list[str]) -> None:
        """Guarda en el RAG un par pregunta+respuesta fundamentado (best-effort)."""
        try:
            from geoia.api.routes.rag import get_engine as get_rag_engine
            rag = await get_rag_engine()
            await asyncio.to_thread(rag.add_learned_qa, message, respuesta, titulos)
        except Exception as e:
            logger.debug(f"No se pudo aprender Q&A: {e}")

    def set_spatial_data(self, session_id: str, geojson: dict | None):
        self.spatial_data[session_id] = geojson

    def get_spatial_data(self, session_id: str) -> dict | None:
        return self.spatial_data.get(session_id)

    async def _call_ollama(self, messages: list[dict]) -> str:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    "http://localhost:11434/api/chat",
                    json={"model": await _get_fastest_model(), "messages": messages, "stream": False,
                          "keep_alive": -1,
                          "options": {"num_predict": 640, "temperature": 0.2, "num_ctx": 4096,
                                      "num_thread": 4, "num_gpu": 99, "top_k": 40, "top_p": 0.85,
                                      "repeat_penalty": 1.2, "repeat_last_n": 320,
                                      "frequency_penalty": 0.6, "presence_penalty": 0.3}},
                )
                if r.status_code == 200:
                    data = r.json()
                    if "error" in data:
                        logger.warning(f"Ollama error in response: {data['error']}")
                        return ""
                    return _colapsar_repeticiones(data.get("message", {}).get("content", ""))
                else:
                    logger.warning(f"Ollama HTTP {r.status_code}: {r.text[:300]}")
        except Exception as e:
            logger.debug(f"_call_ollama error: {e}")
        return ""

    async def chat(
        self, message: str, session_id: str = "default", geojson: dict | None = None,
        community_mode: bool = False,
    ) -> str:
        # Auto-detectar coordenadas en el mensaje si no viene geojson explícito
        if not geojson:
            geojson = _detectar_coordenadas(message)
        if geojson:
            self.set_spatial_data(session_id, geojson)
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        self.sessions[session_id].append({"role": "user", "content": message})
        respuesta = await self._generate_response(
            message, self.sessions[session_id], session_id=session_id, community_mode=community_mode
        )
        self.sessions[session_id].append({"role": "assistant", "content": respuesta})
        self._persistir()
        return respuesta

    async def _contexto_para_stream(
        self, message: str, categoria: str | None, es_norma: bool
    ) -> tuple[str, str, dict]:
        """Búsqueda ACOTADA (web + fuentes oficiales + RAG) para fundamentar la
        respuesta del streaming. Devuelve (contexto, bloque_de_fuentes, meta)
        donde meta indica cuántas fuentes reales (rag/web/oficiales) se usaron."""
        # Timeouts recortados para minimizar el tiempo-hasta-primer-token: las
        # búsquedas corren en paralelo (gather), así que el bloqueo real es el
        # MÁXIMO de ellas. El RAG es local y responde <1s; la web es lo más lento.
        tasks = [asyncio.wait_for(_buscar_en_web(message, 4), timeout=1.8)]

        if categoria:
            from geoia.websearch.colombia import search_colombia
            tasks.append(asyncio.wait_for(search_colombia(message, categoria, num_por_fuente=1), timeout=1.8))
        else:
            tasks.append(asyncio.sleep(0, result=[]))

        # Consultar RAG para CUALQUIER tema catastral (no solo si menciona "norma"):
        # la base tiene la 1040, la Ley 2294 y la guía oficial de catastro multipropósito.
        if es_norma or categoria == "catastral":
            try:
                from geoia.api.routes.rag import get_engine as get_rag_engine
                rag = await get_rag_engine()
                # generar=False: solo recuperación (rápida, local); sin llamada LLM interna.
                tasks.append(asyncio.wait_for(asyncio.to_thread(rag.query, message, 6, False), timeout=2.5))
            except Exception:
                tasks.append(asyncio.sleep(0, result=None))
        else:
            tasks.append(asyncio.sleep(0, result=None))

        res = await asyncio.gather(*tasks, return_exceptions=True)
        web = res[0] if not isinstance(res[0], Exception) else []
        col = res[1] if not isinstance(res[1], Exception) else []
        rag_result = res[2] if not isinstance(res[2], Exception) else None

        piezas: list[str] = []
        fuentes: list[dict] = []
        if web:
            piezas.append("🌐 Web:")
            for r in web[:4]:
                t = r.get('title', '')[:120]; u = r.get('url', ''); s = r.get('snippet', '')[:150]
                piezas.append(f"• {t} — {s}")
                if u:
                    fuentes.append({"title": t, "url": u})
        if col:
            piezas.append(f"\n🇨🇴 Fuentes oficiales ({categoria}):")
            for r in col[:4]:
                t = r.get('title', '')[:100]; u = r.get('url', ''); s = r.get('snippet', '')[:120]
                piezas.append(f"• {t} — {s}")
                if u and not any(f['url'] == u for f in fuentes):
                    fuentes.append({"title": t, "url": u})
        if rag_result and rag_result.get("chunks"):
            piezas.append("\n⚖️ Normatividad (Resolución 1040/2023):")
            for ch in rag_result.get("chunks", [])[:4]:
                piezas.append(f"• {ch[:220]}...")
            for s in rag_result.get("sources", []):
                if s and s not in [f['title'] for f in fuentes]:
                    fuentes.append({"title": s, "url": ""})

        n_rag = len(rag_result.get("chunks", [])) if (rag_result and isinstance(rag_result, dict)) else 0
        logger.info(f"_contexto_para_stream: web={len(web)} colombia={len(col)} rag_chunks={n_rag} "
                    f"contexto_chars={sum(len(p) for p in piezas)}")

        contexto = "\n".join(piezas)
        fuentes_block = ""
        if fuentes:
            lineas = ["**🌐 Fuentes consultadas**"]
            for f in fuentes[:6]:
                lineas.append(f"• [{f['title'][:80]}]({f['url']})" if f['url'] else f"• {f['title'][:80]}")
            fuentes_block = "\n".join(lineas)
        meta = {
            "n_rag": n_rag, "n_web": len(web), "n_col": len(col),
            "n_fuentes": len(fuentes),
            "titulos_fuentes": [f["title"] for f in fuentes[:6]],
        }
        return contexto, fuentes_block, meta

    async def stream_chat(
        self, message: str, session_id: str = "default", geojson: dict | None = None,
        community_mode: bool = False,
    ) -> AsyncIterator[str]:
        """Genera la respuesta token a token. Streaming inmediato sin esperar búsquedas."""
        if not geojson:
            geojson = _detectar_coordenadas(message)
        if geojson:
            self.set_spatial_data(session_id, geojson)
            yield "```geojson-point\n" + json.dumps(geojson, ensure_ascii=False) + "\n```\n\n"
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        self.sessions[session_id].append({"role": "user", "content": message})

        # ── Verificar si es cruce/WFS para delegar al método full ──
        categoria, _, usar_wfs = _extraer_tema(message)
        if usar_wfs and self.get_spatial_data(session_id):
            respuesta = await self._generate_response(
                message, self.sessions[session_id], session_id=session_id, community_mode=community_mode
            )
            self.sessions[session_id].append({"role": "assistant", "content": respuesta})
            self._registrar_pregunta(session_id, message, categoria, False, False, 0)
            self._persistir()
            yield respuesta
            return

        # ── Respuesta rápida por keywords (sin LLM) ──
        from geoia.core.llm import _responder
        rapida = _responder(message)
        if rapida:
            self.sessions[session_id].append({"role": "assistant", "content": rapida})
            self._registrar_pregunta(session_id, message, categoria, False, False, 0)
            self._persistir()
            yield rapida
            return

        # ── Ruta FUNDAMENTADA (híbrido) ──────────────────────────────
        # Temas de catastro/normatividad/IGAC: buscan en fuentes oficiales + RAG
        # (acotado ~2-3s) y responden con citas. Sigue en streaming, así la voz
        # va hablando frase por frase. Preguntas simples caen a la ruta instantánea.
        es_norma = any(kw in message.lower() for kw in (
            "resolucion", "1040", "norma", "procedimiento", "conservacion catastral",
            "formacion catastral", "actualizacion catastral", "avaluo catastral",
            "reglamento", "decreto", "ley"))
        if not usar_wfs and len(message) > 12 and (categoria is not None or es_norma):
            contexto, fuentes_block, ground_meta = await self._contexto_para_stream(message, categoria, es_norma)
            system_g = _build_system_prompt(community_mode=community_mode)
            if contexto.strip():
                system_g += (
                    "\n\nUsa EXCLUSIVAMENTE estos datos de fuentes oficiales para fundamentar tu "
                    "respuesta. Si algún dato no está aquí ni lo sabes con certeza, dilo y recomienda "
                    "verificar con el IGAC. NO escribas URLs ni inventes enlaces (el sistema añade las "
                    "fuentes al final). No repitas frases.\n\n" + contexto[:2600])
            history_g = self.sessions[session_id][-4:]
            chat_g = [{"role": "system", "content": system_g}] + history_g

            modelo_calidad = await _get_quality_model()   # 3B para normatividad
            full_response = ""
            _prox = 200
            async for token in self._stream_ollama(chat_g, model=modelo_calidad):
                full_response += token
                yield token
                # El modelo no debe escribir URLs: si empieza una, cortar (las
                # fuentes reales se añaden abajo).
                if "http" in full_response[-12:].lower():
                    logger.info("stream_chat(grounded): URL del modelo detectada, cortando")
                    break
                if len(full_response) >= _prox:
                    _prox = len(full_response) + 120
                    if _hay_repeticion_degenerada(full_response):
                        logger.warning("stream_chat(grounded): repetición degenerada, cortando")
                        break

            if not full_response:
                from geoia.core.llm import LocalTransformersLLM
                local_llm = LocalTransformersLLM()
                if local_llm.is_available:
                    try:
                        local_resp = local_llm.chat(chat_g, max_tokens=512)
                        if local_resp:
                            local_resp = _colapsar_repeticiones(local_resp[:3000])
                            self.sessions[session_id].append({"role": "assistant", "content": local_resp})
                            yield local_resp
                            if fuentes_block:
                                yield f"\n\n---\n{fuentes_block}"
                            return
                    except Exception:
                        pass
                fallback = self._fallback_sin_llm(message, contexto, [], [], [])
                self.sessions[session_id].append({"role": "assistant", "content": fallback})
                yield fallback
                return
            if fuentes_block:
                yield f"\n\n---\n{fuentes_block}"
            respuesta_final = _sin_urls_inventadas(_colapsar_repeticiones(full_response))
            self.sessions[session_id].append({"role": "assistant", "content": respuesta_final})

            # ── Retroalimentación: registrar la consulta y, si se fundamentó en
            #    fuentes reales, aprender el par Q&A (control "automático con filtro").
            n_fuentes = ground_meta.get("n_fuentes", 0)
            grounded = (ground_meta.get("n_rag", 0) > 0 or ground_meta.get("n_web", 0) > 0
                        or ground_meta.get("n_col", 0) > 0)
            self._registrar_pregunta(session_id, message, categoria, es_norma, grounded, n_fuentes)
            self._persistir()
            if grounded:
                await self._aprender_qa(message, respuesta_final, ground_meta.get("titulos_fuentes", []))
            return

        # ── System prompt base — arranca streaming SIN esperar búsquedas ──
        if community_mode:
            system = _build_system_prompt(community_mode=True)
        else:
            system = (
                "Eres Nymaira, asistente de catastro colombiano. "
                "Responde en español con lenguaje claro e inclusivo, de forma concisa y directa. "
                "Ve al grano: máximo 250 palabras, sin relleno ni preámbulos. "
                "NUNCA repitas frases ni palabras; di cada idea una sola vez. "
                "NO escribas URLs ni inventes enlaces; el sistema añade las fuentes al final. "
                "No inventes leyes, siglas ni cifras: si no lo sabes, dilo. "
                "Conoces: IGAC Base Catastral, Resolución 1040/2023, WFS colombianos, normativa catastral."
            )

        # ── Búsqueda web async (fire-and-forget) para enriquecer respuesta ──
        web_results_cache = []
        if len(message) > 15:
            async def _fetch_web():
                try:
                    return await asyncio.wait_for(_buscar_en_web(message, 4), timeout=2.5)
                except Exception:
                    return []
            task_web = asyncio.create_task(_fetch_web())
        else:
            task_web = None

        history = self.sessions[session_id][-4:]
        chat_messages = [{"role": "system", "content": system}] + history

        # ── Streaming desde Ollama INMEDIATO ──
        full_response = ""
        _proximo_chequeo = 200
        async for token in self._stream_ollama(chat_messages):
            full_response += token
            yield token
            # Cortar si el modelo empieza a escribir una URL (las inventa).
            if "http" in full_response[-12:].lower():
                break
            # Cortafuegos: si el modelo entra en un bucle de repetición, detener.
            if len(full_response) >= _proximo_chequeo:
                _proximo_chequeo = len(full_response) + 120
                if _hay_repeticion_degenerada(full_response):
                    logger.warning("stream_chat: repetición degenerada detectada, cortando stream")
                    break

        # ── Si llegaron resultados web, adjuntarlos al final ──
        if task_web is not None:
            try:
                web_results_cache = await task_web
            except Exception:
                pass
        if web_results_cache and full_response:
            enlaces_lines = ["**🌐 Fuentes consultadas**"]
            for r in web_results_cache[:4]:
                title = r.get('title','')[:80]
                url = r.get('url','')
                if title and url:
                    enlaces_lines.append(f"• [{title}]({url})")
            enlaces = "\n".join(enlaces_lines)
            if len(enlaces_lines) > 1:
                yield f"\n\n---\n{enlaces}"

        if not full_response:
            from geoia.core.llm import LocalTransformersLLM
            local_llm = LocalTransformersLLM()
            if local_llm.is_available:
                try:
                    chat_msgs = [{"role": "system", "content": system}] + history[-6:]
                    local_resp = local_llm.chat(chat_msgs, max_tokens=512)
                    if local_resp:
                        local_resp = _colapsar_repeticiones(local_resp[:3000])
                        self.sessions[session_id].append({"role": "assistant", "content": local_resp})
                        yield local_resp
                        return
                except Exception:
                    pass
            fallback = self._fallback_sin_llm(message, "", [], [], [])
            self.sessions[session_id].append({"role": "assistant", "content": fallback})
            yield fallback
            return

        if "does not support image" in full_response or "Cannot read" in full_response:
            logger.warning("Ollama image error filtrado de stream_chat")
            from geoia.core.llm import LocalTransformersLLM
            local_llm = LocalTransformersLLM()
            if local_llm.is_available:
                try:
                    chat_msgs = [{"role": "system", "content": system}] + history[-6:]
                    local_resp = local_llm.chat(chat_msgs, max_tokens=512)
                    if local_resp:
                        local_resp = _colapsar_repeticiones(local_resp[:3000])
                        self.sessions[session_id].append({"role": "assistant", "content": local_resp})
                        yield local_resp
                        return
                except Exception:
                    pass
            fallback = self._fallback_sin_llm(message, "", [], [], [])
            self.sessions[session_id].append({"role": "assistant", "content": fallback})
            yield fallback
            return

        respuesta_final = _sin_urls_inventadas(_colapsar_repeticiones(full_response))
        self.sessions[session_id].append({"role": "assistant", "content": respuesta_final})
        # Retroalimentación: registrar y (si hubo fuentes web) aprender.
        grounded = bool(web_results_cache)
        self._registrar_pregunta(session_id, message, categoria, es_norma, grounded, len(web_results_cache or []))
        self._persistir()
        if grounded:
            titulos = [r.get("title", "")[:80] for r in (web_results_cache or [])[:4] if r.get("title")]
            await self._aprender_qa(message, respuesta_final, titulos)

    async def _stream_ollama(self, messages: list[dict], model: str | None = None) -> AsyncIterator[str]:
        """Stream tokens desde Ollama. Usa el modelo más rápido salvo que se
        indique uno específico (p. ej. el de calidad para temas normativos)."""
        import httpx
        model = model or await _get_fastest_model()
        # Timeout más amplio: el modelo de calidad (3B) en CPU tarda más.
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                async with client.stream(
                    "POST",
                    "http://localhost:11434/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": True,
                        "keep_alive": -1,
                        "options": {
                            "temperature": 0.2,
                            "num_predict": 640,
                            "num_ctx": 4096,
                            "num_thread": 4,   # = núcleos FÍSICOS del i7-1165G7; medido +5% vs auto, y 8 (hyperthreads) es peor
                            "num_gpu": 99,
                            "top_k": 40,
                            "top_p": 0.9,
                            "repeat_penalty": 1.2,
                            "repeat_last_n": 320,
                            "frequency_penalty": 0.6,
                            "presence_penalty": 0.3,
                            "mirostat": 0,
                        },
                    },
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        logger.warning(f"Ollama error ({response.status_code}): {error_text.decode()[:500]}")
                        return
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            if "error" in data:
                                logger.warning(f"Ollama stream error: {data['error']}")
                                yield f"\n\n⚠️ Error del modelo: {data['error']}"
                                return
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
        self._persistir()

    async def _generate_response(
        self, message: str, history: list[dict], session_id: str | None = None,
        community_mode: bool = False,
    ) -> str:
        from geoia.core.llm import _responder

        # ── Respuesta rápida por keywords SIN búsquedas previas ──
        rapida = _responder(message)
        if rapida:
            return rapida

        eval_result = _evaluar_solicitud(message)

        # ── Respuesta inmediata si hay limitaciones (no_puede) ──
        if eval_result.get("limitaciones") and not eval_result.get("capacidades"):
            partes = [f"❌ **{cap['label']}** — {cap.get('razon', 'No disponible')}" for cap in eval_result["limitaciones"]]
            return "## 🔍 Evaluación de tu solicitud\n\n" + "\n\n".join(partes)

        categoria, directo_api, usar_wfs = _extraer_tema(message)
        session_id = session_id or "default"

        # ── 1. Busqueda en vivo (paralelo) con timeouts cortos ──
        # Buscar en web siempre excepto saludos muy cortos
        necesita_buscar = len(message) > 15
        tasks = []
        if necesita_buscar:
            tasks.append(asyncio.wait_for(_buscar_en_web(message, 4), timeout=3))
        else:
            tasks.append(asyncio.sleep(0, result=[]))

        if categoria and necesita_buscar:
            from geoia.websearch.colombia import search_colombia
            tasks.append(asyncio.wait_for(search_colombia(message, categoria, num_por_fuente=1), timeout=3))
        else:
            tasks.append(asyncio.sleep(0, result=[]))

        # WFS solo si se pide explícitamente cruce espacial
        if usar_wfs:
            tasks.append(asyncio.wait_for(_buscar_en_wfs(categoria or "catastral", 1), timeout=4))
        else:
            tasks.append(asyncio.sleep(0, result=[]))

        # API Colombia solo si es consulta directa
        if directo_api:
            tasks.append(asyncio.wait_for(_buscar_en_api_colombia(message), timeout=3))
        else:
            tasks.append(asyncio.sleep(0, result=[]))

        # IGAC directo
        if categoria == "catastral" and directo_api and necesita_buscar:
            from geoia.websearch.datos_gov_co import search_igac_datasets
            tasks.append(asyncio.wait_for(search_igac_datasets(message, categoria, limit=2), timeout=3))
        else:
            tasks.append(asyncio.sleep(0, result=[]))

        # RAG solo si menciona normatividad
        es_norma = any(kw in message.lower() for kw in ("resolucion", "1040", "norma", "procedimiento",
                        "conservacion catastral", "formacion catastral", "actualizacion catastral",
                        "avaluo catastral", "reglamento", "decreto", "ley"))
        if es_norma:
            from geoia.api.routes.rag import get_engine as get_rag_engine
            rag = await get_rag_engine()
            tasks.append(asyncio.wait_for(
                asyncio.to_thread(rag.query, message, 8),
                timeout=60
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

        # ── 5. Construir contexto con fuentes para LLM ──
        contexto_piezas: list[str] = []
        fuentes_web: list[dict] = []

        if web_results:
            contexto_piezas.append("**🌐 Resultados web:**")
            for r in web_results[:4]:
                title = r.get('title','')[:120]
                url = r.get('url','')
                snippet = r.get('snippet','')[:150]
                contexto_piezas.append(f"• {title}")
                if snippet:
                    contexto_piezas.append(f"  {snippet}")
                if url:
                    fuentes_web.append({"title": title, "url": url})

        if colombia_results:
            contexto_piezas.append(f"\n**🇨🇴 Fuentes Colombia ({categoria or 'general'}):**")
            for r in colombia_results[:4]:
                title = r.get('title','')[:100]
                url = r.get('url','')
                snippet = r.get('snippet','')[:100]
                contexto_piezas.append(f"• {title} — {snippet}")
                if url and not any(f['url'] == url for f in fuentes_web):
                    fuentes_web.append({"title": title, "url": url})

        if wfs_lines:
            contexto_piezas.append("\n**📡 WFS:**")
            contexto_piezas.extend(wfs_lines[:4])

        if api_results:
            contexto_piezas.append("\n**🔌 APIs:**")
            for r in api_results[:3]:
                title = r.get('title','')[:100]
                url = r.get('url','')
                snippet = r.get('snippet','')[:100]
                contexto_piezas.append(f"• {title} — {snippet}")
                if url and not any(f['url'] == url for f in fuentes_web):
                    fuentes_web.append({"title": title, "url": url})

        if igac_results:
            contexto_piezas.append("\n**🏛️ IGAC - Catastro Nacional:**")
            for r in igac_results[:3]:
                title = r.get('title','')[:100]
                url = r.get('url','')
                contexto_piezas.append(f"• {title}")
                if url and not any(f['url'] == url for f in fuentes_web):
                    fuentes_web.append({"title": title, "url": url})

        if rag_result and rag_result.get("chunks"):
            rag_sources = rag_result.get('sources', [])
            rag_chunks = rag_result.get('chunks', [])
            contexto_piezas.append("\n**⚖️ Normatividad catastral (Resolución 1040/2023):**")
            for i, chunk in enumerate(rag_chunks[:5], 1):
                contexto_piezas.append(f"  • Fragmento {i}: {chunk[:200]}...")
            if rag_sources:
                contexto_piezas.append(f"  Fuentes: {', '.join(rag_sources)}")

        contexto = "\n".join(contexto_piezas)

        # Formatear bloque de fuentes web para citar al final
        fuentes_block = ""
        if fuentes_web:
            fuentes_lines = ["**🌐 Fuentes consultadas:**"]
            for i, f in enumerate(fuentes_web[:6], 1):
                fuentes_lines.append(f"  {i}. [{f['title'][:80]}]({f['url']})")
            fuentes_block = "\n".join(fuentes_lines)

        # ── 6. Si hay RAG con chunks, se envían al LLM junto con el contexto ──
        if rag_result and rag_result.get("chunks"):
            rag_context = rag_result.get("context", "")
            if rag_context:
                contexto_piezas.append(f"\n**📄 Texto completo extraído de documentos:**\n{rag_context[:2000]}")

        # ── 7. LLM con contexto real ──
        prompt = _build_system_prompt(community_mode=community_mode)
        prompt += "\n\nIMPORTANTE: Incluye fuentes y referencias web en tu respuesta cuando las tengas. Cita las URLs si están disponibles."
        if contexto.strip():
            prompt += "\n\nDatos en vivo de fuentes oficiales:\n" + contexto[:2500]

        chat_messages = [{"role": "system", "content": prompt}] + history[-6:]
        ollama_resp = await self._call_ollama(chat_messages)

        if ollama_resp:
            if "does not support image" in ollama_resp or "Cannot read" in ollama_resp:
                logger.warning("Ollama image error filtrado de _generate_response")
                return self._fallback_sin_llm(message, contexto, wfs_lines, colombia_results, web_results)
            resp = ollama_resp[:3000]
            if fuentes_block:
                resp += "\n\n---\n" + fuentes_block[:800]
            if contexto.strip() and not fuentes_block:
                resp += "\n\n---\n" + contexto[:800]
            return resp

        # ── 7. Fallback: LocalTransformersLLM ──
        from geoia.core.llm import LocalTransformersLLM
        local_llm = LocalTransformersLLM()
        if local_llm.is_available:
            try:
                local_resp = local_llm.chat(chat_messages, max_tokens=512)
                if local_resp:
                    resp = local_resp[:3000]
                    if fuentes_block:
                        resp += "\n\n---\n" + fuentes_block[:800]
                    if contexto.strip() and not fuentes_block:
                        resp += "\n\n---\n" + contexto[:800]
                    return resp
            except Exception:
                pass

        # ── 8. Fallback inteligente sin LLM ──
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
