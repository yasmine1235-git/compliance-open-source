"""Tests for the PDF and PPTX parsers, using small generated documents."""

import io
import shutil
from pathlib import Path

import pymupdf
import pytesseract
import pytest
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.util import Inches

from complianceops.ingestion import ocr
from complianceops.ingestion.models import Block, BlockKind
from complianceops.ingestion.ocr import OcrUnavailableError
from complianceops.ingestion.pdf_parser import parse_pdf
from complianceops.ingestion.pipeline import parse_document
from complianceops.ingestion.pptx_parser import parse_pptx

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="needs Tesseract")


def _image_png(text: str) -> bytes:
    image = Image.new("RGB", (1400, 300), "white")
    ImageDraw.Draw(image).text((40, 90), text, fill="black", font=ImageFont.load_default(64))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _kinds(blocks: list[Block], kind: BlockKind) -> list[Block]:
    return [block for block in blocks if block.kind is kind]


def test_pdf_extracts_text_per_page(tmp_path: Path) -> None:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Past performance is not a reliable indicator.")
    document.new_page().insert_text((72, 72), "Capital is at risk for all investors.")
    path = tmp_path / "doc.pdf"
    document.save(path)

    blocks = parse_pdf(path)

    assert [(block.page, block.kind) for block in blocks] == [
        (1, BlockKind.TEXT),
        (2, BlockKind.TEXT),
    ]
    assert "Past performance" in blocks[0].text
    assert "Capital is at risk" in blocks[1].text


@pytest.mark.parametrize(
    ("header", "row", "expected_row"),
    [
        (("Fee", "Rate"), ("Management", "1.50%"), "Management | 1.50%"),
        (("Amount", "Currency"), ("1,234.56", "EUR"), "1,234.56 | EUR"),
        (("Ongoing charges", "Rate"), ("Performance fee", "20.00%"), "Performance fee | 20.00%"),
    ],
)
def test_pdf_extracts_table_values_exactly_without_duplicating_them(
    tmp_path: Path, header: tuple[str, str], row: tuple[str, str], expected_row: str
) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 60), "The fund charges are listed in the table below.")
    for y, values in ((100, header), (130, row)):
        for x, value in zip((72, 222), values, strict=True):
            page.draw_rect(pymupdf.Rect(x, y, x + 150, y + 30))
            page.insert_text((x + 8, y + 20), value)
    path = tmp_path / "table.pdf"
    document.save(path)

    blocks = parse_pdf(path)

    tables = _kinds(blocks, BlockKind.TABLE)
    assert [table.text for table in tables] == [f"{header[0]} | {header[1]}\n{expected_row}"]
    assert [block.text for block in _kinds(blocks, BlockKind.TEXT)] == [
        "The fund charges are listed in the table below."
    ]


def test_pdf_scanned_page_uses_ocr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("complianceops.ingestion.pdf_parser.ocr_image", lambda _: "scanned text")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_image(page.rect, stream=_image_png("Capital at risk"))
    path = tmp_path / "scan.pdf"
    document.save(path)

    assert parse_pdf(path) == [Block(1, "scanned text", BlockKind.OCR)]


def test_pdf_page_with_text_also_reads_large_images_but_not_small_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("complianceops.ingestion.pdf_parser.ocr_image", lambda _: "image text")
    icon = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(icon, format="PNG")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "This page has enough regular text to skip full page OCR.")
    page.insert_image(pymupdf.Rect(72, 100, 472, 200), stream=_image_png("Capital at risk"))
    page.insert_image(pymupdf.Rect(72, 300, 104, 332), stream=icon.getvalue())
    path = tmp_path / "mixed.pdf"
    document.save(path)

    blocks = parse_pdf(path)

    assert len(_kinds(blocks, BlockKind.TEXT)) == 1
    assert _kinds(blocks, BlockKind.OCR) == [Block(1, "image text", BlockKind.OCR)]


def test_pptx_extracts_text_tables_groups_and_pictures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("complianceops.ingestion.pptx_parser.ocr_image", lambda _: "picture text")
    deck = Presentation()
    blank = deck.slide_layouts[6]
    first = deck.slides.add_slide(blank)
    box = first.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    box.text_frame.text = "Guaranteed returns for every investor"
    group = first.shapes.add_group_shape()
    grouped = group.shapes.add_textbox(Inches(1), Inches(3), Inches(4), Inches(1))
    grouped.text_frame.text = "Text inside a grouped shape"
    second = deck.slides.add_slide(blank)
    table = second.shapes.add_table(1, 2, Inches(1), Inches(1), Inches(4), Inches(1)).table
    table.cell(0, 0).text = "ISIN"
    table.cell(0, 1).text = "FR0000000000"
    second.shapes.add_picture(io.BytesIO(_image_png("x")), Inches(1), Inches(3))
    path = tmp_path / "deck.pptx"
    deck.save(str(path))

    blocks = parse_pptx(path)

    assert blocks == [
        Block(1, "Guaranteed returns for every investor", BlockKind.TEXT),
        Block(1, "Text inside a grouped shape", BlockKind.TEXT),
        Block(2, "ISIN | FR0000000000", BlockKind.TABLE),
        Block(2, "picture text", BlockKind.OCR),
    ]


def test_parse_document_rejects_other_file_types(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        parse_document(tmp_path / "notes.txt")


def test_ocr_ignores_undecodable_images() -> None:
    assert ocr.ocr_image(b"not an image") == ""


def test_ocr_reports_missing_tesseract(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_: object, **__: object) -> str:
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "image_to_string", missing)

    with pytest.raises(OcrUnavailableError):
        ocr.ocr_image(_image_png("text"))


@needs_tesseract
def test_ocr_reads_a_scanned_pdf_page(tmp_path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_image(page.rect, stream=_image_png("Capital at risk"))
    path = tmp_path / "scan.pdf"
    document.save(path)

    blocks = parse_pdf(path)

    assert len(blocks) == 1
    assert blocks[0].kind is BlockKind.OCR
    assert "capital at risk" in blocks[0].text.lower()
