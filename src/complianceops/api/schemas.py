"""Response models for the HTTP API."""

from enum import StrEnum

from pydantic import BaseModel


class FileType(StrEnum):
    """Document formats accepted by ``POST /check``."""

    PDF = "pdf"
    PPTX = "pptx"


class ReportStatus(StrEnum):
    """Overall state of a report.

    ``NOT_EVALUATED`` means no compliance rule was run, and must never be read as a pass.
    """

    NOT_EVALUATED = "not_evaluated"


class HealthResponse(BaseModel):
    """Response of ``GET /health``."""

    status: str
    version: str


class Verdict(BaseModel):
    """Outcome of one rule, with the evidence that supports it."""

    rule_id: str
    status: str
    evidence_text: str
    source_doc: str
    page: int
    chunk_id: str
    agent: str
    latency_ms: float


class CheckReport(BaseModel):
    """Response of ``POST /check``."""

    filename: str
    file_type: FileType
    size_bytes: int
    sha256: str
    status: ReportStatus
    verdicts: list[Verdict]
