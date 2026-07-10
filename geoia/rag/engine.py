from __future__ import annotations
import os
import re
import json
import pickle
import logging
import time
import hashlib
import threading
import asyncio
import numpy as np
from pathlib import Path
from typing import Any, Optional
from geoia.core.config import settings
from geoia.core.models import setup_hf_env
from geoia.core.llm import get_llm, OllamaLLM

logger = logging.getLogger(__name__)

VECTOR_DIM = 384

# Expansión de consulta data-driven: si la pregunta contiene alguno de los
# `disparadores`, se añade la `expansion` como consulta extra para mejorar la
# cobertura. Agregar una resolución nueva es una línea aquí, sin tocar lógica.
_QUERY_ALIASES: list[dict] = [
    {"disparadores": ["794"], "expansion": "Resolución 794 de 2026"},
    {"disparadores": ["746"], "expansion": "Resolución 746 de 2024"},
    {"disparadores": ["1040"], "expansion": "Resolución 1040 de 2023"},
    {"disparadores": ["glosario"], "expansion": "glosario de términos"},
    {"disparadores": ["prefijo", "código homologado"],
     "expansion": "prefijos del código homologado de identificación predial"},
    {"disparadores": ["documentación", "entrega"],
     "expansion": "documentación mínima para entrega"},
    # ── Instituciones (guía instituciones_catastro_meta.md) ──
    {"disparadores": ["art ", "la art", "renovacion del territorio", "renovacion territorio", "pdet"],
     "expansion": "ART Agencia de Renovación del Territorio PDET desarrollo rural con enfoque territorial"},
    {"disparadores": ["parque nacional", "parques nacionales", "area protegida", "sinap"],
     "expansion": "Parques Nacionales Naturales áreas protegidas SINAP restricción de uso del suelo"},
    {"disparadores": ["ant ", "agencia nacional de tierras", "baldio", "formalizacion", "adjudicacion"],
     "expansion": "ANT Agencia Nacional de Tierras formalización y adjudicación de baldíos propiedad rural"},
    {"disparadores": ["notaria", "notarial", "escritura", "certificado de tradicion", "tradicion y libertad"],
     "expansion": "notaría escritura pública certificado de tradición y libertad matrícula inmobiliaria SNR VUR ORIP"},
    {"disparadores": ["cormacarena"],
     "expansion": "Cormacarena autoridad ambiental del Meta licencias y permisos ambientales POMCA"},
    {"disparadores": ["alcaldia", "predial", "impuesto predial", "gobernacion", "municipal", " pot ", "usos del suelo"],
     "expansion": "administración municipal alcaldía impuesto predial POT ordenamiento territorial usos del suelo"},
]


class RAGEngine:
    _cache: dict[str, Any] = {}
    _cache_ttl = 300

    def __init__(self):
        setup_hf_env()
        self.embedding_model = None
        self.index = None
        self.documents: list[str] = []
        self.metadatas: list[dict] = []
        self.ids: list[str] = []
        # Lock reentrante: protege TODA mutación del índice + persistencia.
        # Evita corrupción si el sembrado en background y el aprendizaje de Q&A
        # (que corre en un hilo durante el chat) escriben a la vez. RLock porque
        # upsert_document -> delete_source anidan la toma del lock.
        self._lock = threading.RLock()
        self._init_components()

    def _faiss_paths(self):
        base = settings.data_dir / "faiss_db"
        base.mkdir(parents=True, exist_ok=True)
        return base / "index.faiss", base / "data.pkl"

    def _init_components(self):
        try:
            from sentence_transformers import SentenceTransformer

            model_path = str(settings.embedding_model_path)
            if settings.embedding_model_path.exists():
                self.embedding_model = SentenceTransformer(model_path)
            else:
                self.embedding_model = SentenceTransformer(settings.embedding_model)
                self.embedding_model.save(model_path)

            import faiss
            idx_path, data_path = self._faiss_paths()
            if idx_path.exists() and data_path.exists():
                # Leer bytes con Python (maneja rutas unicode/´) y deserializar,
                # en vez de faiss.read_index(str(path)) que falla con no-ASCII en Windows.
                with open(idx_path, "rb") as f:
                    self.index = faiss.deserialize_index(np.frombuffer(f.read(), dtype=np.uint8))
                with open(data_path, "rb") as f:
                    data = pickle.load(f)
                    self.documents = data["documents"]
                    self.metadatas = data["metadatas"]
                    self.ids = data["ids"]
                logger.info(f"FAISS cargado: {self.index.ntotal} vectores")
            else:
                self.index = faiss.IndexFlatIP(VECTOR_DIM)
                logger.info("FAISS index creado (vacio)")

            # Pre-calentar LLM local para evitar demora en primera consulta
            try:
                from geoia.core.llm import get_llm
                llm = get_llm()
                if llm is not None and hasattr(llm, 'is_loaded'):
                    logger.info(f"LLM local disponible: {llm.is_loaded}")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"RAG init error: {e}")

    def _save(self):
        # Serializa el índice a bytes y escribe con Python (soporta rutas con ´).
        # Escritura atómica (.tmp + replace) para no dejar archivos a medias si se
        # corta a mitad. Se asume el lock ya tomado por quien muta el índice.
        try:
            import faiss
            idx_path, data_path = self._faiss_paths()
            idx_bytes = faiss.serialize_index(self.index).tobytes()
            tmp_idx = idx_path.with_suffix(".faiss.tmp")
            with open(tmp_idx, "wb") as f:
                f.write(idx_bytes)
            tmp_idx.replace(idx_path)
            tmp_data = data_path.with_suffix(".pkl.tmp")
            with open(tmp_data, "wb") as f:
                pickle.dump({
                    "documents": self.documents,
                    "metadatas": self.metadatas,
                    "ids": self.ids,
                }, f)
            tmp_data.replace(data_path)
        except Exception as e:
            logger.error(f"FAISS save error: {e}")

    def _embed(self, texts: list[str]) -> np.ndarray:
        import faiss as _faiss
        if self.embedding_model:
            emb = self.embedding_model.encode(texts)
            _faiss.normalize_L2(emb)
            return emb
        return np.zeros((len(texts), VECTOR_DIM), dtype=np.float32)

    def _score_result(self, document: str, metadata: dict) -> float:
        score = 0.0

        # Preferir GUÍAS CURADAS (.md): español limpio, redactado y correcto.
        # Los volcados crudos del PDF traen tablas, anexos y fragmentos ruidosos
        # que un modelo pequeño regurgita mal.
        source = metadata.get("source", "")
        if source.endswith(".md"):
            score += 6.0

        # Guía curada de instituciones (ART, ANT, SNR/Notarías, Cormacarena, alcaldías…):
        # empujón extra para que surja en consultas sobre trámites institucionales, donde
        # compite con los 741 chunks de la Resolución 1040.
        if source == "instituciones_catastro_meta.md":
            score += 2.5

        # Q&A APRENDIDO del propio chat: útil pero NO autoritativo (es texto
        # generado por un modelo pequeño). Prioridad baja: solo aflora cuando las
        # fuentes curadas no cubren la consulta; jamás desplaza a una guía .md.
        if source == "aprendido":
            score += 0.5

        # Frescura: leve preferencia por lo ingerido/actualizado hace poco (útil
        # cuando las fuentes del catastro se mueven). Mínimo, para no desbancar a
        # las guías curadas (.md, +6).
        ts = metadata.get("ts")
        if ts:
            edad_dias = (time.time() - ts) / 86400
            if edad_dias < 90:
                score += 0.3
            elif edad_dias < 365:
                score += 0.1

        # Penalizar fragmentos tipo tabla/índice/basura de PDF.
        if document.count("|") >= 4:
            score -= 4.0
        if document:
            legibles = sum(1 for c in document if c.isalpha() or c.isspace())
            if legibles / len(document) < 0.70:   # demasiados símbolos/dígitos
                score -= 3.0

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
        
        if "resolución 794" in doc_lower or "resolución 794 de 2026" in doc_lower or "resolución 0794" in doc_lower:
            score += 4.0
        
        if "resolución 746" in doc_lower or "resolución 746 de 2024" in doc_lower:
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
        
        if source.endswith("anexo_01_glosario.pdf") or source.endswith("anexo_03_documentacion_minima.pdf") or source.endswith("anexo_09_prefijos_codigo.pdf") or source.endswith("anexo_10_consistencia_logica.pdf"):
            score += 2.0
        
        return score

    def _extract_text(self, filename: str, content: bytes) -> tuple[str, str]:
        ext = os.path.splitext(filename)[1].lower()

        if ext == ".pdf":
            try:
                import fitz
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

    @staticmethod
    def _sanitize_source(name: str) -> str:
        """Clave de fuente segura: sin rutas ni caracteres raros (evita `../` y
        colisiones). Conserva el nombre base."""
        base = os.path.basename(str(name or "documento"))
        base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
        return base or "documento"

    def ingest_document(self, filename: str, content: bytes, content_hash: str | None = None) -> int:
        filename = self._sanitize_source(filename)
        text, model_used = self._extract_text(filename, content)

        if not text or not text.strip():
            return 0
        if content_hash is None:
            content_hash = hashlib.sha256(content).hexdigest()

        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=1500,
                chunk_overlap=200,
                length_function=len,
                separators=["\n\n", "\n", ". ", "; ", "?", "!"],
            )
            chunks = splitter.split_text(text)
        except ImportError:
            try:
                from langchain.text_splitter import RecursiveCharacterTextSplitter
                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=1500, chunk_overlap=200, length_function=len,
                    separators=["\n\n", "\n", ". ", "; ", "?", "!"],
                )
                chunks = splitter.split_text(text)
            except ImportError:
                chunks = [text[i:i+1500] for i in range(0, len(text), 750)]

        if not chunks:
            return 0

        chunks = [c.strip() for c in chunks if len(c.strip()) > 50]
        if not chunks:
            return 0

        embeddings = self._embed(chunks)
        ts = time.time()
        ids = [f"{filename}_{i}" for i in range(len(chunks))]
        metas = [{"source": filename, "model": model_used, "chunk": i,
                  "hash": content_hash, "ts": ts} for i in range(len(chunks))]

        if self.index is not None:
            with self._lock:
                self.index.add(embeddings)
                self.documents.extend(chunks)
                self.metadatas.extend(metas)
                self.ids.extend(ids)
                self._save()

        return len(chunks)

    def _rebuild_from_kept(self, keep_indices: list[int]) -> None:
        """Reconstruye el índice conservando solo las filas indicadas. FAISS
        IndexFlatIP no borra por id, pero sí permite `reconstruct`; recuperamos los
        vectores guardados y armamos un índice nuevo. Asume lock tomado."""
        import faiss
        new_index = faiss.IndexFlatIP(VECTOR_DIM)
        if keep_indices:
            vecs = np.vstack([self.index.reconstruct(int(i)) for i in keep_indices]).astype("float32")
            new_index.add(vecs)
        self.index = new_index
        self.documents = [self.documents[i] for i in keep_indices]
        self.metadatas = [self.metadatas[i] for i in keep_indices]
        self.ids = [self.ids[i] for i in keep_indices]

    def delete_source(self, source: str) -> int:
        """Elimina TODOS los chunks de una fuente (p. ej. una resolución derogada).
        Devuelve cuántos se quitaron. Seguro con lock."""
        source = self._sanitize_source(source)
        if self.index is None:
            return 0
        with self._lock:
            keep = [i for i, m in enumerate(self.metadatas) if m.get("source") != source]
            removed = len(self.metadatas) - len(keep)
            if removed:
                self._rebuild_from_kept(keep)
                self._save()
                logger.info(f"RAG: eliminados {removed} chunks de '{source}'")
            return removed

    def upsert_document(self, filename: str, content: bytes) -> dict:
        """Inserta o ACTUALIZA una fuente por hash de contenido — el corazón del
        soporte a "fuentes que se mueven":
          - Si la fuente ya está con el MISMO contenido -> no hace nada (no re-embebe).
          - Si cambió -> borra los chunks viejos y re-ingesta (sin duplicar).
          - Si es nueva -> la ingesta.
        Devuelve {status: unchanged|updated|added, chunks: N}."""
        filename = self._sanitize_source(filename)
        content_hash = hashlib.sha256(content).hexdigest()
        with self._lock:
            hashes = {m.get("hash") for m in self.metadatas if m.get("source") == filename}
            if content_hash in hashes:
                return {"status": "unchanged", "chunks": 0}
            existia = any(m.get("source") == filename for m in self.metadatas)
            if existia:
                self.delete_source(filename)
            n = self.ingest_document(filename, content, content_hash=content_hash)
            return {"status": "updated" if existia else "added", "chunks": n}

    def _norm_pregunta(self, q: str) -> str:
        """Normaliza una pregunta para deduplicar lo aprendido."""
        return re.sub(r"\s+", " ", (q or "").lower().strip())[:200]

    def add_learned_qa(self, question: str, answer: str, sources: list[str] | None = None) -> bool:
        """Guarda un par pregunta+respuesta FUNDAMENTADA en la base vectorial
        para reutilizarlo después. Devuelve True si se agregó algo nuevo.

        Seguro con FAISS: se ejecuta en el mismo proceso del servidor. Se
        deduplica por pregunta normalizada para no inflar el índice."""
        if self.index is None or not question or not answer:
            return False
        question = question.strip()
        answer = answer.strip()
        if len(answer) < 40:   # respuestas triviales/errores no aportan
            return False

        norm = self._norm_pregunta(question)
        doc = f"Pregunta: {question}\nRespuesta: {answer}"
        try:
            with self._lock:
                for meta in self.metadatas:
                    if meta.get("source") == "aprendido" and meta.get("norm") == norm:
                        return False  # ya aprendida (dedup dentro del lock)
                embeddings = self._embed([doc])
                self.index.add(embeddings)
                self.documents.append(doc)
                self.metadatas.append({
                    "source": "aprendido",
                    "model": "qa_feedback",
                    "chunk": 0,
                    "norm": norm,
                    "fuentes": ", ".join(sources or [])[:300],
                    "ts": time.time(),
                })
                self.ids.append(f"aprendido_{int(time.time()*1000)}")
                self._save()
            logger.info(f"RAG aprendió Q&A: {question[:60]}...")
            return True
        except Exception as e:
            logger.warning(f"No se pudo aprender Q&A: {e}")
            return False

    def listar_aprendido(self) -> list[dict]:
        """Devuelve los pares Q&A aprendidos (para inspección/depuración)."""
        out = []
        for doc, meta in zip(self.documents, self.metadatas):
            if meta.get("source") == "aprendido":
                out.append({"texto": doc[:400], "fuentes": meta.get("fuentes", ""),
                            "ts": meta.get("ts")})
        return out

    def _generate_answer(self, query_text: str, context: str, sources: list[str]) -> str:
        try:
            from geoia.core.llm import get_llm
            llm = get_llm()
            if llm is None:
                return ""
            system = (
                "Eres un asistente experto en normatividad catastral colombiana. "
                "Responde en español de forma clara, concisa y precisa (máximo 3 párrafos). "
                "Usa EXCLUSIVAMENTE la información del contexto proporcionado. "
                "No uses tu conocimiento previo. Si el contexto no contiene la respuesta, "
                "di que no dispones de esa información. No inventes datos."
            )
            context_clean = context[:2800].replace("|", " ").replace("\n\n\n", "\n\n")
            prompt = (
                f"Contexto:\n{context_clean}\n\n"
                f"Pregunta: {query_text}\n\n"
                f"Responde solo con la información del contexto:"
            )
            answer = llm.generate(prompt, system=system, max_tokens=400)
            return answer.strip()
        except Exception as e:
            logger.error(f"RAG answer generation error: {e}")
            return ""

    def query(self, query_text: str, top_k: int = 8, generar: bool = True) -> dict:
        """Recupera fragmentos relevantes. Si `generar=True` además redacta una
        respuesta con el LLM (endpoint /rag/query). El chatbot usa `generar=False`
        porque solo necesita los fragmentos como contexto — así evita una llamada
        LLM extra que competiría con el streaming y dispararía el tiempo de espera."""
        if self.index is None or self.index.ntotal == 0:
            return {"answer": "", "sources": [], "chunks": []}

        def _search(q: str, n: int) -> list[dict]:
            emb = self._embed([q])
            n_res = min(n, self.index.ntotal)
            dists, idxs = self.index.search(emb, n_res)
            results = []
            for idx, dist in zip(idxs[0], dists[0]):
                if idx < 0 or idx >= len(self.documents):
                    continue
                results.append({
                    "doc": self.documents[idx],
                    "meta": self.metadatas[idx],
                    "dist": float(dist),
                })
            return results

        # Multi-consulta para mejor cobertura (alias data-driven, ver _QUERY_ALIASES)
        queries = [query_text]
        lower = query_text.lower()
        for alias in _QUERY_ALIASES:
            if any(d in lower for d in alias["disparadores"]):
                queries.append(alias["expansion"])

        seen_ids = set()
        all_results = []
        for q in queries:
            results = _search(q, top_k * 2)
            for r in results:
                rid = f"{r['meta'].get('source','')}_{r['meta'].get('chunk', 0)}"
                if rid not in seen_ids:
                    seen_ids.add(rid)
                    all_results.append(r)

        for r in all_results:
            r["score"] = self._score_result(r["doc"], r["meta"])

        all_results.sort(key=lambda x: x["score"], reverse=True)
        top_results = all_results[:top_k]

        context = "\n\n---\n\n".join([
            f"[Fragmento {i+1} - {r['meta'].get('source','desconocido')}]\n{r['doc']}"
            for i, r in enumerate(top_results)
        ])
        sources = list(set([r["meta"].get("source", "desconocido") for r in top_results]))
        chunks = [r["doc"] for r in top_results]
        answer = self._generate_answer(query_text, context, sources) if generar else ""

        return {"answer": answer, "sources": sources, "chunks": chunks, "context": context}

    def clear_cache(self) -> None:
        """Limpiar cache local para forzar re-inicialización."""
        self._cache.clear()
        logger.info("Cache RAG limpiado")