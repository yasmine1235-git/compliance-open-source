"""Models for the HTTP API."""

from enum import StrEnum

from pydantic import BaseModel

from complianceops.agents.models import ReportStatus, Verdict

REPORT_DISCLAIMER = (
    "Automated check against draft rules that have not been reviewed by a compliance "
    "professional. Not legal advice."
)


class FileType(StrEnum):
    """Document formats accepted by ``POST /check``."""

    PDF = "pdf"
    PPTX = "pptx"


class HealthResponse(BaseModel):
    """Response of ``GET /health``."""

    status: str
    version: str


class CheckReport(BaseModel):
    """Response of ``POST /check``."""

    filename: str
    file_type: FileType
    size_bytes: int
    sha256: str
    status: ReportStatus
    verdicts: list[Verdict]
    disclaimer: str = REPORT_DISCLAIMER
