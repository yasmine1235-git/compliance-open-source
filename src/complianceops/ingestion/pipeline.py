"""Parsing, chunking, embedding and indexing of one document."""

from pathlib import Path

from complianceops.ingestion.chunking import chunk_blocks
from complianceops.ingestion.models import Block, Category
from complianceops.ingestion.pdf_parser import parse_pdf
from complianceops.ingestion.pptx_parser import parse_pptx
from complianceops.rag.embeddings import Embedder
from complianceops.rag.store import VectorStore

SUPPORTED_SUFFIXES = frozenset({".pdf", ".pptx"})


def parse_document(path: Path) -> list[Block]:
    """Return the blocks of a PDF or PPTX file."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path)
    if suffix == ".pptx":
        return parse_pptx(path)
    raise ValueError(f"Unsupported file type: {path.name}")


def ingest_file(
    path: Path,
    doc_version: str,
    category: Category,
    store: VectorStore,
    embedder: Embedder,
    doc_id: str | None = None,
) -> int:
    """Index a document, replacing any earlier copy of the same version.

    Returns the number of chunks indexed. The document ID defaults to the file name without its
    extension, so new versions of a file stay linked to each other.
    """
    resolved_id = doc_id or path.stem
    chunks = chunk_blocks(parse_document(path), resolved_id, doc_version, path.name)
    vectors = embedder.embed([chunk.text for chunk in chunks]) if chunks else []
    store.replace_document(category, resolved_id, doc_version, chunks, vectors, embedder.dimension)
    return len(chunks)
