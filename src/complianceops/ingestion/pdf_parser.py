"""Block extraction from PDF files."""

from pathlib import Path
from typing import Any

import pymupdf

from complianceops.ingestion.models import Block, BlockKind
from complianceops.ingestion.ocr import ocr_image

# A page with less text than this is treated as a scan and read with OCR.
_MIN_PAGE_TEXT_CHARS = 20
# Smaller images are assumed to be logos or icons.
_MIN_IMAGE_SIZE_PX = 100
_SCAN_DPI = 300
_IMAGE_BLOCK_TYPE = 1


def _table_blocks(page: Any, page_number: int) -> tuple[list[Block], list[Any]]:
    blocks = []
    areas = []
    for table in page.find_tables().tables:
        rows = [" | ".join(cell or "" for cell in row) for row in table.extract()]
        blocks.append(Block(page_number, "\n".join(rows).strip(), BlockKind.TABLE))
        areas.append(pymupdf.Rect(table.bbox))
    return blocks, areas


def _text_blocks(page: Any, page_number: int, table_areas: list[Any]) -> list[Block]:
    blocks = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] == _IMAGE_BLOCK_TYPE:
            continue
        # Text inside a table was already extracted with the table.
        center = (pymupdf.Rect(block["bbox"]).tl + pymupdf.Rect(block["bbox"]).br) / 2
        if any(center in area for area in table_areas):
            continue
        lines = ["".join(span["text"] for span in line["spans"]) for line in block["lines"]]
        blocks.append(Block(page_number, "\n".join(lines).strip(), BlockKind.TEXT))
    return blocks


def _image_blocks(page: Any, page_number: int) -> list[Block]:
    blocks = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != _IMAGE_BLOCK_TYPE:
            continue
        if min(block["width"], block["height"]) < _MIN_IMAGE_SIZE_PX:
            continue
        blocks.append(Block(page_number, ocr_image(block["image"]), BlockKind.OCR))
    return blocks


def parse_pdf(path: Path) -> list[Block]:
    """Return the text, table and OCR blocks of a PDF, in page order."""
    blocks: list[Block] = []
    with pymupdf.open(path) as document:
        for page_number, page in enumerate(document, start=1):
            if len(page.get_text().strip()) < _MIN_PAGE_TEXT_CHARS:
                scan = page.get_pixmap(dpi=_SCAN_DPI).tobytes("png")
                blocks.append(Block(page_number, ocr_image(scan), BlockKind.OCR))
                continue
            table_blocks, table_areas = _table_blocks(page, page_number)
            blocks += _text_blocks(page, page_number, table_areas)
            blocks += table_blocks
            blocks += _image_blocks(page, page_number)
    return blocks
