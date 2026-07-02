from geoia.core.ai_models import procesar_documento, resumen_documento, extraer_entidades, ocr_texto

extract_text = lambda filename, content: resumen_documento(procesar_documento(filename, content))
summarize_text = lambda text, max_chars=2000: text[:max_chars] + ("\n\n[...truncado]" if len(text) > max_chars else "")
