from __future__ import annotations

import asyncio
import logging

from geoia.core.config import settings

logger = logging.getLogger(__name__)


async def seed_default_documents() -> None:
    """Precarga documentos RAG al arrancar. Solo .md para no bloquear startup.
    Los PDFs grandes se procesan con seed_pdfs_background después del arranque.
    """
    try:
        from geoia.api.routes.rag import get_engine as get_rag_engine
        engine = await get_rag_engine()
        if engine.index is None:
            return

        existing_count = engine.index.ntotal if engine.index else 0
        if existing_count > 0:
            logger.debug(f"RAG ya tiene {existing_count} docs; se omite auto-seed.")
            return

        total_files = 0
        total_chunks = 0

        # Solo .md (rápido)
        seed_dir = settings.data_dir / "rag_seed"
        if seed_dir.exists():
            for md_path in sorted(seed_dir.glob("*.md")):
                try:
                    content = md_path.read_bytes()
                    chunks = await asyncio.to_thread(engine.ingest_document, md_path.name, content)
                    total_files += 1
                    total_chunks += chunks
                except Exception as e:
                    logger.error(f"Error al sembrar '{md_path.name}': {e}")

        logger.info(
            f"Auto-seed RAG: {total_files} archivo(s), {total_chunks} chunk(s). "
            f"PDFs se procesarán en background."
        )
    except Exception as e:
        logger.error(f"Error en auto-seed RAG: {e}")


async def seed_pdfs_background() -> None:
    """Procesa PDFs de data/documents/ en background (no bloquea startup)."""
    import gc
    try:
        from geoia.api.routes.rag import get_engine as get_rag_engine
        engine = await get_rag_engine()
        if engine.index is None:
            logger.warning("RAG no disponible, se omite seed de PDFs.")
            return

        docs_dir = settings.data_dir / "documents"
        if not docs_dir.exists():
            logger.debug("data/documents/ no existe, sin PDFs que procesar.")
            return

        pdfs = sorted(docs_dir.glob("*.pdf"))
        if not pdfs:
            logger.debug("Sin PDFs en data/documents/.")
            return

        logger.info(f"Iniciando seed de {len(pdfs)} PDF(s) en background (puede tomar varios minutos)...")

        for pdf_path in pdfs:
            size_mb = pdf_path.stat().st_size / (1024 * 1024)
            if size_mb > 100:
                logger.warning(f"PDF muy grande ({size_mb:.0f} MB), se omite: {pdf_path.name}")
                continue
            # Idempotente: si el PDF ya está ingestado, no lo vuelvas a cargar
            ya = any(pdf_path.name == m.get("source") for m in engine.metadatas)
            if ya:
                logger.info(f"PDF ya ingestado, se omite: {pdf_path.name}")
                continue
            try:
                content = pdf_path.read_bytes()
                chunks = await asyncio.to_thread(engine.ingest_document, pdf_path.name, content)
                logger.info(f"PDF ingestado: {pdf_path.name} ({size_mb:.1f} MB) -> {chunks} chunks")
                gc.collect()
            except Exception as e:
                logger.error(f"Error al ingestar PDF '{pdf_path.name}': {e}")

        logger.info("Seed de PDFs en background completado.")
    except Exception as e:
        logger.error(f"Error en seed_pdfs_background: {e}")
