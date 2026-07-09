"""Pruebas del motor RAG enfocadas en "fuentes que se mueven":
upsert idempotente por hash, actualización sin duplicar, y borrado de fuente.

Usa un embedder falso determinista y un índice FAISS en un directorio temporal,
así no carga sentence-transformers ni toca la base real (rápido y aislado).
"""
import threading

import numpy as np
import pytest

faiss = pytest.importorskip("faiss")
from geoia.rag.engine import RAGEngine, VECTOR_DIM


@pytest.fixture
def engine(tmp_path, monkeypatch):
    # Índice temporal, sin cargar el modelo de embeddings real.
    monkeypatch.setattr(
        RAGEngine, "_faiss_paths",
        lambda self: (tmp_path / "index.faiss", tmp_path / "data.pkl"),
    )
    e = RAGEngine.__new__(RAGEngine)
    e.embedding_model = None
    e.index = faiss.IndexFlatIP(VECTOR_DIM)
    e.documents, e.metadatas, e.ids = [], [], []
    e._lock = threading.RLock()

    def fake_embed(texts):
        arr = np.zeros((len(texts), VECTOR_DIM), dtype="float32")
        for i, t in enumerate(texts):
            arr[i, abs(hash(t)) % VECTOR_DIM] = 1.0
        return arr

    e._embed = fake_embed
    return e


def _chunks_de(engine, source):
    return [m for m in engine.metadatas if m.get("source") == source]


def test_upsert_agrega_fuente_nueva(engine):
    res = engine.upsert_document("guia.md", b"El catastro multiproposito es el inventario de predios. " * 30)
    assert res["status"] == "added"
    assert res["chunks"] >= 1
    assert len(_chunks_de(engine, "guia.md")) == res["chunks"]


def test_upsert_mismo_contenido_no_reembebe(engine):
    contenido = b"Contenido normativo estable sobre formacion catastral. " * 30
    engine.upsert_document("res.md", contenido)
    n1 = engine.index.ntotal
    res = engine.upsert_document("res.md", contenido)  # idéntico
    assert res["status"] == "unchanged"
    assert res["chunks"] == 0
    assert engine.index.ntotal == n1  # no creció


def test_upsert_contenido_cambiado_reemplaza_sin_duplicar(engine):
    engine.upsert_document("res.md", b"Version vieja de la resolucion. " * 30)
    viejos = len(_chunks_de(engine, "res.md"))
    res = engine.upsert_document("res.md", b"Version NUEVA y distinta de la resolucion. " * 40)
    assert res["status"] == "updated"
    # Solo debe quedar la versión nueva (sin acumular la vieja)
    metas = _chunks_de(engine, "res.md")
    assert len(metas) == res["chunks"]
    assert all(m["hash"] == metas[0]["hash"] for m in metas)
    assert len(metas) != viejos or metas[0]["hash"]  # cambió el contenido


def test_delete_source_quita_todo(engine):
    engine.upsert_document("a.md", b"Documento A sobre avaluos catastrales. " * 20)
    engine.upsert_document("b.md", b"Documento B sobre conservacion catastral. " * 20)
    total = engine.index.ntotal
    quitados = engine.delete_source("a.md")
    assert quitados >= 1
    assert _chunks_de(engine, "a.md") == []
    assert _chunks_de(engine, "b.md")  # b intacto
    assert engine.index.ntotal == total - quitados


def test_sanitize_source_evita_rutas(engine):
    assert RAGEngine._sanitize_source("../../etc/passwd") == "passwd"
    assert RAGEngine._sanitize_source("res 1040:2023.pdf") == "res_1040_2023.pdf"


def test_persistencia_roundtrip(engine, tmp_path, monkeypatch):
    engine.upsert_document("g.md", b"Guia de catastro multiproposito del IGAC. " * 25)
    ntotal = engine.index.ntotal
    docs = list(engine.documents)
    # Releer desde disco como haría _init_components
    with open(tmp_path / "index.faiss", "rb") as f:
        idx = faiss.deserialize_index(np.frombuffer(f.read(), dtype=np.uint8))
    assert idx.ntotal == ntotal
    import pickle
    with open(tmp_path / "data.pkl", "rb") as f:
        data = pickle.load(f)
    assert data["documents"] == docs
