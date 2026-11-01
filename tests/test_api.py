"""Tests for the HTTP API."""

import hashlib
import io
import json
import zipfile
from collections.abc import Iterator
from typing import Any

import pymupdf
import pytest
from fastapi.testclient import TestClient
from pptx import Presentation
from pptx.util import Inches

from complianceops.api.app import app
from complianceops.api.dependencies import get_llm
from complianceops.config import Settings, get_settings

MAX_BYTES = 200_000


def _pdf_bytes(*pages: str) -> bytes:
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        for line_number, line in enumerate(text.splitlines()):
            page.insert_text((72, 72 + 20 * line_number), line)
    return bytes(document.tobytes())


def _pptx_bytes(*slides: str) -> bytes:
    deck = Presentation()
    for text in slides:
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
        box.text_frame.text = text
    buffer = io.BytesIO()
    deck.save(buffer)
    return buffer.getvalue()


def _zip_bytes(member: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, "<xml/>")
    return buffer.getvalue()


PDF_BYTES = _pdf_bytes("Some text in a document, long enough to be read.")
PPTX_BYTES = _pptx_bytes("Some text in a deck, long enough to be read.")

COMPLIANT_DECK = _pdf_bytes(
    "This is a marketing communication.\n"
    "Please refer to the prospectus and to the KID before making any final investment decisions.\n"
    "Investment policy: the fund invests in European equities.\n"
    "ISIN FRCOPS000017"
)

VIOLATING_DECK = _pdf_bytes(
    "Sample Global Equity Fund, ISIN FRCOPS000033",
    "A risk-free investment with guaranteed returns.",
    "Past performance: 12% in 2023.",
)


class FakeLlm:
    """An LLM with no objections to anything."""

    def complete(self, prompt: str) -> str:
        return json.dumps({"findings": []})


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: Settings(max_upload_bytes=MAX_BYTES)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _status_by_rule(report: dict[str, Any]) -> dict[str, list[str]]:
    statuses: dict[str, list[str]] = {}
    for verdict in report["verdicts"]:
        statuses.setdefault(verdict["rule_id"], []).append(verdict["status"])
    return statuses


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.parametrize(
    ("filename", "content", "file_type"),
    [
        ("deck.pdf", PDF_BYTES, "pdf"),
        ("DECK.PDF", PDF_BYTES, "pdf"),
        ("deck.pptx", PPTX_BYTES, "pptx"),
    ],
    ids=["pdf", "uppercase_extension", "pptx"],
)
def test_check_accepts_supported_files(
    client: TestClient, filename: str, content: bytes, file_type: str
) -> None:
    response = client.post("/check", files={"file": (filename, content)})

    assert response.status_code == 200
    report = response.json()
    assert report["filename"] == filename
    assert report["file_type"] == file_type
    assert report["size_bytes"] == len(content)
    assert report["sha256"] == hashlib.sha256(content).hexdigest()
    assert "Not legal advice" in report["disclaimer"]


@pytest.mark.parametrize(
    ("filename", "content", "status_code"),
    [
        ("notes.txt", b"plain text", 415),
        ("no_extension", PDF_BYTES, 415),
        ("renamed.pdf", b"plain text", 415),
        ("renamed.pptx", PDF_BYTES, 415),
        ("other_archive.pptx", _zip_bytes("word/document.xml"), 415),
        ("empty.pdf", b"", 400),
        ("large.pdf", b"%PDF-" + b"0" * MAX_BYTES, 413),
        ("corrupt.pdf", b"%PDF-1.7\nthis is not really a pdf", 422),
    ],
    ids=[
        "wrong_extension",
        "no_extension",
        "renamed_to_pdf",
        "renamed_to_pptx",
        "other_archive",
        "empty",
        "too_large",
        "corrupt",
    ],
)
def test_check_rejects_invalid_files(
    client: TestClient, filename: str, content: bytes, status_code: int
) -> None:
    response = client.post("/check", files={"file": (filename, content)})

    assert response.status_code == status_code


def test_check_accepts_file_at_size_limit(client: TestClient) -> None:
    content = PDF_BYTES + b" " * (MAX_BYTES - len(PDF_BYTES))

    response = client.post("/check", files={"file": ("limit.pdf", content)})

    assert response.status_code == 200


def test_check_requires_a_file(client: TestClient) -> None:
    response = client.post("/check")

    assert response.status_code == 422


@pytest.mark.parametrize("country", ["fr", "FRA", "F1"])
def test_check_rejects_malformed_country(client: TestClient, country: str) -> None:
    response = client.post(
        "/check", files={"file": ("deck.pdf", PDF_BYTES)}, data={"target_country": country}
    )

    assert response.status_code == 422


def test_planted_violations_are_found_on_the_right_pages(client: TestClient) -> None:
    response = client.post(
        "/check", files={"file": ("deck.pdf", VIOLATING_DECK)}, data={"target_country": "DE"}
    )

    report = response.json()
    assert report["status"] == "non_compliant"
    fails = {v["rule_id"]: v["page"] for v in report["verdicts"] if v["status"] == "fail"}
    assert fails["LANG-001"] == 2
    assert fails["MC-PERF-001"] == 3
    assert fails["REG-002"] == 1
    assert fails["MC-IDENT-001"] is None
    assert fails["MC-DISC-001"] is None
    assert fails["MC-POLICY-001"] is None


def test_clean_document_without_llm_is_incomplete_not_compliant(client: TestClient) -> None:
    response = client.post(
        "/check", files={"file": ("deck.pdf", COMPLIANT_DECK)}, data={"target_country": "FR"}
    )

    report = response.json()
    statuses = _status_by_rule(report)
    assert report["status"] == "incomplete"
    assert statuses["LANG-001"] == ["not_evaluated"]
    assert statuses["CONS-001"] == ["not_evaluated"]
    assert "fail" not in {status for values in statuses.values() for status in values}


def test_every_rule_is_reported(client: TestClient) -> None:
    response = client.post("/check", files={"file": ("deck.pdf", PDF_BYTES)})

    assert set(_status_by_rule(response.json())) == {
        "MC-IDENT-001",
        "MC-DISC-001",
        "MC-PERF-001",
        "MC-FUTURE-001",
        "MC-FUTURE-002",
        "MC-ESG-001",
        "MC-RISK-001",
        "MC-POLICY-001",
        "MC-COST-001",
        "MC-LEVERAGE-001",
        "LANG-001",
        "CONS-001",
        "REG-001",
        "REG-002",
    }


def test_scanned_style_blank_document_is_incomplete(client: TestClient) -> None:
    response = client.post("/check", files={"file": ("deck.pptx", _pptx_bytes(""))})

    report = response.json()
    assert report["status"] == "incomplete"
    assert {verdict["status"] for verdict in report["verdicts"]} == {"not_evaluated"}


def test_llm_is_used_when_configured(client: TestClient) -> None:
    app.dependency_overrides[get_llm] = FakeLlm

    response = client.post(
        "/check", files={"file": ("deck.pdf", COMPLIANT_DECK)}, data={"target_country": "FR"}
    )

    assert _status_by_rule(response.json())["LANG-001"] == ["pass"]
