"""Streaming ingestion: index files as they appear in a folder.

The folder is polled because file system events do not reach containers through Docker volumes
mounted from Windows or macOS.
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path

from complianceops.ingestion.pipeline import SUPPORTED_SUFFIXES

logger = logging.getLogger(__name__)

_Signature = tuple[int, int]


class FolderWatcher:
    """Calls ``ingest`` once for each new or changed file.

    A file is only ingested once its size and modification time are the same on two polls in a
    row, so files still being copied are left alone. A failed file is retried when it changes.
    """

    def __init__(self, folder: Path, ingest: Callable[[Path], int]) -> None:
        self._folder = folder
        self._ingest = ingest
        self._pending: dict[Path, _Signature] = {}
        self._handled: dict[Path, _Signature] = {}

    def poll_once(self) -> list[Path]:
        """Scan the folder once and return the files successfully ingested."""
        current: dict[Path, _Signature] = {}
        for path in self._folder.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                stat = path.stat()
                current[path] = (stat.st_mtime_ns, stat.st_size)

        ingested = []
        for path, signature in current.items():
            if self._handled.get(path) == signature or self._pending.get(path) != signature:
                continue
            self._handled[path] = signature
            try:
                count = self._ingest(path)
            except Exception:
                logger.exception("Could not ingest %s", path)
                continue
            logger.info("Ingested %s (%d chunks)", path, count)
            ingested.append(path)
        self._pending = current
        return ingested

    def run(self, interval_seconds: float) -> None:
        """Poll until interrupted."""
        while True:
            self.poll_once()
            time.sleep(interval_seconds)
