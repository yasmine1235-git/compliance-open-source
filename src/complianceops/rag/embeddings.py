"""Text embedding models."""

from typing import Any, Protocol

MINILM = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
BGE_M3 = "BAAI/bge-m3"


class Embedder(Protocol):
    """Anything that can turn texts into vectors of a fixed size."""

    @property
    def dimension(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformerEmbedder:
    """Embedder backed by a sentence-transformers model, downloaded on first use."""

    def __init__(self, model_name: str = MINILM) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                'Embedding needs the optional dependencies: pip install ".[embeddings]"'
            ) from error
        self._model: Any = SentenceTransformer(model_name)

    @property
    def dimension(self) -> int:
        return int(self._model.get_embedding_dimension())

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [[float(value) for value in vector] for vector in vectors]
