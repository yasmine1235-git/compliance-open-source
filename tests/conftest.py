"""Shared test helpers."""

import hashlib

import pytest
from qdrant_client import QdrantClient

from complianceops.rag.store import VectorStore


class FakeEmbedder:
    """Deterministic embedder: identical texts get identical vectors."""

    dimension = 8

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [
            [byte / 255 + 0.01 for byte in hashlib.sha256(t.encode()).digest()[:8]] for t in texts
        ]


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def store() -> VectorStore:
    return VectorStore(QdrantClient(":memory:"))
