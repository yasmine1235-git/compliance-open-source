"""FastAPI application."""

import asyncio
import hashlib
import logging
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, UploadFile

from complianceops import __version__
from complianceops.agents.llm import LlmClient
from complianceops.agents.models import AgentContext, Retriever
from complianceops.api.dependencies import get_llm, get_retriever
from complianceops.api.schemas import CheckReport, FileType, HealthResponse
from complianceops.api.uploads import UploadRejectedError, validate_upload
from complianceops.config import Settings, get_settings
from complianceops.ingestion.chunking import chunk_blocks
from complianceops.ingestion.models import Block
from complianceops.ingestion.ocr import OcrUnavailableError
from complianceops.ingestion.pipeline import parse_document
from complianceops.orchestrator.graph import run_check

logger = logging.getLogger(__name__)

app = FastAPI(title="ComplianceOps", version=__version__)


def _parse_upload(content: bytes, file_type: FileType) -> list[Block]:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / f"upload.{file_type.value}"
        path.write_bytes(content)
        return parse_document(path)


@app.get("/health")
def health() -> HealthResponse:
    """Report that the API is running."""
    return HealthResponse(status="ok", version=__version__)


@app.post("/check")
async def check(
    file: UploadFile,
    settings: Annotated[Settings, Depends(get_settings)],
    llm: Annotated[LlmClient | None, Depends(get_llm)],
    retrieve: Annotated[Retriever, Depends(get_retriever)],
    target_country: Annotated[str | None, Form(pattern="^[A-Z]{2}$")] = None,
    prospectus_id: Annotated[str | None, Form(min_length=1)] = None,
    prospectus_version: Annotated[str | None, Form(min_length=1)] = None,
) -> CheckReport:
    """Check a PDF or PPTX against the compliance rules and return a report.

    The upload is only kept in a temporary folder while it is parsed.
    """
    filename = file.filename or ""
    # Read one byte past the limit: enough to detect an oversized file without loading all of it.
    content = await file.read(settings.max_upload_bytes + 1)
    try:
        file_type = validate_upload(filename, content, settings.max_upload_bytes)
    except UploadRejectedError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    try:
        blocks = await asyncio.to_thread(_parse_upload, content, file_type)
    except OcrUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Could not parse an upload")
        raise HTTPException(status_code=422, detail="The file could not be read.") from error

    sha256 = hashlib.sha256(content).hexdigest()
    # Short blocks matter here: a heading such as "Risks" is evidence that a section exists.
    chunks = chunk_blocks(blocks, sha256, "upload", filename, min_chars=0)
    context = AgentContext(
        source_doc=filename,
        chunks=chunks,
        target_country=target_country,
        prospectus_id=prospectus_id,
        prospectus_version=prospectus_version,
        llm=llm,
        retrieve=retrieve,
    )
    status, verdicts = await run_check(context)
    return CheckReport(
        filename=filename,
        file_type=file_type,
        size_bytes=len(content),
        sha256=sha256,
        status=status,
        verdicts=verdicts,
    )
