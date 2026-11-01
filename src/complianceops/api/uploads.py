"""Validation of uploaded documents."""

import io
import zipfile
from pathlib import PurePath

from complianceops.api.schemas import FileType

_FILE_TYPES_BY_SUFFIX = {".pdf": FileType.PDF, ".pptx": FileType.PPTX}


class UploadRejectedError(Exception):
    """An upload failed validation. ``status_code`` is the HTTP status to return."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _is_pptx(content: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return "ppt/presentation.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def validate_upload(filename: str, content: bytes, max_bytes: int) -> FileType:
    """Return the file type of an upload, or raise ``UploadRejectedError``.

    The content is checked as well as the extension, so a renamed file is rejected.
    """
    file_type = _FILE_TYPES_BY_SUFFIX.get(PurePath(filename).suffix.lower())
    if file_type is None:
        raise UploadRejectedError(415, "Only PDF and PPTX files are supported.")
    if not content:
        raise UploadRejectedError(400, "The uploaded file is empty.")
    if len(content) > max_bytes:
        raise UploadRejectedError(413, f"The uploaded file exceeds {max_bytes} bytes.")

    matches = content.startswith(b"%PDF-") if file_type is FileType.PDF else _is_pptx(content)
    if not matches:
        raise UploadRejectedError(415, f"The file content is not a valid {file_type.value} file.")
    return file_type
