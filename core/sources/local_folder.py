from __future__ import annotations

import os
import datetime
from pathlib import Path
from typing import Iterable, Any

from core.start_date import get_next_start_date, update_last_processed

class LocalFolderAdapter:
    """Adapter that watches a local directory for new Excel/CSV files.

    It yields Path objects for files whose modification time is newer than the
    stored checkpoint for the given source name.
    """

    def __init__(self, source_name: str, folder_path: str, extensions: list[str] | None = None):
        self.source_name = source_name
        self.folder = Path(folder_path).expanduser().resolve()
        self.extensions = extensions or [".xls", ".xlsx", ".csv"]
        if not self.folder.is_dir():
            raise ValueError(f"LocalFolderAdapter: folder does not exist: {self.folder}")

    def _is_new(self, path: Path) -> bool:
        # Get the checkpoint datetime (UTC) for this source
        try:
            checkpoint_date = get_next_start_date(self.source_name)
        except Exception:
            # If not present, start from epoch
            checkpoint_date = datetime.date(1970, 1, 1)
        # Convert file mtime to date
        file_dt = datetime.datetime.utcfromtimestamp(path.stat().st_mtime).date()
        return file_dt >= checkpoint_date

    def list_new_items(self) -> Iterable[Path]:
        for entry in self.folder.iterdir():
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in self.extensions:
                continue
            if self._is_new(entry):
                yield entry

    def transform(self, item: Path) -> bytes:
        # Simply read the raw file bytes; the ingest manager will upload them as‑is.
        return item.read_bytes()
