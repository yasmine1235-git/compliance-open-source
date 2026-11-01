"""Versioned chunk storage and search in Qdrant."""

from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from complianceops.ingestion.models import BlockKind, Category, Chunk


class EmbeddingMismatchError(RuntimeError):
    """A collection was built with a different embedding size than the current model."""


@dataclass(frozen=True)
class SearchResult:
    """A chunk returned by a search, with its similarity score."""

    chunk: Chunk
    score: float


def _collection_name(category: Category) -> str:
    return f"complianceops_{category.value}"


def _match_all(**fields: str | None) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(key=key, match=models.MatchValue(value=value))
            for key, value in fields.items()
            if value is not None
        ]
    )


class VectorStore:
    """One Qdrant collection per category. Every chunk stores its ``doc_version``."""

    def __init__(self, client: QdrantClient) -> None:
        self._client = client

    def _ensure_collection(self, category: Category, dimension: int) -> None:
        name = _collection_name(category)
        if not self._client.collection_exists(name):
            self._client.create_collection(
                name,
                vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
            )
            return
        vectors = self._client.get_collection(name).config.params.vectors
        existing = vectors.size if isinstance(vectors, models.VectorParams) else None
        if existing != dimension:
            raise EmbeddingMismatchError(
                f"Collection {name} holds vectors of size {existing}, but the current embedding "
                f"model produces size {dimension}. Delete the collection and ingest again."
            )

    def replace_document(
        self,
        category: Category,
        doc_id: str,
        doc_version: str,
        chunks: list[Chunk],
        vectors: list[list[float]],
        dimension: int,
    ) -> None:
        """Store a document version, removing any chunks left from an earlier ingestion."""
        self._ensure_collection(category, dimension)
        name = _collection_name(category)
        self._client.delete(
            name,
            points_selector=models.FilterSelector(
                filter=_match_all(doc_id=doc_id, doc_version=doc_version)
            ),
            wait=True,
        )
        if not chunks:
            return
        points = [
            models.PointStruct(
                id=chunk.chunk_id,
                vector=vector,
                payload={
                    "doc_id": chunk.doc_id,
                    "doc_version": chunk.doc_version,
                    "source_doc": chunk.source_doc,
                    "page": chunk.page,
                    "kind": chunk.kind.value,
                    "text": chunk.text,
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        self._client.upsert(name, points=points, wait=True)

    def search(
        self,
        category: Category,
        query_vector: list[float],
        limit: int = 5,
        doc_id: str | None = None,
        doc_version: str | None = None,
    ) -> list[SearchResult]:
        """Return the closest chunks, optionally limited to one document or version."""
        name = _collection_name(category)
        if not self._client.collection_exists(name):
            return []
        response = self._client.query_points(
            name,
            query=query_vector,
            query_filter=_match_all(doc_id=doc_id, doc_version=doc_version),
            limit=limit,
            with_payload=True,
        )
        results = []
        for point in response.points:
            payload = point.payload or {}
            chunk = Chunk(
                chunk_id=str(point.id),
                doc_id=payload["doc_id"],
                doc_version=payload["doc_version"],
                source_doc=payload["source_doc"],
                page=payload["page"],
                kind=BlockKind(payload["kind"]),
                text=payload["text"],
            )
            results.append(SearchResult(chunk=chunk, score=point.score))
        return results
