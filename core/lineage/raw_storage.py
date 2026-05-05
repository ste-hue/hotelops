"""Storage backends for raw objects.

Phase 1 used implicit local files (raw_uri = file://). Phase 4 introduces an
explicit backend abstraction so intake_file can dispatch upload (GCS) or
no-op (local/drive).

Spec: 2026-05-05-gcs-raw-staging.md §4
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)


@dataclass
class UploadResult:
    raw_uri: str
    generation: Optional[int]  # None for backends without versioning


class RawStorageBackend(ABC):
    @abstractmethod
    def upload(
        self,
        local_path: Path,
        source_name: str,
        intake_at: datetime,
    ) -> UploadResult:
        """Persist the file to the backend; return the URI by which it can be
        re-read, plus a generation token if the backend versions objects."""

    @abstractmethod
    def download_to_temp(
        self,
        raw_uri: str,
        generation: Optional[int],
    ) -> str:
        """Materialize the raw bytes to a local path the caller can pass to a
        subprocess. Returns the local path (string)."""

    @abstractmethod
    def cleanup(self, local_path: str) -> bool:
        """Remove a temp file created by download_to_temp.

        Returns True if a real cleanup happened (caller should treat the path
        as gone), False if no-op (e.g. LocalBackend returned the original
        file unchanged).
        """


class LocalBackend(RawStorageBackend):
    """Passthrough: file is already on disk; no upload, no download."""

    def upload(
        self,
        local_path: Path,
        source_name: str,
        intake_at: datetime,
    ) -> UploadResult:
        return UploadResult(raw_uri=local_path.resolve().as_uri(), generation=None)

    def download_to_temp(
        self,
        raw_uri: str,
        generation: Optional[int],
    ) -> str:
        parsed = urlparse(raw_uri)
        if parsed.scheme not in ("file", ""):
            raise ValueError(
                f"LocalBackend cannot download {raw_uri!r}; expected file:// scheme"
            )
        return parsed.path

    def cleanup(self, local_path: str) -> bool:
        return False
