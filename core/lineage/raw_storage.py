"""Storage backends for raw objects.

Phase 1 used implicit local files (raw_uri = file://). Phase 4 introduces an
explicit backend abstraction so intake_file can dispatch upload (GCS) or
no-op (local/drive).

Spec: 2026-05-05-gcs-raw-staging.md §4
"""

from __future__ import annotations

import logging
import os
import tempfile
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


def _storage_client():  # pragma: no cover — patched in tests
    from google.cloud import storage

    return storage.Client(project="hotelops-suite")


class GCSBackend(RawStorageBackend):
    """Uploads to gs://<bucket>/<source>/<YYYY>/<MM>/<filename>.

    Object Versioning is expected to be ON at the bucket level — re-uploads of
    the same key with different bytes produce a new generation. MD5 dedup
    upstream (register_raw_object) avoids re-uploads of byte-identical files.
    """

    def __init__(self, bucket: str) -> None:
        self.bucket = bucket

    def _compute_key(self, source_name: str, intake_at: datetime, filename: str) -> str:
        return f"{source_name}/{intake_at.year:04d}/{intake_at.month:02d}/{filename}"

    def upload(
        self,
        local_path: Path,
        source_name: str,
        intake_at: datetime,
    ) -> UploadResult:
        key = self._compute_key(source_name, intake_at, local_path.name)
        client = _storage_client()
        blob = client.bucket(self.bucket).blob(key)
        # Resumable a chunk: su uplink lento/saturo un file grande in un colpo
        # solo sfora il timeout per-request (default 60s). Ogni chunk è una
        # richiesta autonoma, quindi il timeout vale sul chunk, non sul file.
        blob.chunk_size = 8 * 1024 * 1024
        blob.upload_from_filename(str(local_path), timeout=300)
        # blob.generation is populated after upload_from_filename completes
        log.info(
            "GCS upload ok: gs://%s/%s (generation=%s)",
            self.bucket,
            key,
            blob.generation,
        )
        return UploadResult(
            raw_uri=f"gs://{self.bucket}/{key}",
            generation=blob.generation,
        )

    def download_to_temp(
        self,
        raw_uri: str,
        generation: Optional[int],
    ) -> str:
        parsed = urlparse(raw_uri)
        if parsed.scheme != "gs":
            raise ValueError(
                f"GCSBackend cannot download {raw_uri!r}; expected gs:// scheme"
            )
        if parsed.netloc != self.bucket:
            raise ValueError(
                f"GCSBackend bucket mismatch: configured={self.bucket}, "
                f"uri bucket={parsed.netloc}"
            )
        key = parsed.path.lstrip("/")
        suffix = "_" + os.path.basename(key) if key else ""
        fd, dest = tempfile.mkstemp(prefix="hotelops_raw_", suffix=suffix)
        os.close(fd)

        client = _storage_client()
        blob = (
            client.bucket(self.bucket).blob(key, generation=generation)
            if generation is not None
            else client.bucket(self.bucket).blob(key)
        )
        blob.download_to_filename(dest)
        return dest

    def cleanup(self, local_path: str) -> bool:
        if os.path.exists(local_path):
            os.unlink(local_path)
        return True
