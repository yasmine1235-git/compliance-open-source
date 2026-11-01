"""Tests for the HTTP API."""

import hashlib
import io
import zipfile
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from complianceops.api.app import app
from complianceops.config import Settings, get_settings

MAX_BYTES = 4096
PDF_BYTES = b"%PDF-1.7\nminimal test content\n"


def _zip_bytes(member: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, "<xml/>")
    return buffer.getvalue()


PPTX_BYTES = _zip_bytes("ppt/presentation.xml")


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: Settings(max_upload_bytes=MAX_BYTES)
    yield TestClient(app)
    app.dependency_overrides.clear()


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
)
def test_check_accepts_supported_files(
    client: TestClient, filename: str, content: bytes, file_type: str
) -> None:
    response = client.post("/check", files={"file": (filename, content)})

    assert response.status_code == 200
    assert response.json() == {
        "filename": filename,
        "file_type": file_type,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "status": "not_evaluated",
        "verdicts": [],
    }


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
    ],
)
def test_check_rejects_invalid_files(
    client: TestClient, filename: str, content: bytes, status_code: int
) -> None:
    response = client.post("/check", files={"file": (filename, content)})

    assert response.status_code == status_code


def test_check_accepts_file_at_size_limit(client: TestClient) -> None:
    content = b"%PDF-" + b"0" * (MAX_BYTES - 5)

    response = client.post("/check", files={"file": ("limit.pdf", content)})

    assert response.status_code == 200


def test_check_requires_a_file(client: TestClient) -> None:
    response = client.post("/check")

    assert response.status_code == 422
