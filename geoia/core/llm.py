from __future__ import annotations
import logging
import re
from geoia.core.config import settings

logger = logging.getLogger(__name__)


def _responder(message):
    msg = message.lower().strip()
    # Revisar saludos primero (siempre responder rápido, aunque tenga palabras consulta)
    SALUDOS_RE = r"\bhola\b|\bbuenos d[ií]as\b|\bbuenas tardes\b|\bbuenas noches\b|\bbuenas\b|\bsaludos\b|\bque tal\b|\bcomo estas\b"
    if re.search(SALUDOS_RE, msg) and len(msg) < 80:
        return "¡Hola! ¿En qué te puedo ayudar hoy? Puedo resolver dudas sobre catastro, predios, linderos, trámites o análisis espacial. 😊"

    # Mensajes largos o con consulta real → delegar al LLM
    palabras_consulta = ("puede", "puedes", "cómo", "como", "qué", "que", "cuál", "cual",
                         "dónde", "donde", "cuándo", "cuando", "por favor", "necesito",
                         "busca", "muestra", "analiza", "cruza", "calcul", "verifica",
                         "predio", "catastro", "archivo", "polígono", "capa", "mapa",
                         "igac", "snrp", "upra", "ideam", "norma", "ley", "decreto")
    if len(msg) > 60 or any(p in msg for p in palabras_consulta):
        return None
    pares = [
        (r"\bmatr[ií]cula\b", (
            "¡Claro! Para consultar una matrículla inmobiliaria (que es como la "
            "cédula de tu predio o terreno) necesitas tener a mano:\n\n"
            "• El número de matrícula (aparece en escrituras o recibos)\n"
            "• El departamento y municipio donde está el terreno\n\n"
            "Puedes hacerlo de dos formas:\n"
            "1️⃣ Presencial: ve a la oficina de registro de tu municipio\n"
            "2️⃣ Virtual: entra al portal de la Supernotariado (SNRP) desde el computador\n\n"
            "Si quieres, en la pestaña de 'Colombia' 🇨🇴 busco información oficial para ti."
        )),
        (r"\baval[uú]o\b", (
            "El avalúo catastral es básicamente **¿cuánto vale tu terreno según el gobierno?** "
            "Se calcula teniendo en cuenta varias cosas:\n\n"
            "📏 El tamaño del terreno y lo que está construido\n"
            "📍 Dónde queda (barrio, municipio)\n"
            "🏠 La estratificación\n"
            "🌱 Para qué se usa el suelo\n"
            "🔧 Las características físicas del predio\n\n"
            "No es lo mismo un terreno en el centro de la ciudad que uno en la vereda. "
            "Si quieres saber el avalúo exacto de un predio, puedes consultarlo en la "
            "oficina de catastro de tu municipio."
        )),
        (r"\blindero\b", (
            "Un lindero es **la línea que separa tu terreno del vecino**. "
            "Es como la 'raya' que divide dos propiedades.\n\n"
            "Para validar linderos debes:\n"
            "1️⃣ Revisar la escritura pública (dice cómo se describen los límites)\n"
            "2️⃣ Hacer un levantamiento topográfico (medición del terreno)\n"
            "3️⃣ Verificar las coordenadas con herramientas de mapas\n\n"
            "En la pestaña 'Validación' puedes probar coordenadas para ver si un "
            "polígono está bien formado. ¡Es gratis y fácil!"
        )),
        (r"\btr[aá]mite\b", (
            "Estos son los trámites catastrales más comunes que la gente necesita:\n\n"
            "📋 **Actualización catastral** - Cuando tu predio cambia (ej: construiste una pieza nueva)\n"
            "📋 **Corrección de área** - Si el área registrada no coincide con la real\n"
            "📋 **Cambio de uso de suelo** - Si antes era rural y ahora es urbano\n"
            "📋 **Registro de mejoras** - Cuando haces arreglos o construcciones\n"
            "📋 **Rectificación de linderos** - Si los límites del terreno están mal\n\n"
            "Para cualquier trámite, lo mejor es ir a la oficina de catastro "
            "de tu municipio con la documentación del predio. Ellos te guían paso a paso."
        )),
        (r"\bgracias\b", "¡Con gusto! Cuando tengas más dudas, aquí estoy. 😊"),
        (r"\bqu[eé] puedes hacer\b|\bqu[eé] sabes hacer\b|\bfunciones\b|\bcapacidades\b",
         "Puedo ayudarte con:\n\n"
         "🏠 **Catastro** — matrícula, avalúos, linderos, trámites\n"
         "📄 **Documentos** — sube un PDF y hazle preguntas\n"
         "🗺️ **Geo IA** — análisis espacial, cruces de capas, WFS/WMS\n"
         "📐 **Validación** — coordenadas y polígonos\n"
         "🇨🇴 **Colombia** — busco en fuentes oficiales del gobierno\n"
         "⚖️ **Normatividad** — Resolución IGAC 1040 de 2023 y más\n\n"
         "¿Por dónde empezamos?"),
        (r"\bgeo\b|\bsatelital\b|\bimagen\b|\bclasificar\b", (
            "¿Tienes una imagen satelital o aérea de un terreno? "
            "En la pestaña 'Geo IA' puedes subirla y con inteligencia artificial "
            "la clasificamos para saber si es zona urbana, rural, bosque, agua, etc.\n\n"
            "Así puedes identificar cambios en el terreno sin necesidad de ir al lugar."
        )),
        (r"\bdocumento\b|\bpdf\b|\brag\b", (
            "Puedes subir documentos (como escrituras, manuales, normas) "
            "en la pestaña 'Documentos' y después hacerle preguntas sobre "
            "su contenido. Es como tener un asistente que lee los papeles por ti."
        )),
        (r"\bvalidar\b|\bcoordenadas?\b|\bpol[ií]gono\b", (
            "Si tienes coordenadas de un terreno, en la pestaña 'Validación' "
            "puedes ingresarlas y verificamos que el polígono (la forma del terreno) "
            "esté bien formado. Te decimos el área, perímetro y si hay errores."
        )),
    ]
    for patron, respuesta in pares:
        if re.search(patron, msg):
            return respuesta
    return None


class LocalTransformersLLM:
    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._pipe = None
        self._loaded = False
        self._load_error = None

    @property
    def is_available(self) -> bool:
        path = settings.local_llm_model_path
        if not path.exists():
            return False
        safetensors = list(path.rglob("model.safetensors")) + list(path.rglob("*.safetensors"))
        return len(safetensors) > 0

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def _load(self):
        if self._loaded:
            return True
        if self._load_error:
            return False
        if not self.is_available:
            self._load_error = "Modelo no descargado"
            logger.warning(f"Modelo local no encontrado en {settings.local_llm_model_path}")
            return False
        try:
            from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline as hf_pipeline
            import torch
            logger.info(f"Cargando modelo local {settings.local_llm_model_name}...")
            model_path = str(settings.local_llm_model_path)
            self._tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
            self._model = AutoModelForCausalLM.from_pretrained(
                model_path,
                dtype="auto",
                device_map="auto",
                local_files_only=True,
            )
            if self._model.generation_config.max_length is not None and self._model.generation_config.max_length < 256:
                self._model.generation_config.max_length = 2048
            self._pipe = hf_pipeline(
                "text-generation",
                model=self._model,
                tokenizer=self._tokenizer,
            )
            self._loaded = True
            logger.info("Modelo local cargado exitosamente")
            return True
        except Exception as e:
            self._load_error = str(e)
            logger.error(f"Error cargando modelo local: {e}")
            return False

    def _build_prompt(self, message: str, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": message})
        return self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

    def generate(self, prompt: str, system: str | None = None, max_tokens: int = 256) -> str:
        if not self._load():
            return ""

        try:
            full_prompt = self._build_prompt(prompt, system)
            self._model.generation_config.max_length = 2048
            result = self._pipe(
                full_prompt,
                max_new_tokens=max_tokens,
                max_length=2048,
                do_sample=False,
                pad_token_id=self._tokenizer.eos_token_id,
            )
            texto = result[0]["generated_text"]
            if texto.startswith(full_prompt):
                texto = texto[len(full_prompt):]
            return texto.strip()
        except Exception as e:
            logger.error(f"Error en generacion local: {e}")
            return ""

    def chat(self, messages: list[dict], max_tokens: int = 512) -> str:
        if not messages:
            return ""

        if not self._load():
            return ""

        try:
            prompt = self._tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            result = self._pipe(
                prompt,
                max_new_tokens=max_tokens,
                temperature=0.3,
                top_p=0.9,
                do_sample=True,
                pad_token_id=self._tokenizer.eos_token_id,
            )
            texto = result[0]["generated_text"]
            if texto.startswith(prompt):
                texto = texto[len(prompt):]
            return texto.strip()
        except Exception as e:
            logger.error(f"Error en generacion local: {e}")
            return ""


_instancia = None


def get_llm():
    global _instancia
    if _instancia is None:
        _instancia = LocalTransformersLLM()
    return _instancia


def _scan_local_models() -> list[dict]:
    result = []
    if settings.local_llm_model_path.exists():
        n_files = len(list(settings.local_llm_model_path.rglob("*")))
        result.append({
            "name": settings.local_llm_model_name,
            "path": str(settings.local_llm_model_path),
            "size_mb": 0,
            "format": "transformers",
            "files": n_files,
        })
    return result


def _check_ollama() -> str | bool:
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=3)
        if r.status_code == 200:
            return "http://localhost:11434"
    except Exception:
        pass
    return False


class OllamaLLM:
    """LLM via Ollama - ultra rápido, sin carga de modelo."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen2.5:1.5b"):
        self._base_url = base_url
        self._model = model
        self._available = None

    @property
    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import httpx
            r = httpx.get(f"{self._base_url}/api/tags", timeout=3)
            if r.status_code == 200:
                models = r.json().get("models", [])
                names = [m.get("name", "") for m in models]
                self._available = self._model in names or any(self._model in n for n in names)
                return self._available
        except Exception:
            pass
        self._available = False
        return False

    def generate(self, prompt: str, system: str | None = None, max_tokens: int = 512) -> str:
        if not self.is_available:
            return ""
        try:
            import httpx
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            r = httpx.post(
                f"{self._base_url}/api/chat",
                json={"model": self._model, "messages": messages, "stream": False,
                      "options": {"temperature": 0.3, "num_predict": max_tokens}},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json().get("message", {}).get("content", "").strip()
        except Exception as e:
            logger.error(f"Error Ollama generate: {e}")
        return ""

    def chat(self, messages: list[dict], max_tokens: int = 512) -> str:
        if not self.is_available or not messages:
            return ""
        try:
            import httpx
            r = httpx.post(
                f"{self._base_url}/api/chat",
                json={"model": self._model, "messages": messages, "stream": False,
                      "options": {"temperature": 0.3, "num_predict": max_tokens}},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json().get("message", {}).get("content", "").strip()
        except Exception as e:
            logger.error(f"Error Ollama chat: {e}")
        return ""


_llm_instance: OllamaLLM | LocalTransformersLLM | None = None


def get_llm():
    """Retorna el mejor LLM disponible (singleton): Ollama > LocalTransformers > None."""
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance
    ollama_url = _check_ollama()
    if ollama_url:
        try:
            import httpx
            r = httpx.get(f"{ollama_url}/api/tags", timeout=3)
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                for candidate in ("qwen2.5:0.5b", "qwen2.5:1.5b", "llama3.2:1b", "qwen2.5:3b", "qwen2.5:7b"):
                    if candidate in models or any(candidate in n for n in models):
                        _llm_instance = OllamaLLM(base_url=ollama_url, model=candidate)
                        logger.info(f"Usando Ollama {candidate}")
                        return _llm_instance
        except Exception:
            pass
    _llm_instance = LocalTransformersLLM()
    if _llm_instance.is_available:
        logger.info("Usando LocalTransformers (Qwen2.5-0.5B-Instruct)")
        return _llm_instance
    _llm_instance = None
    return None
