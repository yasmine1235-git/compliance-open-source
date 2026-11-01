"""Block extraction from PPTX files."""

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from complianceops.ingestion.models import Block, BlockKind
from complianceops.ingestion.ocr import ocr_image


def _flatten(shapes: Iterable[Any]) -> Iterator[Any]:
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _flatten(shape.shapes)
        else:
            yield shape


def _shape_block(shape: Any, slide_number: int) -> Block | None:
    if getattr(shape, "has_table", False):
        rows = [" | ".join(cell.text for cell in row.cells) for row in shape.table.rows]
        return Block(slide_number, "\n".join(rows).strip(), BlockKind.TABLE)
    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
        return Block(slide_number, ocr_image(shape.image.blob), BlockKind.OCR)
    if shape.has_text_frame:
        return Block(slide_number, shape.text_frame.text.strip(), BlockKind.TEXT)
    return None


def parse_pptx(path: Path) -> list[Block]:
    """Return the text, table and OCR blocks of a deck, in slide order."""
    blocks = []
    for slide_number, slide in enumerate(Presentation(str(path)).slides, start=1):
        for shape in _flatten(slide.shapes):
            block = _shape_block(shape, slide_number)
            if block is not None:
                blocks.append(block)
    return blocks
