"""Tests del motor RAG con ChromaDB aislado."""
import os, sys, tempfile, pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from geoia.core.config import settings
from geoia.core.models import setup_hf_env
setup_hf_env()

from geoia.rag.engine import RAGEngine


@pytest.fixture
def temp_db():
    orig = settings.vector_db_path
    tmp = tempfile.mkdtemp()
    settings.vector_db_path = tmp
    engine = RAGEngine()
    yield engine
    settings.vector_db_path = orig


def test_extract_text_pdf():
    pdf_path = os.path.join(os.path.dirname(__file__), "..", "resolucion_1040_de_2023.pdf")
    if not os.path.exists(pdf_path):
        pytest.skip("PDF de prueba no encontrado")

    with open(pdf_path, "rb") as f:
        content = f.read()

    engine = RAGEngine()
    text, model = engine._extract_text("test.pdf", content)

    assert len(text) > 1000
    assert model == "PyMuPDF"
    assert "RESOLUCIÓN" in text or "1040" in text


def test_chunking(temp_db):
    engine = temp_db
    text = "Palabra. " * 5000
    chunks = engine.ingest_document("test_chunks.txt", text.encode("utf-8"))
    assert chunks > 1


def test_retrieval(temp_db):
    """Verifica que ChromaDB recupera documentos relevantes (sin dependencia del LLM)."""
    engine = temp_db

    engine.ingest_document("formacion.txt", b"FORMACION CATASTRAL: conjunto de operaciones catastrales para levantar informacion predial.")

    # Acceder directo al vector store para verificar recuperacion
    result = engine.vector_store.query(
        query_embeddings=[engine._embed(["formacion catastral"])[0]],
        n_results=1,
    )
    assert result["documents"] and result["documents"][0]
    assert "formacion" in result["documents"][0][0].lower() or "FORMACION" in result["documents"][0][0]


def test_query_returns_structure(temp_db):
    """Verifica que query() retorna answer + sources sin importar el LLM."""
    engine = temp_db
    engine.ingest_document("dummy.txt", b"contenido de prueba para testing del motor RAG")
    result = engine.query("prueba", top_k=1)
    assert "answer" in result
    assert "sources" in result
    # Debe tener al menos la dummy.txt como source
    assert any("dummy.txt" in s for s in result["sources"])


def test_ingest_url_no_network():
    from geoia.api.routes.rag import RAGIngestURLRequest
    req = RAGIngestURLRequest(url="https://ejemplo.com/doc.pdf")
    assert req.url == "https://ejemplo.com/doc.pdf"
