"""Services used by the API, created on first use because they are slow to load."""

from functools import lru_cache

from qdrant_client import QdrantClient

from complianceops.agents.llm import LlmClient
from complianceops.agents.models import Retriever
from complianceops.config import get_settings
from complianceops.ingestion.models import Category, Chunk
from complianceops.rag.embeddings import Embedder, SentenceTransformerEmbedder
from complianceops.rag.store import VectorStore

_PASSAGES_PER_CLAIM = 3


def get_llm() -> LlmClient | None:
    """Return the LLM client. None is configured yet, so LLM rules stay ``not_evaluated``."""
    return None


@lru_cache
def _search_services() -> tuple[VectorStore, Embedder]:
    settings = get_settings()
    store = VectorStore(QdrantClient(url=settings.qdrant_url))
    return store, SentenceTransformerEmbedder(settings.embedding_model)


def _retrieve_from_prospectus(query: str, doc_id: str, doc_version: str) -> list[Chunk]:
    store, embedder = _search_services()
    results = store.search(
        Category.PROSPECTUS,
        embedder.embed([query])[0],
        limit=_PASSAGES_PER_CLAIM,
        doc_id=doc_id,
        doc_version=doc_version,
    )
    return [result.chunk for result in results]


def get_retriever() -> Retriever:
    """Return the function agents use to search a prospectus."""
    return _retrieve_from_prospectus
