"""Conversion of extracted blocks into indexable chunks."""

import uuid
from collections.abc import Iterable

from complianceops.ingestion.models import Block, Chunk

_MIN_CHUNK_CHARS = 20
_CHUNK_ID_NAMESPACE = uuid.UUID("6f1d2c1e-7a55-4b0a-9a53-3f2c8e1d4b77")


def chunk_blocks(
    blocks: Iterable[Block], doc_id: str, doc_version: str, source_doc: str
) -> list[Chunk]:
    """Keep each block over 20 characters as one chunk.

    Chunk IDs depend only on the document, version and position, so they are stable across runs.
    """
    chunks = []
    for position, block in enumerate(blocks):
        text = block.text.strip()
        if len(text) <= _MIN_CHUNK_CHARS:
            continue
        chunk_id = uuid.uuid5(_CHUNK_ID_NAMESPACE, f"{doc_id}|{doc_version}|{position}")
        chunks.append(
            Chunk(
                chunk_id=str(chunk_id),
                doc_id=doc_id,
                doc_version=doc_version,
                source_doc=source_doc,
                page=block.page,
                kind=block.kind,
                text=text,
            )
        )
    return chunks
