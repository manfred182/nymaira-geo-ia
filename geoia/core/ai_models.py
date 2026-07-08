# gestión central de modelos AI: OCR, STT, NER, LLM.

# Integra modelos open-source para procesar información:
#   - PaddleOCR: extraer texto de PDFs/imágenes/documentos
#   - Whisper: voz a texto
#   - GLiNER: extraer entidades (predios, nombres, fechas, direcciones)
 #   - Ollama LLM: respuestas inteligentes

# módulo de modelos AI

from __future__ import annotations
import io, json, logging, os, re, tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# OCR (PaddleOCR)
# ─────────────────────────────────────────────────────────────────────────────

_ocr = None

def get_ocr():
    global _ocr
    if _ocr is None:
        try:
            from paddleocr import PaddleOCR
            _ocr = PaddleOCR(use_angle_cls=True, lang="es", show_log=False, use_gpu=False)
            logger.info("PaddleOCR cargado exitosamente")
        except ImportError:
            logger.warning("PaddleOCR no instalado. Usar: pip install paddleocr")
        except Exception as e:
            logger.warning(f"PaddleOCR no disponible: {e}")
    return _ocr

def ocr_texto(imagen_bytes: bytes) -> str:
    """Extrae texto de una imagen/PDF usando PaddleOCR."""
    ocr = get_ocr()
    if ocr is None:
        return ""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(imagen_bytes)).convert("RGB")
        img_path = tempfile.mktemp(suffix=".png")
        img.save(img_path)
        result = ocr.ocr(img_path, cls=True)
        os.remove(img_path)
        lines = []
        for page in result if isinstance(result, list) else [result]:
            if isinstance(page, list):
                for line in page:
                    if isinstance(line, (list, tuple)) and len(line) > 1:
                        text = line[1][0] if isinstance(line[1], (list, tuple)) else str(line[1])
                        if text.strip():
                            lines.append(text.strip())
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Error en OCR: {e}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# STT - Whisper
# ─────────────────────────────────────────────────────────────────────────────

_stt = None

def get_stt():
    global _stt
    if _stt is None:
        try:
            import whisper
            _stt = whisper.load_model("tiny", device="cpu")
            logger.info("Whisper tiny cargado")
        except ImportError:
            logger.warning("Whisper no instalado. Usar: pip install openai-whisper")
        except Exception as e:
            logger.warning(f"Whisper no disponible: {e}")
    return _stt

def transcribir(audio_bytes: bytes) -> str:
    """Transcribe audio a texto usando Whisper."""
    stt = get_stt()
    if stt is None:
        return ""
    try:
        ext = ".wav"
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            f.write(audio_bytes)
            tmp = f.name
        result = stt.transcribe(tmp, language="es", fp16=False)
        os.remove(tmp)
        return result.get("text", "").strip()
    except Exception as e:
        logger.warning(f"Error en transcripcion: {e}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# NER - GLiNER
# ─────────────────────────────────────────────────────────────────────────────

_ner = None

def get_ner():
    global _ner
    if _ner is None:
        try:
            from gliner import GLiNER
            _ner = GLiNER.from_pretrained("urchade/gliner_multi-v2.1")
            logger.info("GLiNER cargado exitosamente")
        except ImportError:
            logger.warning("GLiNER no instalado. Usar: pip install gliner")
        except Exception as e:
            logger.warning(f"GLiNER no disponible: {e}")
    return _ner

def extraer_entidades(texto: str) -> list[dict]:
    """Extrae entidades de un texto usando GLiNER."""
    ner = get_ner()
    if ner is None:
        return []
    try:
        labels = ["nombre", "persona", "lugar", "direccion", "fecha",
                  "numero", "identificacion", "matricula", "predio",
                  "municipio", "departamento", "documento", "telefono",
                  "correo", "entidad", "valor", "area", "norma", "articulo", "resolucion",
                  "procedimiento", "formacion", "actualizacion", "conservacion",
                  "avaluo", "gestor", "entidad_gubernamental", "tipo_tramite"]
        entities = ner.predict_entities(texto[:3000], labels, threshold=0.3)
        return [{"texto": e["text"], "label": e["label"], "score": round(e["score"], 3)}
                for e in entities]
    except Exception as e:
        logger.warning(f"Error en NER: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Procesamiento inteligente de documentos
# ─────────────────────────────────────────────────────────────────────────────

def procesar_documento(nombre: str, contenido: bytes) -> dict[str, Any]:
    """Procesa un documento subido por el usuario usando todos los modelos disponibles."""
    ext = os.path.splitext(nombre)[1].lower()
    resultado: dict[str, Any] = {
        "nombre": nombre,
        "tamano_kb": len(contenido) // 1024,
        "texto_extraido": "",
        "entidades": [],
        "modelos_usados": [],
    }

    # 1. Extraer texto segun tipo de archivo
    if ext in (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"):
        # Imagen → OCR
        texto = ocr_texto(contenido)
        if texto:
            resultado["texto_extraido"] = texto
            resultado["modelos_usados"].append("PaddleOCR")
        else:
            resultado["texto_extraido"] = f"[Imagen: {nombre} — OCR no disponible para extraer texto]"
    elif ext == ".pdf":
        # PDF → intentar extraer texto directo, fallback OCR
        try:
            import fitz
            doc = fitz.open(stream=contenido, filetype="pdf")
            texto = "\n".join(page.get_text() for page in doc)
            if not texto.strip():
                raise ValueError("Sin texto extraible")
            resultado["texto_extraido"] = texto
            resultado["modelos_usados"].append("PyMuPDF")
        except Exception:
            texto = ocr_texto(contenido)
            if texto:
                resultado["texto_extraido"] = texto
                resultado["modelos_usados"].append("PaddleOCR")
    elif ext in (".txt", ".csv", ".json", ".geojson"):
        try:
            resultado["texto_extraido"] = contenido.decode("utf-8", errors="replace")
        except Exception:
            resultado["texto_extraido"] = contenido.decode("latin-1", errors="replace")
    elif ext in (".docx", ".doc"):
        try:
            import docx
            doc = docx.Document(io.BytesIO(contenido))
            resultado["texto_extraido"] = "\n".join(p.text for p in doc.paragraphs)
            resultado["modelos_usados"].append("python-docx")
        except ImportError:
            resultado["texto_extraido"] = f"[Documento Word: {nombre}]"
    elif ext in (".xlsx", ".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True)
            lines = []
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                for row in ws.iter_rows(values_only=True):
                    lines.append(", ".join(str(c) if c is not None else "" for c in row))
            resultado["texto_extraido"] = "\n".join(lines)
            resultado["modelos_usados"].append("openpyxl")
        except ImportError:
            resultado["texto_extraido"] = f"[Excel: {nombre}]"
    else:
        resultado["texto_extraido"] = f"[Archivo: {nombre} - {len(contenido)} bytes]"

    # 2. Extraer entidades con GLiNER si hay texto suficiente
    texto = resultado.get("texto_extraido", "")
    if len(texto) > 20 and "[" not in texto[:5]:
        try:
            entidades = extraer_entidades(texto[:3000])
            if entidades:
                resultado["entidades"] = entidades
                resultado["modelos_usados"].append("GLiNER")
        except Exception:
            pass

    # 3. Truncar texto si es muy largo
    if len(resultado["texto_extraido"]) > 5000:
        resultado["texto_extraido"] = resultado["texto_extraido"][:5000] + "\n\n[...truncado]"

    return resultado


def resumen_documento(resultado: dict) -> str:
    """Genera un resumen legible del resultado del procesamiento."""
    lines = [f"📄 **{resultado['nombre']}** ({resultado['tamano_kb']}KB)"]

    if resultado["modelos_usados"]:
        lines.append(f"🔧 Modelos: {' + '.join(resultado['modelos_usados'])}")

    texto = resultado.get("texto_extraido", "")
    if texto:
        lines.append(f"\n📝 **Contenido:**\n{texto[:2000]}")

    if resultado["entidades"]:
        lines.append(f"\n🏷️ **Entidades encontradas:**")
        for e in resultado["entidades"][:15]:
            lines.append(f"  • {e['texto']} — _{e['label']}_ ({e['score']})")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Estado de modelos disponibles
# ─────────────────────────────────────────────────────────────────────────────

def estado_modelos() -> dict:
    """Retorna que modelos estan disponibles."""
    modelos = {
        "ocr": {"nombre": "PaddleOCR", "disponible": False, "tipo": "OCR"},
        "stt": {"nombre": "Whisper", "disponible": False, "tipo": "Voz"},
        "ner": {"nombre": "GLiNER", "disponible": False, "tipo": "NER"},
    }
    try:
        import paddleocr
        modelos["ocr"]["disponible"] = True
    except ImportError:
        pass
    try:
        import whisper
        modelos["stt"]["disponible"] = True
    except ImportError:
        pass
    try:
        import gliner
        modelos["ner"]["disponible"] = True
    except ImportError:
        pass
    return modelos