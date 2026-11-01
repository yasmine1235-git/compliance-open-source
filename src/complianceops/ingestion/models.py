"""Data models shared by the ingestion pipeline and the vector store."""

from dataclasses import dataclass
from enum import StrEnum


class BlockKind(StrEnum):
    """How the text of a block was extracted."""

    TEXT = "text"
    TABLE = "table"
    OCR = "ocr"


class Category(StrEnum):
    """Index a document belongs to. Each category has its own collection."""

    MIFID_II = "mifid_ii"
    SFDR = "sfdr"
    PRIIPS = "priips"
    AMF = "amf"
    PROSPECTUS = "prospectus"


@dataclass(frozen=True)
class Block:
    """A piece of text extracted from one page or slide (numbered from 1)."""

    page: int
    text: str
    kind: BlockKind


@dataclass(frozen=True)
class Chunk:
    """A block ready for indexing, with the metadata needed to cite it."""

    chunk_id: str
    doc_id: str
    doc_version: str
    source_doc: str
    page: int
    kind: BlockKind
    text: str
