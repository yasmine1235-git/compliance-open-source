"""Tests for chunking, versioned indexing and folder watching."""

from collections.abc import Callable
from pathlib import Path

import pymupdf
import pytest

from complianceops.ingestion.chunking import chunk_blocks
from complianceops.ingestion.models import Block, BlockKind, Category
from complianceops.ingestion.pipeline import ingest_file
from complianceops.ingestion.watcher import FolderWatcher
from complianceops.rag.store import EmbeddingMismatchError, VectorStore
from conftest import FakeEmbedder


def _pdf(path: Path, *pages: str) -> Path:
    document = pymupdf.open()
    for text in pages:
        document.new_page().insert_text((72, 72), text)
    document.save(path)
    return path


def _recorder(ingested: list[Path]) -> Callable[[Path], int]:
    def ingest(path: Path) -> int:
        ingested.append(path)
        return 1

    return ingest


def _text_query(embedder: FakeEmbedder, text: str) -> list[float]:
    return embedder.embed([text])[0]


def test_chunking_keeps_only_blocks_over_20_characters() -> None:
    blocks = [
        Block(1, "x" * 20, BlockKind.TEXT),
        Block(1, "y" * 21, BlockKind.TEXT),
        Block(2, f"  {'z' * 20}  ", BlockKind.TEXT),
    ]

    chunks = chunk_blocks(blocks, "doc", "1", "doc.pdf")

    assert [chunk.text for chunk in chunks] == ["y" * 21]
    assert chunks[0].page == 1
    assert (chunks[0].doc_id, chunks[0].doc_version, chunks[0].source_doc) == (
        "doc",
        "1",
        "doc.pdf",
    )


def test_chunk_ids_are_stable_and_differ_by_version() -> None:
    blocks = [Block(1, "a sufficiently long block of text", BlockKind.TEXT)]

    first = chunk_blocks(blocks, "doc", "1", "doc.pdf")[0].chunk_id
    again = chunk_blocks(blocks, "doc", "1", "doc.pdf")[0].chunk_id
    other_version = chunk_blocks(blocks, "doc", "2", "doc.pdf")[0].chunk_id

    assert first == again
    assert first != other_version


def test_search_finds_ingested_chunk_with_citation(
    tmp_path: Path, store: VectorStore, embedder: FakeEmbedder
) -> None:
    text = "Past performance is not a reliable indicator."
    path = _pdf(tmp_path / "doc.pdf", "Some other content on the first page.", text)

    count = ingest_file(path, "1", Category.SFDR, store, embedder)
    results = store.search(Category.SFDR, _text_query(embedder, text), limit=1)

    assert count == 2
    chunk = results[0].chunk
    assert (chunk.text, chunk.page, chunk.source_doc, chunk.doc_id, chunk.doc_version) == (
        text,
        2,
        "doc.pdf",
        "doc",
        "1",
    )


def test_search_can_target_a_version(
    tmp_path: Path, store: VectorStore, embedder: FakeEmbedder
) -> None:
    old = "The management fee of this fund is 1.50 percent."
    new = "The management fee of this fund is 2.00 percent."
    ingest_file(_pdf(tmp_path / "doc.pdf", old), "1", Category.PROSPECTUS, store, embedder)
    ingest_file(_pdf(tmp_path / "doc.pdf", new), "2", Category.PROSPECTUS, store, embedder)
    query = _text_query(embedder, old)

    only_v1 = store.search(Category.PROSPECTUS, query, doc_version="1")
    only_v2 = store.search(Category.PROSPECTUS, query, doc_version="2")
    both = store.search(Category.PROSPECTUS, query)

    assert [result.chunk.text for result in only_v1] == [old]
    assert [result.chunk.text for result in only_v2] == [new]
    assert len(both) == 2


def test_search_can_target_a_document(
    tmp_path: Path, store: VectorStore, embedder: FakeEmbedder
) -> None:
    ingest_file(
        _pdf(tmp_path / "a.pdf", "Content of the first document."),
        "1",
        Category.PROSPECTUS,
        store,
        embedder,
    )
    ingest_file(
        _pdf(tmp_path / "b.pdf", "Content of the second document."),
        "1",
        Category.PROSPECTUS,
        store,
        embedder,
    )

    results = store.search(Category.PROSPECTUS, _text_query(embedder, "anything"), doc_id="b")

    assert [result.chunk.doc_id for result in results] == ["b"]


def test_reingesting_replaces_chunks_including_removed_ones(
    tmp_path: Path, store: VectorStore, embedder: FakeEmbedder
) -> None:
    first = _pdf(
        tmp_path / "doc.pdf", "First page of the document.", "Second page of the document."
    )
    ingest_file(first, "1", Category.AMF, store, embedder)
    shorter = _pdf(tmp_path / "doc.pdf", "Only one page remains now.")
    ingest_file(shorter, "1", Category.AMF, store, embedder)

    results = store.search(Category.AMF, _text_query(embedder, "anything"), limit=10)

    assert [result.chunk.text for result in results] == ["Only one page remains now."]


def test_categories_are_separate_indexes(
    tmp_path: Path, store: VectorStore, embedder: FakeEmbedder
) -> None:
    ingest_file(
        _pdf(tmp_path / "doc.pdf", "A rule about sustainability."),
        "1",
        Category.SFDR,
        store,
        embedder,
    )

    assert store.search(Category.PRIIPS, _text_query(embedder, "rule")) == []


def test_embedding_size_change_is_rejected(
    tmp_path: Path, store: VectorStore, embedder: FakeEmbedder
) -> None:
    path = _pdf(tmp_path / "doc.pdf", "Content long enough to be a chunk.")
    ingest_file(path, "1", Category.SFDR, store, embedder)

    class LargerEmbedder(FakeEmbedder):
        dimension = 16

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.5] * 16 for _ in texts]

    with pytest.raises(EmbeddingMismatchError):
        ingest_file(path, "2", Category.SFDR, store, LargerEmbedder())


class TestFolderWatcher:
    def test_waits_for_file_to_stop_changing(self, tmp_path: Path) -> None:
        ingested: list[Path] = []
        watcher = FolderWatcher(tmp_path, _recorder(ingested))
        path = tmp_path / "doc.pdf"
        path.write_bytes(b"partial")

        assert watcher.poll_once() == []
        path.write_bytes(b"partial and more content")
        assert watcher.poll_once() == []
        assert watcher.poll_once() == [path]
        assert ingested == [path]

    def test_ingests_each_version_of_a_file_once(self, tmp_path: Path) -> None:
        ingested: list[Path] = []
        watcher = FolderWatcher(tmp_path, _recorder(ingested))
        path = tmp_path / "doc.pdf"
        path.write_bytes(b"one")
        watcher.poll_once()
        watcher.poll_once()
        watcher.poll_once()
        assert len(ingested) == 1

        path.write_bytes(b"two, a changed file")
        watcher.poll_once()
        watcher.poll_once()
        assert len(ingested) == 2

    def test_ignores_unsupported_files(self, tmp_path: Path) -> None:
        ingested: list[Path] = []
        watcher = FolderWatcher(tmp_path, _recorder(ingested))
        (tmp_path / "notes.txt").write_text("text")

        watcher.poll_once()
        watcher.poll_once()

        assert ingested == []

    def test_failed_file_does_not_stop_others_and_is_not_retried_until_changed(
        self, tmp_path: Path
    ) -> None:
        attempts: list[str] = []

        def ingest(path: Path) -> int:
            attempts.append(path.name)
            if path.name == "bad.pdf":
                raise ValueError("corrupt")
            return 1

        watcher = FolderWatcher(tmp_path, ingest)
        (tmp_path / "bad.pdf").write_bytes(b"bad")
        (tmp_path / "good.pdf").write_bytes(b"good")
        watcher.poll_once()

        assert watcher.poll_once() == [tmp_path / "good.pdf"]
        watcher.poll_once()
        assert sorted(attempts) == ["bad.pdf", "good.pdf"]
