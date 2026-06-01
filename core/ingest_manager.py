from __future__ import annotations

import datetime
import logging
import time
from pathlib import Path
from typing import Iterable, Protocol, Tuple, Dict, Any

from google.cloud import storage

from core.start_date import get_next_start_date, update_last_processed

log = logging.getLogger(__name__)

class SourceAdapter(Protocol):
    """Adapter interface for a data source.

    Implementations must provide a way to list new items since the last
    checkpoint and optionally transform them before upload.
    """

    def list_new_items(self) -> Iterable[Any]:
        """Yield new raw items (paths, bytes, etc.) since the last checkpoint."""
        ...

    def transform(self, item: Any) -> bytes:
        """Convert a raw item to the bytes payload to be uploaded to GCS.
        By default, if the item is already ``bytes`` it can be returned as‑is.
        """
        ...

class IngestManager:
    def __init__(self, gcs_project: str, dest_bucket: str, service_account_json: str | None = None):
        self.adapters: Dict[str, SourceAdapter] = {}
        self.project = gcs_project
        self.dest_bucket = dest_bucket
        if service_account_json:
            self.storage_client = storage.Client.from_service_account_json(service_account_json, project=gcs_project)
        else:
            self.storage_client = storage.Client(project=gcs_project)
        self.bucket = self.storage_client.bucket(dest_bucket)

    def register(self, name: str, adapter: SourceAdapter) -> None:
        self.adapters[name] = adapter
        log.info("Registered source adapter %s", name)

    def _upload(self, payload: bytes, blob_name: str, dry_run: bool) -> None:
        if dry_run:
            log.info("[DRY‑RUN] Would upload %s (%d bytes) to %s", blob_name, len(payload), self.dest_bucket)
            return
        blob = self.bucket.blob(blob_name)
        blob.upload_from_string(payload)
        log.info("Uploaded %s (%d bytes) to %s", blob_name, len(payload), self.dest_bucket)

    def run(self, poll_interval: int = 60, dry_run: bool = False) -> None:
        log.info("Starting continuous ingestion loop (interval=%ds, dry_run=%s)", poll_interval, dry_run)
        while True:
            for name, adapter in self.adapters.items():
                try:
                    last_dt = get_next_start_date(name)  # reuse start_date utility as checkpoint
                except Exception:
                    # If no entry, start from epoch
                    last_dt = datetime.datetime(1970, 1, 1)
                for item in adapter.list_new_items():
                    # The adapter is responsible for yielding only items newer than last_dt
                    payload = adapter.transform(item)
                    # Derive a blob name – simple scheme: <source>/<timestamp>_<basename>
                    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
                    if isinstance(item, Path):
                        blob_name = f"{name}/{ts}_{item.name}"
                    else:
                        blob_name = f"{name}/{ts}.bin"
                    self._upload(payload, blob_name, dry_run)
                    # Update checkpoint after successful upload
                    update_last_processed(name, datetime.datetime.utcnow())
                log.debug("Finished processing source %s", name)
            time.sleep(poll_interval)
