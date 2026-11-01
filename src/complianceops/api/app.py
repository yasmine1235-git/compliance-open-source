"""FastAPI application."""

import hashlib
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, UploadFile

from complianceops import __version__
from complianceops.api.schemas import CheckReport, HealthResponse, ReportStatus
from complianceops.api.uploads import UploadRejectedError, validate_upload
from complianceops.config import Settings, get_settings

app = FastAPI(title="ComplianceOps", version=__version__)


@app.get("/health")
def health() -> HealthResponse:
    """Report that the API is running."""
    return HealthResponse(status="ok", version=__version__)


@app.post("/check")
async def check(
    file: UploadFile,
    settings: Annotated[Settings, Depends(get_settings)],
) -> CheckReport:
    """Validate a PDF or PPTX and return its report.

    No compliance rules run yet, so the report is always ``not_evaluated`` with no verdicts.
    The document is not stored.
    """
    filename = file.filename or ""
    # Read one byte past the limit: enough to detect an oversized file without loading all of it.
    content = await file.read(settings.max_upload_bytes + 1)
    try:
        file_type = validate_upload(filename, content, settings.max_upload_bytes)
    except UploadRejectedError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    return CheckReport(
        filename=filename,
        file_type=file_type,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        status=ReportStatus.NOT_EVALUATED,
        verdicts=[],
    )
