from __future__ import annotations
import re
import logging
import time
import asyncio
from typing import Any, Optional
from geoia.core.config import settings
from geoia.core.models import setup_hf_env
from geoia.core.llm import get_llm

logger = logging.getLogger(__name__)


class RAGEngine:
    _cache: dict[str, Any] = {}
    _cache_ttl = 300

    def __init__(self):
        setup_hf_env()
        self.vector_store = None
        self.embedding_model = None
        self._init_components()

    def _init_components(self):
        try:
            from sentence_transformers import SentenceTransformer
            import chromadb

            model_path = str(settings.embedding_model_path)
            if settings.embedding_model_path.exists():
                self.embedding_model = SentenceTransformer(model_path)
            else:
                self.embedding_model = SentenceTransformer(settings.embedding_model)
                self.embedding_model.save(model_path)

            chroma_client = chromadb.PersistentClient(
                path=str(settings.vector_db_path)
            )
            self.vector_store = chroma_client.get_or_create_collection(
                name="documentos_catastrales",
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            logger.error(f"RAG init error: {e}")

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self.embedding_model:
            return self.embedding_model.encode(texts).tolist()
        return [[0.0] * 384 for _ in texts]

    def _score_result(self, document: str, metadata: dict) -> float:
        score = 0.0
        model = metadata.get("model", "")
        if "PyMuPDF" in model:
            score += 2.0
        elif "PaddleOCR" in model:
            score += 1.5
        elif "procesar_documento" in model:
            score += 1.5
        
        doc_lower = document.lower()
        if "resolución 1040" in doc_lower or "resolución 1040 de 2023" in doc_lower:
            score += 4.0
        
        if "resolución única" in doc_lower or "gestoría catastral multipropósito" in doc_lower:
            score += 2.5
        
        if re.search(r'art[ií]culo\s+\d+', doc_lower):
            score += 1.5
        
        if re.search(r'art[ií]culo\s+\d+°', doc_lower):
            score += 1.0
        
        if re.search(r'\\n\\n[a-záéíóú\\s]+:', doc_lower):
            score += 1.0
        
        words = doc_lower.split()
        if len(words) > 150:
            score += 0.5
        
        if "coeficiente" in doc_lower or "declaratorio" in doc_lower:
            score += 0.8
        
        if any(term in doc_lower for term in ["director", "gerencia", "comité", "intendente", "drd"]):
            score += 1.2
        
        return score

    def _extract_text(self, filename: str, content: bytes) -> tuple[str, str]:
        ext = os.path.splitext(filename)[1].lower()

        if ext == ".pdf":
            try:
                doc = fitz.open(stream=content, filetype="pdf")
                pages = []
                for page in doc:
                    t = page.get_text()
                    if t.strip():
                        pages.append(t)
                text = "\n\n".join(pages)
                if text.strip():
                    return text, "PyMuPDF"
            except Exception:
                pass
            try:
                from geoia.core.ai_models import procesar_documento
                result = procesar_documento(filename, content)
                t = result.get("texto_extraido", "")
                if t.strip() and "[" not in t[:5]:
                    return t, "+".join(result.get("modelos_usados", ["procesar_documento"]))
            except Exception:
                pass
            return content.decode("utf-8", errors="ignore"), "fallback_utf8"

        if ext in (".txt", ".csv", ".json", ".md"):
            return content.decode("utf-8", errors="replace"), "utf-8"

        try:
            from geoia.core.ai_models import procesar_documento
            result = procesar_documento(filename, content)
            t = result.get("texto_extraido", "")
            if t.strip() and "[" not in t[:5]:
                return t, "+".join(result.get("modelos_usados", ["procesar_documento"]))
        except Exception:
            pass
        return content.decode("utf-8", errors="ignore"), "fallback_utf8"

    def ingest_document(self, filename: str, content: bytes) -> int:
        text, model_used = self._extract_text(filename, content)

        if not text or not text.strip():
            return 0

        try:
            from langchain.text_splitter import RecursiveCharacterTextSplitter
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=500,
                chunk_overlap=50,
                length_function=len,
                separators=["\n\n", "\n", ". ", "; ", "\?", "!"],
            )
            chunks = splitter.split_text(text)
        except ImportError:
            chunks = [text[i:i+500] for i in range(0, len(text), 250)]

        if not chunks:
            return 0

        chunks = [c.strip() for c in chunks if len(c.strip()) > 50]
        if not chunks:
            return 0

        embeddings = self._embed(chunks)
        ids = [f"{filename}_{i}" for i in range(len(chunks))]

        if self.vector_store:
            self.vector_store.add(
                documents=chunks,
                embeddings=embeddings,
                ids=ids,
                metadatas=[{"source": filename, "model": model_used, "chunk": i} for i in range(len(chunks))],
            )

        return len(chunks)

    def query(self, query_text: str, top_k: int = 5) -> dict:
        if not self.vector_store:
            return {"answer": "No hay documentos indexados. Ingrese documentos primero.", "sources": []}

        query_embedding = self._embed([query_text])[0]

        try:
            results = self.vector_store.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, 100),
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            logger.error(f"ChromaDB query error: {e}")
            return {"answer": "Error al buscar en los documentos indexados.", "sources": []}

        if not results["documents"] or not results["documents"][0]:
            return {"answer": "No se encontraron documentos relevantes.", "sources": []}

        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results.get("distances", [[0]])[0]

        scored_results = []
        for doc, meta, dist in zip(documents, metadatas, distances):
            score = self._score_result(doc, meta)
            scored_results.append({"doc": doc, "meta": meta, "dist": dist, "score": score})

        scored_results.sort(key=lambda x: x["score"], reverse=True)

        top_results = scored_results[:top_k]
        context = "\n\n".join([r["doc"] for r in top_results])
        sources = list(set([m.get("source", "desconocido") for m in [r["meta"] for r in top_results]]))

        prompt = (
            "Eres un asistente experto en normatividad catastral colombiana. Tenemos acceso a documentos oficiales de normatividad catastral, específicamente a la Resolución 1040 de 2023 del IGAC. "
            "Responde usando SOLO la información de los documentos proporcionados, siguiendo estas reglas exactas:\n\n"
            "1. Cita artículos específicos si los documentos los mencionan (ej: 'Art. 1°, Res. 1040/2023')\n"
            "2. Si el documento menciona procedimientos, describe el PASO A PASO\n"
            "3. Si el documento proporciona plazos, fechas o requisitos: enumera todos NOMBRES los elementos\n"
            "4. Si el documento tiene TITULARES, incluye el título como subtítulo\n"
            "5. Si encuentras 'Comité', 'GERENCIA', 'DRD' (Director Regional) en el texto: preserva el contenido exacto, no lo reformules\n"
            "6. No agregues información que no esté explicitamente en los documentos aportados\n"
            "7. Si la pregunta es sobre X Y el documento dice Z: responde con Z, no con X\n"
            "8. Si la respuesta es SATISFACTORIA: indica 'SATISFACTORIO' explícitamente\n"
            "9. Si el texto del documento incluye LISTAS o ENUMERACIONES: manténlas exactamente como aparecen\n"
            "10. NO respondas con frases genéricas como 'consultar el documento completo' a menos que NO haya términos específicos\n\n"
            "DISEMINACIÓN CATÁSTRAL: El documento contiene numerosos verbos descendentes, territoriales, administrativos y de control [[kata]] que deben ser conservados.\n\n"
            "NORMAS DE ÉPOCA: Preserva la terminología exacta del período (2023), incluyendo asignaciones territoriales, horarios y designaciones institucionales.\n\n"
            f"Documentos (ordenados por relevancia):\n---\n{context}\n---\n\n"
            f"Pregunta: {query_text}\n\n"
            "Respuesta (citando artículos, preserving terminología exacta, orden según relevancia):"
        )

        llm = get_llm()
        if not llm or not hasattr(llm, "generate"):
            return {"answer": "LLM no disponible para generar respuesta.", "sources": sources}

        answer = llm.generate(prompt, system="Eres un asistente experto en normatividad catastral colombiana. Responde solo con la información de los documentos proporcionados. Preserva la terminología, títulos, artículos y enumeraciones exactas. Cita fuentes correctamente. Ordena según relevancia. Responde paso a paso para procedimientos y preserva la terminología exacta del período 2023.")

        if not answer:
            answer = (
                "Basado en los documentos consultados (Resolución 1040 de 2023): No se encontró respuesta específica en los textos aportados."
            )

        return {"answer": answer, "sources": sources}

    def clear_cache(self) -> None:
        """Limpiar cache local para forzar re-inicialización."""
        self._cache.clear()
        logger.info("Cache RAG limpiado")