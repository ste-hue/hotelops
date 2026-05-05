# GCS Raw Staging — Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land GCS as the immutable Raw layer for one pilot source (`MPS_BANCA_ORTI_APPEND`), closing the doc-vs-implementation drift on `DATAHUB_ONTOLOGY.md`. Other 12 sources stay on Drive backend until a separate bulk-flip PR. Pilot revisited on 2026-05-05: APPEND chosen over SNAPSHOT to exercise content_hash dedup (the technical novelty); see spec §3 D9.

**Architecture:** Add a `RawStorageBackend` ABC with `LocalBackend` (passthrough; Phase 1 behavior) and `GCSBackend` (uploads to `gs://hotelops-raw`, returns URI + generation). `intake_file` selects backend via `source_def.raw_storage.backend`. `_invoke_parser` downloads `gs://` URIs to temp before subprocess dispatch. Add nullable `gcs_generation INT64` to `f_raw_objects` (additive, non-breaking). Phase 1+2 tests must remain green.

**Tech Stack:** Python 3.11, `google-cloud-storage>=2.14`, Pydantic v2, pytest with monkeypatch, gsutil/gcloud for bucket provisioning.

**Spec:** `docs/superpowers/specs/2026-05-05-gcs-raw-staging.md`

**Branch:** `refactor/gcs-raw-staging` (off `main`)

---

## Task 0: Branch + bucket provisioning (controller-only, NOT a subagent task)

This step is executed by the **controller (Stefano or Stefano + Claude in main session)**, not delegated to a subagent. It touches production infrastructure (creates a real GCS bucket).

**Files:**
- Create: `scripts/provision_gcs_bucket.sh`

- [ ] **Step 1: Create branch**

```bash
git checkout main
git pull
git checkout -b refactor/gcs-raw-staging
```

- [ ] **Step 2: Write idempotent provisioning script**

Create `scripts/provision_gcs_bucket.sh`:

```bash
#!/usr/bin/env bash
# Idempotent provisioning of gs://hotelops-raw.
# Safe to re-run: each step is a no-op if state already matches.
set -euo pipefail

PROJECT="hotelops-suite"
BUCKET="hotelops-raw"
LOCATION="EU"

echo "→ Ensuring bucket gs://${BUCKET} (project=${PROJECT}, location=${LOCATION})…"
if gsutil ls -b "gs://${BUCKET}" >/dev/null 2>&1; then
  echo "  bucket already exists, skipping create"
else
  gcloud storage buckets create "gs://${BUCKET}" \
    --project="${PROJECT}" \
    --location="${LOCATION}" \
    --default-storage-class=STANDARD \
    --uniform-bucket-level-access \
    --public-access-prevention
fi

echo "→ Enabling Object Versioning…"
gcloud storage buckets update "gs://${BUCKET}" --versioning

echo "→ Enabling Autoclass with terminal class ARCHIVE…"
gcloud storage buckets update "gs://${BUCKET}" \
  --enable-autoclass \
  --autoclass-terminal-storage-class=ARCHIVE

echo "→ Verifying state…"
gcloud storage buckets describe "gs://${BUCKET}" \
  --format='value(name,versioning.enabled,autoclass.enabled,autoclass.terminalStorageClass,iamConfiguration.publicAccessPrevention,iamConfiguration.uniformBucketLevelAccess.enabled)'

echo "✓ Done. gs://${BUCKET} is ready."
```

```bash
chmod +x scripts/provision_gcs_bucket.sh
```

- [ ] **Step 3: Run the script (Stefano executes; verify before committing)**

```bash
./scripts/provision_gcs_bucket.sh
```

Expected output ends with: `✓ Done. gs://hotelops-raw is ready.`

If `gcloud storage` commands are unavailable, fall back to `gsutil versioning set on gs://hotelops-raw` etc. — the script can be adjusted.

- [ ] **Step 4: Commit script**

```bash
git add scripts/provision_gcs_bucket.sh
git commit -m "infra(gcs): idempotent bucket provisioning script for hotelops-raw"
```

---

## Task 1: Schema — add `gcs_generation` to RawObject + DDL

**Files:**
- Modify: `core/lineage/schemas.py`
- Modify: `core/bq/load/load_lineage_tables.py`
- Test: `tests/test_lineage_schemas.py` (add cases)
- New: `core/bq/migrations/2026_05_05_add_gcs_generation.py`

- [ ] **Step 1: Write the failing test for Pydantic field**

Append to `tests/test_lineage_schemas.py`:

```python
def test_raw_object_accepts_gcs_generation():
    from core.lineage.schemas import RawObject
    from datetime import datetime, timezone

    row = RawObject(
        raw_object_id="r1",
        content_hash="h",
        raw_uri="gs://hotelops-raw/k/v.xlsx",
        raw_backend="gcs",
        file_name_original="v.xlsx",
        bytes_size=1,
        intake_at=datetime.now(timezone.utc),
        intake_actor="x",
        pipeline_run_id="run",
        pipeline_name="ingest_intake",
        ingestion_ts=datetime.now(timezone.utc),
        gcs_generation=1715000000123456,
    )
    assert row.gcs_generation == 1715000000123456


def test_raw_object_gcs_generation_optional_default_none():
    from core.lineage.schemas import RawObject
    from datetime import datetime, timezone

    row = RawObject(
        raw_object_id="r2",
        content_hash="h2",
        raw_uri="file:///tmp/x.xlsx",
        raw_backend="local",
        file_name_original="x.xlsx",
        bytes_size=1,
        intake_at=datetime.now(timezone.utc),
        intake_actor="x",
        pipeline_run_id="run",
        pipeline_name="ingest_intake",
        ingestion_ts=datetime.now(timezone.utc),
    )
    assert row.gcs_generation is None
```

- [ ] **Step 2: Run test — must fail**

```bash
pytest tests/test_lineage_schemas.py::test_raw_object_accepts_gcs_generation -v
```

Expected: FAIL with `ValidationError` or `unexpected keyword argument`.

- [ ] **Step 3: Add field to `RawObject` in `core/lineage/schemas.py`**

Locate the `RawObject` class and add (alphabetically near other Optional fields):

```python
    gcs_generation: Optional[int] = None
```

- [ ] **Step 4: Run tests — must pass**

```bash
pytest tests/test_lineage_schemas.py -v
```

Expected: all pass (including the two new tests + previous Phase 1 tests).

- [ ] **Step 5: Update DDL in `core/bq/load/load_lineage_tables.py`**

Find the `_F_RAW_OBJECTS_DDL` (or equivalent named constant) and add `gcs_generation INT64` to the column list (nullable; place after `raw_backend` for logical grouping).

If the DDL is a triple-quoted string, the change is:

```sql
  raw_backend STRING NOT NULL OPTIONS(description="..."),
  gcs_generation INT64 OPTIONS(description="GCS object generation when raw_backend='gcs'; NULL otherwise"),
  file_name_original STRING NOT NULL,
```

- [ ] **Step 6: Write migration script (one-shot ALTER TABLE)**

Create `core/bq/migrations/2026_05_05_add_gcs_generation.py`:

```python
"""One-shot migration: ALTER TABLE f_raw_objects ADD COLUMN gcs_generation INT64.

Idempotent: probes column existence via INFORMATION_SCHEMA before altering.
Run: python -m core.bq.migrations.2026_05_05_add_gcs_generation
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

PROJECT = "hotelops-suite"
DATASET = "hotelops"
TABLE = "f_raw_objects"
COLUMN = "gcs_generation"


def column_exists() -> bool:
    from core.bq.client import get_client

    client = get_client()
    sql = f"""
    SELECT 1
    FROM `{PROJECT}.{DATASET}.INFORMATION_SCHEMA.COLUMNS`
    WHERE table_name = '{TABLE}' AND column_name = '{COLUMN}'
    """
    return any(client.query(sql).result())


def run(dry_run: bool = False) -> None:
    if column_exists():
        log.info("Column %s.%s.%s already exists — no-op.", DATASET, TABLE, COLUMN)
        return

    sql = (
        f"ALTER TABLE `{PROJECT}.{DATASET}.{TABLE}` "
        f"ADD COLUMN {COLUMN} INT64 "
        f"OPTIONS(description=\"GCS object generation when raw_backend='gcs'; NULL otherwise\")"
    )
    if dry_run:
        log.info("[DRY RUN] would execute: %s", sql)
        return

    from core.bq.client import get_client

    client = get_client()
    client.query(sql).result()
    log.info("ALTER TABLE complete: added %s.%s.%s", DATASET, TABLE, COLUMN)


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Write idempotency test for migration**

Create `tests/test_migration_add_gcs_generation.py`:

```python
"""Migration is idempotent and emits the right ALTER when column missing."""

from unittest.mock import MagicMock

from core.bq.migrations import (
    add_gcs_generation := __import__(
        "core.bq.migrations.2026_05_05_add_gcs_generation",
        fromlist=["run", "column_exists"],
    )
)


def test_migration_skips_when_column_exists(monkeypatch) -> None:
    monkeypatch.setattr(add_gcs_generation, "column_exists", lambda: True)
    fake_client = MagicMock()
    monkeypatch.setattr("core.bq.client.get_client", lambda: fake_client)

    add_gcs_generation.run(dry_run=False)

    fake_client.query.assert_not_called()


def test_migration_runs_alter_when_column_missing(monkeypatch) -> None:
    monkeypatch.setattr(add_gcs_generation, "column_exists", lambda: False)
    fake_client = MagicMock()
    monkeypatch.setattr("core.bq.client.get_client", lambda: fake_client)

    add_gcs_generation.run(dry_run=False)

    fake_client.query.assert_called_once()
    sql_arg = fake_client.query.call_args[0][0]
    assert "ALTER TABLE" in sql_arg
    assert "gcs_generation INT64" in sql_arg
```

(Note: walrus syntax above is illustrative; use a plain `import importlib` + `importlib.import_module(...)` if simpler. Filename has a digit prefix that's not a valid Python identifier — use `importlib`.)

Cleaner version:

```python
import importlib
from unittest.mock import MagicMock

mig = importlib.import_module("core.bq.migrations.2026_05_05_add_gcs_generation")


def test_migration_skips_when_column_exists(monkeypatch) -> None:
    monkeypatch.setattr(mig, "column_exists", lambda: True)
    fake_client = MagicMock()
    monkeypatch.setattr("core.bq.client.get_client", lambda: fake_client)

    mig.run(dry_run=False)

    fake_client.query.assert_not_called()


def test_migration_runs_alter_when_column_missing(monkeypatch) -> None:
    monkeypatch.setattr(mig, "column_exists", lambda: False)
    fake_client = MagicMock()
    monkeypatch.setattr("core.bq.client.get_client", lambda: fake_client)

    mig.run(dry_run=False)

    fake_client.query.assert_called_once()
    sql_arg = fake_client.query.call_args[0][0]
    assert "ALTER TABLE" in sql_arg
    assert "gcs_generation INT64" in sql_arg
```

Also create `core/bq/migrations/__init__.py` (empty) if it doesn't exist.

- [ ] **Step 8: Run tests**

```bash
pytest tests/test_migration_add_gcs_generation.py tests/test_lineage_schemas.py -v
```

Expected: all pass.

- [ ] **Step 9: Run full suite — must remain green**

```bash
pytest -q
```

- [ ] **Step 10: Lint + format**

```bash
ruff check . && ruff format core/lineage/schemas.py core/bq/load/load_lineage_tables.py core/bq/migrations/ tests/test_migration_add_gcs_generation.py tests/test_lineage_schemas.py
```

- [ ] **Step 11: Commit**

```bash
git add core/lineage/schemas.py core/bq/load/load_lineage_tables.py core/bq/migrations/ tests/test_migration_add_gcs_generation.py tests/test_lineage_schemas.py
git commit -m "feat(lineage): add gcs_generation column to RawObject + DDL + migration"
```

- [ ] **Step 12: Apply migration to BQ production (controller-executed, NOT a subagent task)**

```bash
python -m core.bq.migrations.2026_05_05_add_gcs_generation --dry-run
python -m core.bq.migrations.2026_05_05_add_gcs_generation
```

Verify:

```bash
bq show --schema --format=prettyjson hotelops-suite:hotelops.f_raw_objects | grep -A 1 gcs_generation
```

Expected: shows `"name": "gcs_generation", "type": "INTEGER"`.

---

## Task 2: `RawStorageBackend` ABC + `LocalBackend` (passthrough)

**Files:**
- Create: `core/lineage/raw_storage.py`
- Create: `tests/test_raw_storage_local.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_raw_storage_local.py`:

```python
"""LocalBackend: passthrough behavior — Phase 1 semantics preserved."""

from datetime import datetime, timezone
from pathlib import Path

import pytest


def test_local_backend_returns_file_uri_no_upload(tmp_path: Path) -> None:
    from core.lineage.raw_storage import LocalBackend, UploadResult

    f = tmp_path / "x.xlsx"
    f.write_bytes(b"abc")

    backend = LocalBackend()
    result = backend.upload(
        local_path=f,
        source_name="ANY_X_Y_Z",
        intake_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
    )

    assert isinstance(result, UploadResult)
    assert result.raw_uri == f.resolve().as_uri()
    assert result.generation is None  # local has no generation


def test_local_backend_download_is_identity(tmp_path: Path) -> None:
    from core.lineage.raw_storage import LocalBackend

    f = tmp_path / "x.xlsx"
    f.write_bytes(b"abc")

    backend = LocalBackend()
    dest = backend.download_to_temp(raw_uri=f.resolve().as_uri(), generation=None)

    assert Path(dest).read_bytes() == b"abc"
    # LocalBackend may return the original path (no copy needed)
    # — caller must not unlink it. Document via cleanup() returning False.
    assert backend.cleanup(dest) is False


def test_local_backend_rejects_non_file_uri() -> None:
    from core.lineage.raw_storage import LocalBackend

    with pytest.raises(ValueError, match="LocalBackend"):
        LocalBackend().download_to_temp(raw_uri="gs://bucket/key", generation=None)
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/test_raw_storage_local.py -v
```

Expected: FAIL with `ModuleNotFoundError: core.lineage.raw_storage`.

- [ ] **Step 3: Implement `core/lineage/raw_storage.py`**

```python
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
```

- [ ] **Step 4: Run tests — must pass**

```bash
pytest tests/test_raw_storage_local.py -v
```

- [ ] **Step 5: Lint + format + commit**

```bash
ruff check . && ruff format core/lineage/raw_storage.py tests/test_raw_storage_local.py
git add core/lineage/raw_storage.py tests/test_raw_storage_local.py
git commit -m "feat(lineage): RawStorageBackend ABC + LocalBackend passthrough (task 2)"
```

---

## Task 3: `GCSBackend` (with mocked Client)

**Files:**
- Modify: `core/lineage/raw_storage.py`
- Modify: `pyproject.toml`
- Create: `tests/test_raw_storage_gcs.py`

- [ ] **Step 1: Add `google-cloud-storage` dep**

Edit `pyproject.toml`. Find the `dependencies = [...]` block and add:

```toml
  "google-cloud-storage>=2.14",
```

(Place near the existing `google-cloud-bigquery` line.)

- [ ] **Step 2: Install**

```bash
pip install -e ".[dev]"
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_raw_storage_gcs.py`:

```python
"""GCSBackend: upload + key formatting + download + cleanup, fully mocked."""

import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_storage_client(monkeypatch):
    """Patch google.cloud.storage.Client with a MagicMock."""
    fake_blob = MagicMock()
    fake_blob.generation = 1715000000123456
    fake_bucket = MagicMock()
    fake_bucket.blob = MagicMock(return_value=fake_blob)
    fake_client = MagicMock()
    fake_client.bucket = MagicMock(return_value=fake_bucket)

    import core.lineage.raw_storage as rs

    monkeypatch.setattr(rs, "_storage_client", lambda: fake_client)
    return fake_client, fake_bucket, fake_blob


def test_gcs_backend_key_format(tmp_path: Path) -> None:
    from core.lineage.raw_storage import GCSBackend

    f = tmp_path / "situazione_partite.xlsx"
    f.write_bytes(b"x")

    backend = GCSBackend(bucket="hotelops-raw")
    key = backend._compute_key(
        source_name="ESOLVER_PARTITE_ORTI_SNAPSHOT",
        intake_at=datetime(2026, 5, 5, 14, 30, tzinfo=timezone.utc),
        filename="situazione_partite.xlsx",
    )
    assert key == "ESOLVER_PARTITE_ORTI_SNAPSHOT/2026/05/situazione_partite.xlsx"


def test_gcs_backend_upload_returns_uri_and_generation(
    fake_storage_client, tmp_path: Path
) -> None:
    fake_client, fake_bucket, fake_blob = fake_storage_client
    from core.lineage.raw_storage import GCSBackend, UploadResult

    f = tmp_path / "x.xlsx"
    f.write_bytes(b"abc")

    backend = GCSBackend(bucket="hotelops-raw")
    result = backend.upload(
        local_path=f,
        source_name="ESOLVER_PARTITE_ORTI_SNAPSHOT",
        intake_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
    )

    assert isinstance(result, UploadResult)
    assert result.raw_uri == "gs://hotelops-raw/ESOLVER_PARTITE_ORTI_SNAPSHOT/2026/05/x.xlsx"
    assert result.generation == 1715000000123456
    fake_client.bucket.assert_called_once_with("hotelops-raw")
    fake_bucket.blob.assert_called_once_with(
        "ESOLVER_PARTITE_ORTI_SNAPSHOT/2026/05/x.xlsx"
    )
    fake_blob.upload_from_filename.assert_called_once_with(str(f))


def test_gcs_backend_download_to_temp_writes_bytes(
    fake_storage_client, tmp_path: Path
) -> None:
    fake_client, fake_bucket, fake_blob = fake_storage_client

    def fake_download(dest_path: str) -> None:
        Path(dest_path).write_bytes(b"downloaded-bytes")

    fake_blob.download_to_filename.side_effect = fake_download

    from core.lineage.raw_storage import GCSBackend

    backend = GCSBackend(bucket="hotelops-raw")
    local = backend.download_to_temp(
        raw_uri="gs://hotelops-raw/ESOLVER_PARTITE_ORTI_SNAPSHOT/2026/05/x.xlsx",
        generation=1715000000123456,
    )

    try:
        assert Path(local).read_bytes() == b"downloaded-bytes"
        # bucket.blob called with the key + generation kwarg
        fake_bucket.blob.assert_called_with(
            "ESOLVER_PARTITE_ORTI_SNAPSHOT/2026/05/x.xlsx",
            generation=1715000000123456,
        )
    finally:
        if os.path.exists(local):
            os.unlink(local)


def test_gcs_backend_cleanup_removes_temp(tmp_path: Path) -> None:
    from core.lineage.raw_storage import GCSBackend

    f = tmp_path / "tmp_dl.xlsx"
    f.write_bytes(b"x")

    backend = GCSBackend(bucket="hotelops-raw")
    assert backend.cleanup(str(f)) is True
    assert not f.exists()


def test_gcs_backend_rejects_non_gs_uri() -> None:
    from core.lineage.raw_storage import GCSBackend

    with pytest.raises(ValueError, match="GCSBackend"):
        GCSBackend(bucket="hotelops-raw").download_to_temp(
            raw_uri="file:///tmp/x", generation=None
        )


def test_gcs_backend_rejects_uri_for_different_bucket() -> None:
    from core.lineage.raw_storage import GCSBackend

    with pytest.raises(ValueError, match="bucket mismatch"):
        GCSBackend(bucket="hotelops-raw").download_to_temp(
            raw_uri="gs://other-bucket/key", generation=1
        )
```

- [ ] **Step 4: Run — must fail**

```bash
pytest tests/test_raw_storage_gcs.py -v
```

Expected: FAIL with `ImportError` on `GCSBackend`.

- [ ] **Step 5: Implement `GCSBackend`**

Append to `core/lineage/raw_storage.py`:

```python
import os
import tempfile


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

    def _compute_key(
        self, source_name: str, intake_at: datetime, filename: str
    ) -> str:
        return (
            f"{source_name}/"
            f"{intake_at.year:04d}/{intake_at.month:02d}/"
            f"{filename}"
        )

    def upload(
        self,
        local_path: Path,
        source_name: str,
        intake_at: datetime,
    ) -> UploadResult:
        key = self._compute_key(source_name, intake_at, local_path.name)
        client = _storage_client()
        blob = client.bucket(self.bucket).blob(key)
        blob.upload_from_filename(str(local_path))
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
```

- [ ] **Step 6: Run tests — must pass**

```bash
pytest tests/test_raw_storage_gcs.py tests/test_raw_storage_local.py -v
```

- [ ] **Step 7: Lint + format**

```bash
ruff check . && ruff format core/lineage/raw_storage.py tests/test_raw_storage_gcs.py pyproject.toml
```

- [ ] **Step 8: Commit**

```bash
git add core/lineage/raw_storage.py tests/test_raw_storage_gcs.py pyproject.toml
git commit -m "feat(lineage): GCSBackend with key format YYYY/MM + Object Versioning support (task 3)"
```

---

## Task 4: `register_raw_object` accepts `gcs_generation`

**Files:**
- Modify: `core/lineage/raw_manifest.py`
- Test: `tests/test_raw_manifest.py` (add cases)

- [ ] **Step 1: Failing test**

Append to `tests/test_raw_manifest.py`:

```python
def test_register_raw_object_persists_gcs_generation(monkeypatch) -> None:
    from core.lineage import raw_manifest

    captured: list = []
    monkeypatch.setattr(
        raw_manifest, "_lookup_existing_by_hash", lambda h: None
    )
    monkeypatch.setattr(
        raw_manifest,
        "bq_write_validated",
        lambda table, rows, mode: captured.append((table, rows, mode)),
    )

    rid = raw_manifest.register_raw_object(
        content_hash="h",
        raw_uri="gs://hotelops-raw/k/v.xlsx",
        raw_backend="gcs",
        file_name_original="v.xlsx",
        bytes_size=1,
        intake_actor="cli",
        gcs_generation=1715000000123456,
    )

    assert rid
    table, rows, mode = captured[0]
    assert mode == "append"
    row = rows[0]
    assert row.raw_backend == "gcs"
    assert row.raw_uri == "gs://hotelops-raw/k/v.xlsx"
    assert row.gcs_generation == 1715000000123456


def test_register_raw_object_default_gcs_generation_none(monkeypatch) -> None:
    from core.lineage import raw_manifest

    captured: list = []
    monkeypatch.setattr(raw_manifest, "_lookup_existing_by_hash", lambda h: None)
    monkeypatch.setattr(
        raw_manifest,
        "bq_write_validated",
        lambda table, rows, mode: captured.append((table, rows, mode)),
    )

    raw_manifest.register_raw_object(
        content_hash="h2",
        raw_uri="file:///tmp/x.xlsx",
        raw_backend="local",
        file_name_original="x.xlsx",
        bytes_size=1,
        intake_actor="cli",
    )

    row = captured[0][1][0]
    assert row.gcs_generation is None
```

- [ ] **Step 2: Run — must fail (function does not accept kwarg)**

```bash
pytest tests/test_raw_manifest.py::test_register_raw_object_persists_gcs_generation -v
```

- [ ] **Step 3: Add `gcs_generation` parameter to `register_raw_object`**

Edit `core/lineage/raw_manifest.py`. Update signature:

```python
def register_raw_object(
    content_hash: str,
    raw_uri: str,
    raw_backend: RawBackend,
    file_name_original: str,
    bytes_size: int,
    intake_actor: str,
    file_name_canonical: Optional[str] = None,
    source_name: Optional[str] = None,
    detector_category: Optional[str] = None,
    societa_id: Optional[str] = None,
    business_unit_id: Optional[str] = None,
    banca_id: Optional[str] = None,
    file_sorgente: Optional[str] = None,
    gcs_generation: Optional[int] = None,
) -> str:
```

And in the `RawObject(...)` construction, add the field:

```python
    row = RawObject(
        # ... existing fields ...
        gcs_generation=gcs_generation,
    )
```

- [ ] **Step 4: Run tests — must pass**

```bash
pytest tests/test_raw_manifest.py -v
```

- [ ] **Step 5: Lint + format + commit**

```bash
ruff check . && ruff format core/lineage/raw_manifest.py tests/test_raw_manifest.py
git add core/lineage/raw_manifest.py tests/test_raw_manifest.py
git commit -m "feat(lineage): register_raw_object accepts gcs_generation (task 4)"
```

---

## Task 5: Validate `raw_storage.backend` ∈ {drive, local, gcs} at boot

**Files:**
- Modify: `core/lineage/source_resolver.py` (add validation)
- Modify: `core/lineage/schemas.py` (extend `RawStorage.backend` if needed)
- Test: `tests/test_source_resolver.py` (add cases)

- [ ] **Step 1: Failing test**

Append to `tests/test_source_resolver.py`:

```python
def test_load_registry_rejects_unknown_backend(tmp_path) -> None:
    yaml_text = """
version: 1
sources:
  X_Y_ORTI_APPEND:
    system: X
    dataset: Y
    societa: ORTI
    lifecycle: APPEND
    canonical_table: f_x
    parser_module: ingest.fake
    hash_basis: hash_riga
    loop_targets: [some_loop]
    promotion_policy: AUTO
    detector_category: x
    raw_storage:
      backend: floppy_disk
      path_template: "x"
"""
    p = tmp_path / "registry.yaml"
    p.write_text(yaml_text)

    from core.lineage.source_resolver import load_registry
    import pytest

    with pytest.raises(ValueError, match="backend"):
        load_registry(p)


def test_load_registry_accepts_gcs_backend(tmp_path) -> None:
    yaml_text = """
version: 1
sources:
  X_Y_ORTI_APPEND:
    system: X
    dataset: Y
    societa: ORTI
    lifecycle: APPEND
    canonical_table: f_x
    parser_module: ingest.fake
    hash_basis: hash_riga
    loop_targets: [some_loop]
    promotion_policy: AUTO
    detector_category: x
    raw_storage:
      backend: gcs
      bucket: hotelops-raw
      path_template: "x"
"""
    p = tmp_path / "registry.yaml"
    p.write_text(yaml_text)

    from core.lineage.source_resolver import load_registry

    reg = load_registry(p)
    assert reg.get("X_Y_ORTI_APPEND").raw_storage.backend == "gcs"
```

- [ ] **Step 2: Run — must fail**

```bash
pytest tests/test_source_resolver.py::test_load_registry_rejects_unknown_backend -v
```

- [ ] **Step 3: Add backend validation**

Open `core/lineage/schemas.py`, locate the `RawStorage` model, and constrain
`backend`:

```python
from typing import Literal

class RawStorage(BaseModel):
    backend: Literal["drive", "local", "gcs"]
    path_template: Optional[str] = None
    bucket: Optional[str] = None
```

(If `RawStorage` already exists with `backend: str`, narrow it to `Literal[...]`.)

If using a `field_validator` style instead of `Literal` is needed (e.g. for
better error messages), replace with:

```python
    backend: str

    @field_validator("backend")
    @classmethod
    def _check_backend(cls, v: str) -> str:
        allowed = {"drive", "local", "gcs"}
        if v not in allowed:
            raise ValueError(f"backend must be one of {sorted(allowed)}, got {v!r}")
        return v
```

- [ ] **Step 4: Run tests — must pass**

```bash
pytest tests/test_source_resolver.py -v
```

(If the rejection test still fails because the error type is `ValidationError`
not `ValueError`, adjust the test's `pytest.raises` to the actual exception
class — Pydantic's `ValidationError` wraps `ValueError`s; `match="backend"`
should still work.)

- [ ] **Step 5: Lint + format + commit**

```bash
ruff check . && ruff format core/lineage/schemas.py core/lineage/source_resolver.py tests/test_source_resolver.py
git add core/lineage/schemas.py core/lineage/source_resolver.py tests/test_source_resolver.py
git commit -m "feat(lineage): validate raw_storage.backend ∈ {drive,local,gcs} at boot (task 5)"
```

---

## Task 6: `intake_file` selects backend via `source_def`

**Files:**
- Modify: `ingest/intake.py`
- Create: `tests/test_intake_gcs.py`

- [ ] **Step 1: Failing test**

Create `tests/test_intake_gcs.py`:

```python
"""intake_file dispatches to GCSBackend when source_def says backend=gcs."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fixture_file(tmp_path: Path) -> Path:
    f = tmp_path / "situazione_partite.xlsx"
    f.write_bytes(b"fake")
    return f


@pytest.fixture
def patch_intake_deps(monkeypatch):
    """Stub register_raw_object + emit_event; capture calls."""
    captured = {"register": [], "events": []}
    monkeypatch.setattr(
        "ingest.intake.register_raw_object",
        lambda **kw: captured["register"].append(kw) or "raw-id-123",
    )
    monkeypatch.setattr(
        "ingest.intake.emit_event",
        lambda **kw: captured["events"].append(kw) or "ev-1",
    )
    return captured


def test_intake_with_gcs_source_uploads_and_records_uri_generation(
    monkeypatch, fixture_file: Path, patch_intake_deps
) -> None:
    fake_source = MagicMock()
    fake_source.source_name = "ESOLVER_PARTITE_ORTI_SNAPSHOT"
    fake_source.societa = "ORTI"
    fake_source.business_unit = None
    fake_source.detector_category = "partite_fornitori"
    fake_source.raw_storage = MagicMock(backend="gcs", bucket="hotelops-raw")
    fake_source.loop_targets = ["cash_control"]
    fake_source.promotion_policy = "AUTO"

    fake_reg = MagicMock()
    fake_reg.get = lambda name: fake_source if name == fake_source.source_name else None
    monkeypatch.setattr("ingest.intake.load_registry", lambda: fake_reg)

    upload_calls: list = []

    class FakeGCSBackend:
        def __init__(self, bucket): self.bucket = bucket
        def upload(self, local_path, source_name, intake_at):
            upload_calls.append((local_path, source_name, intake_at, self.bucket))
            from core.lineage.raw_storage import UploadResult
            return UploadResult(
                raw_uri=f"gs://{self.bucket}/{source_name}/2026/05/{local_path.name}",
                generation=1715000000123456,
            )

    monkeypatch.setattr("ingest.intake.GCSBackend", FakeGCSBackend)

    from ingest.intake import intake_file

    result = intake_file(
        path=fixture_file,
        source_name="ESOLVER_PARTITE_ORTI_SNAPSHOT",
        actor="test",
    )

    assert result.raw_object_id == "raw-id-123"
    assert len(upload_calls) == 1
    assert upload_calls[0][1] == "ESOLVER_PARTITE_ORTI_SNAPSHOT"
    assert upload_calls[0][3] == "hotelops-raw"

    reg_call = patch_intake_deps["register"][0]
    assert reg_call["raw_backend"] == "gcs"
    assert reg_call["raw_uri"].startswith("gs://hotelops-raw/")
    assert reg_call["gcs_generation"] == 1715000000123456


def test_intake_with_drive_source_does_not_upload(
    monkeypatch, fixture_file: Path, patch_intake_deps
) -> None:
    fake_source = MagicMock()
    fake_source.source_name = "ESOLVER_BILANCINO_ORTI_SNAPSHOT"
    fake_source.societa = "ORTI"
    fake_source.business_unit = None
    fake_source.detector_category = "bilancino"
    fake_source.raw_storage = MagicMock(backend="drive", bucket=None)
    fake_source.loop_targets = ["budget_canonical"]
    fake_source.promotion_policy = "AUTO"

    fake_reg = MagicMock()
    fake_reg.get = lambda name: fake_source if name == fake_source.source_name else None
    monkeypatch.setattr("ingest.intake.load_registry", lambda: fake_reg)

    gcs_init_calls = []

    class FakeGCSBackend:
        def __init__(self, bucket): gcs_init_calls.append(bucket)

    monkeypatch.setattr("ingest.intake.GCSBackend", FakeGCSBackend)

    from ingest.intake import intake_file

    intake_file(
        path=fixture_file,
        source_name="ESOLVER_BILANCINO_ORTI_SNAPSHOT",
        actor="test",
    )

    assert gcs_init_calls == [], "GCSBackend must not be instantiated for drive backend"
    reg_call = patch_intake_deps["register"][0]
    assert reg_call["raw_backend"] == "drive"
    assert reg_call["raw_uri"].startswith("file://")
    assert reg_call.get("gcs_generation") is None


def test_intake_without_source_name_stays_local(
    monkeypatch, fixture_file: Path, patch_intake_deps
) -> None:
    """No source → no GCS upload (Q4 decision: sourceless intake stays local)."""
    gcs_init_calls = []

    class FakeGCSBackend:
        def __init__(self, bucket): gcs_init_calls.append(bucket)

    monkeypatch.setattr("ingest.intake.GCSBackend", FakeGCSBackend)

    from ingest.intake import intake_file

    intake_file(path=fixture_file, source_name=None, actor="test")

    assert gcs_init_calls == []
    reg_call = patch_intake_deps["register"][0]
    assert reg_call["raw_backend"] == "local"
    assert reg_call["raw_uri"].startswith("file://")
```

- [ ] **Step 2: Run — must fail (no GCSBackend import in intake)**

```bash
pytest tests/test_intake_gcs.py -v
```

- [ ] **Step 3: Modify `ingest/intake.py`**

Replace the body of `intake_file` to dispatch on `source_def.raw_storage.backend`. The new flow:

```python
from datetime import datetime, timezone
from core.lineage.raw_storage import GCSBackend, LocalBackend, UploadResult


def intake_file(
    path: Path,
    source_name: Optional[str] = None,
    actor: str = "cli",
) -> IntakeResult:
    """Register a file in the lineage layer.

    Backend is selected from source_def.raw_storage.backend:
      - drive | local → file kept on local disk, raw_uri = file://...
      - gcs → file uploaded to gs://<bucket>/<source>/<YYYY>/<MM>/<filename>,
              raw_uri = gs://..., gcs_generation populated
    Sourceless intake (source_name=None) is always treated as local.
    """
    if not path.exists():
        raise FileNotFoundError(path)

    content_hash = _file_md5(path)
    bytes_size = path.stat().st_size

    source_def = None
    if source_name is not None:
        reg = load_registry()
        source_def = reg.get(source_name)
        if source_def is None:
            raise KeyError(f"source_name not in registry: {source_name}")
        enforce_loop_target_gate_consistency(source_def)

    backend_kind = (
        source_def.raw_storage.backend
        if source_def and source_def.raw_storage
        else "local"
    )
    intake_at = datetime.now(timezone.utc)

    if backend_kind == "gcs":
        bucket = source_def.raw_storage.bucket or "hotelops-raw"
        backend = GCSBackend(bucket=bucket)
        upload_result = backend.upload(
            local_path=path, source_name=source_name, intake_at=intake_at
        )
    else:
        # drive | local: passthrough
        backend = LocalBackend()
        upload_result = backend.upload(
            local_path=path, source_name=source_name or "_unclassified", intake_at=intake_at
        )

    with PipelineRun(
        "ingest_intake",
        societa_id=source_def.societa if source_def else None,
        file_sorgente=str(path),
    ):
        raw_object_id = register_raw_object(
            content_hash=content_hash,
            raw_uri=upload_result.raw_uri,
            raw_backend=backend_kind,
            file_name_original=path.name,
            bytes_size=bytes_size,
            intake_actor=actor,
            source_name=source_name,
            detector_category=source_def.detector_category if source_def else None,
            societa_id=source_def.societa if source_def else None,
            business_unit_id=source_def.business_unit if source_def else None,
            file_sorgente=str(path),
            gcs_generation=upload_result.generation,
        )

        emit_event(
            raw_object_id=raw_object_id,
            event_type="RAW_INGESTED",
            actor=actor,
            from_status=None,
            to_status="RAW_ONLY",
            payload={
                "file_name": path.name,
                "bytes_size": bytes_size,
                "raw_backend": backend_kind,
                "gcs_generation": upload_result.generation,
            },
        )

    return IntakeResult(
        raw_object_id=raw_object_id,
        content_hash=content_hash,
        source_name=source_name,
        deduped=False,
    )
```

Remove the old `raw_backend` and `raw_uri` parameters from the public signature (the new flow derives them). If callers pass them today, they'll get a `TypeError`. Phase 2 `cmd_drop --lineage` calls `intake_file(r.file_path, source_name=..., actor="drop_shadow")` — no extra kwargs — so it remains compatible.

Verify no other caller passes `raw_backend` or `raw_uri`:

```bash
grep -rn "intake_file(" --include="*.py" | grep -v "tests/" | grep -v "intake.py"
```

- [ ] **Step 4: Run tests — must pass**

```bash
pytest tests/test_intake_gcs.py tests/test_intake.py tests/test_drop_shadow.py -v
```

(All must remain green; especially `test_drop_shadow.py` exercises the Phase 2 path.)

- [ ] **Step 5: Run full suite**

```bash
pytest -q
```

- [ ] **Step 6: Lint + format + commit**

```bash
ruff check . && ruff format ingest/intake.py tests/test_intake_gcs.py
git add ingest/intake.py tests/test_intake_gcs.py
git commit -m "feat(intake): backend dispatch — GCS upload when source_def says backend=gcs (task 6)"
```

---

## Task 7: `_invoke_parser` supports `gs://` via download-to-temp

**Files:**
- Modify: `ingest/promotion.py`
- Test: `tests/test_promotion.py` (add cases)

- [ ] **Step 1: Failing test**

Append to `tests/test_promotion.py`:

```python
def test_invoke_parser_downloads_gs_uri_to_temp(monkeypatch, tmp_path) -> None:
    """gs:// raw_uri → download to temp → subprocess gets a local path."""
    from unittest.mock import MagicMock
    from ingest import promotion

    # Stub backend
    download_calls = []
    cleanup_calls = []
    fake_local = str(tmp_path / "downloaded.xlsx")
    (tmp_path / "downloaded.xlsx").write_bytes(b"x")

    class FakeGCSBackend:
        def __init__(self, bucket):
            self.bucket = bucket
        def download_to_temp(self, raw_uri, generation):
            download_calls.append((raw_uri, generation))
            return fake_local
        def cleanup(self, p):
            cleanup_calls.append(p)
            return True

    monkeypatch.setattr(promotion, "GCSBackend", FakeGCSBackend)

    # Stub subprocess
    captured = []

    def fake_run(cmd, **kw):
        captured.append(cmd)
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        return result

    monkeypatch.setattr("ingest.promotion.subprocess.run", fake_run)

    fake_source = MagicMock(societa="ORTI")
    promotion._invoke_parser(
        parser_module="ingest.flussi.ingest_partite_aperte",
        raw_uri="gs://hotelops-raw/X_Y_ORTI_SNAPSHOT/2026/05/file.xlsx",
        source_def=fake_source,
        gcs_generation=1715000000123456,
    )

    assert download_calls == [
        ("gs://hotelops-raw/X_Y_ORTI_SNAPSHOT/2026/05/file.xlsx", 1715000000123456)
    ]
    assert len(captured) == 1
    assert captured[0][1:5] == ["-m", "ingest.flussi.ingest_partite_aperte", "--file", fake_local]
    assert cleanup_calls == [fake_local]


def test_invoke_parser_file_uri_unchanged(monkeypatch, tmp_path) -> None:
    """file:// path: no download, no cleanup, parser receives the path directly."""
    from unittest.mock import MagicMock
    from ingest import promotion

    captured = []

    def fake_run(cmd, **kw):
        captured.append(cmd)
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        return result

    monkeypatch.setattr("ingest.promotion.subprocess.run", fake_run)

    fake_source = MagicMock(societa="ORTI")
    promotion._invoke_parser(
        parser_module="ingest.flussi.ingest_x",
        raw_uri="file:///tmp/x.xlsx",
        source_def=fake_source,
        gcs_generation=None,
    )

    assert captured[0][1:5] == ["-m", "ingest.flussi.ingest_x", "--file", "/tmp/x.xlsx"]
```

- [ ] **Step 2: Run — must fail (`_invoke_parser` doesn't accept `gcs_generation`, doesn't handle `gs://`)**

```bash
pytest tests/test_promotion.py -v
```

- [ ] **Step 3: Modify `_invoke_parser`**

Open `ingest/promotion.py`. Update imports + function:

```python
from core.lineage.raw_storage import GCSBackend  # add at top with other lineage imports


def _invoke_parser(
    parser_module: str,
    raw_uri: str,
    source_def,
    gcs_generation: Optional[int] = None,
) -> dict:
    """Invoke the parser via subprocess.

    file:// → pass parsed path directly.
    gs://   → download to temp, pass temp path, cleanup on exit.
    """
    from urllib.parse import urlparse

    parsed = urlparse(raw_uri)
    backend = None
    cleanup_path: Optional[str] = None

    if parsed.scheme == "gs":
        bucket = parsed.netloc
        backend = GCSBackend(bucket=bucket)
        local_path = backend.download_to_temp(raw_uri, generation=gcs_generation)
        cleanup_path = local_path
    elif parsed.scheme in ("file", ""):
        local_path = parsed.path
    else:
        raise NotImplementedError(
            f"Unsupported raw_uri scheme {parsed.scheme!r}: {raw_uri}"
        )

    cmd = [sys.executable, "-m", parser_module, "--file", local_path]
    if source_def.societa in ("ORTI", "INTUR"):
        cmd += ["--societa", source_def.societa]

    log.info("Invoking parser: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(
                f"Parser {parser_module} failed (exit {proc.returncode}): "
                f"{proc.stderr.strip()[:500]}"
            )
        return {"rows_written": -1}
    finally:
        if backend is not None and cleanup_path is not None:
            try:
                backend.cleanup(cleanup_path)
            except Exception as e:
                log.warning("Cleanup of temp %s failed: %s", cleanup_path, e)
```

Then update the single call site in `promote_raw_object`:

```python
        try:
            parser_result = _invoke_parser(
                source_def.parser_module,
                raw.raw_uri,
                source_def,
                gcs_generation=getattr(raw, "gcs_generation", None),
            )
```

- [ ] **Step 4: Run tests — must pass**

```bash
pytest tests/test_promotion.py -v
```

- [ ] **Step 5: Lint + format + commit**

```bash
ruff check . && ruff format ingest/promotion.py tests/test_promotion.py
git add ingest/promotion.py tests/test_promotion.py
git commit -m "feat(promotion): _invoke_parser supports gs:// via download-to-temp (task 7)"
```

---

## Task 8: Pilot source flip in registry

**Files:**
- Modify: `core/source_registry.yaml`
- Test: `tests/test_source_registry_pilot.py` (new, smoke-style)

- [ ] **Step 1: Failing test**

Create `tests/test_source_registry_pilot.py`:

```python
"""Pilot source MPS_BANCA_ORTI_APPEND must be on backend=gcs."""

from core.lineage.source_resolver import load_registry

PILOT_SOURCE = "MPS_BANCA_ORTI_APPEND"


def test_pilot_mps_banca_orti_uses_gcs_backend() -> None:
    reg = load_registry()
    src = reg.get(PILOT_SOURCE)
    assert src is not None
    assert src.raw_storage.backend == "gcs"
    assert src.raw_storage.bucket == "hotelops-raw"
    # Sanity: pilot is APPEND lifecycle (the whole point of switching from
    # the original SNAPSHOT proposal — exercises content_hash dedup).
    assert src.lifecycle == "APPEND"


def test_other_sources_remain_drive() -> None:
    """Bulk flip is a separate PR; verify only pilot moved."""
    reg = load_registry()
    not_pilot_gcs = []
    for name, src in reg._sources.items():
        if name == PILOT_SOURCE:
            continue
        if src.raw_storage and src.raw_storage.backend == "gcs":
            not_pilot_gcs.append(name)
    assert not_pilot_gcs == [], (
        f"Only the pilot should be on gcs in this PR; found extra: {not_pilot_gcs}"
    )
```

(If `SourceRegistry` exposes sources via a different attribute than `_sources`, adapt the second test — e.g. iterate via a public method like `all_sources()` or `keys()`.)

- [ ] **Step 2: Run — must fail (pilot still on drive)**

```bash
pytest tests/test_source_registry_pilot.py -v
```

- [ ] **Step 3: Edit `core/source_registry.yaml`**

Locate `MPS_BANCA_ORTI_APPEND`. Change ONLY the `raw_storage` block:

```yaml
  MPS_BANCA_ORTI_APPEND:
    system: MPS
    dataset: BANCA
    dataset_label: "Movimenti homebanking MPS"
    societa: ORTI
    business_unit: null
    lifecycle: APPEND
    canonical_table: f_banche_movimenti
    parser_module: ingest.banca.ingest
    hash_basis: hash_riga
    loop_targets: [daily_reconciliation, cash_control, monthly_close]
    promotion_policy: AUTO
    detector_category: banca
    raw_storage:
      backend: gcs                          # was: drive
      bucket: hotelops-raw                   # NEW (only required for backend=gcs)
      path_template: "homebanking/ORTI/MPS"  # retained for Drive-side workspace
```

- [ ] **Step 4: Run tests — must pass**

```bash
pytest tests/test_source_registry_pilot.py tests/test_source_resolver.py -v
```

- [ ] **Step 5: Run full suite**

```bash
pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add core/source_registry.yaml tests/test_source_registry_pilot.py
git commit -m "feat(registry): pilot MPS_BANCA_ORTI_APPEND → backend=gcs (task 8)"
```

---

## Task 9: Doc updates

**Files:**
- Modify: `docs/DATAHUB_ONTOLOGY.md`
- Modify: `CLAUDE.md`
- Modify: `STATUS.md`

- [ ] **Step 1: Update `docs/DATAHUB_ONTOLOGY.md` §10**

Replace section 10 with:

```markdown
## 10) Stato di transizione (oggi 2026-05-05)

- Architettura target: GCS-first (decisa, in materializzazione)
- **Phase 4 landed**: `gs://hotelops-raw` operativo (Versioning ON +
  Autoclass→ARCHIVE), `core/lineage/raw_storage.py` con `LocalBackend` +
  `GCSBackend`, schema `f_raw_objects.gcs_generation` aggiunto, parser
  invocation supporta `gs://` via download-to-temp.
- **Pilot source attivo**: `MPS_BANCA_ORTI_APPEND` (`backend: gcs`,
  lifecycle APPEND con content_hash dedup — esercita il caso d'uso pieno
  di GCS+versioning).
- **Bulk flip pendente**: altre 12 sources restano `backend: drive` finché
  un PR dedicato le sposta in batch (separato da Phase 4 per limitare blast
  radius del pilot).
- **Backfill rows storiche**: NON eseguito — `f_raw_objects` esistenti
  restano `file://`. Backfill è opzionale e separato.
- Legacy datahub Drive: ancora workspace umano editabile; non sostituito.

I nuovi lavori che toccano lineage devono usare `intake_file` (che dispatcha
backend automaticamente via `source_def`). Non scrivere mai direttamente in
`f_raw_objects`.
```

- [ ] **Step 2: Update `CLAUDE.md` lineage section**

Find the `core/lineage/` description block. Add:

```markdown
- `core/lineage/raw_storage.py` -- Backend abstraction. `LocalBackend` (file:// passthrough) + `GCSBackend` (uploads to `gs://hotelops-raw/<source>/<YYYY>/<MM>/<filename>` con Object Versioning). Selezione via `source_def.raw_storage.backend`.
```

Find the table of fact tables. Update the `f_raw_objects` mention or add note:

```markdown
> `f_raw_objects` ora include nullable `gcs_generation INT64` (popolato solo per `raw_backend=gcs`).
```

Find Commands section. Optional: nota su provisioning script:

```bash
# GCS bucket provisioning (one-time, idempotent)
./scripts/provision_gcs_bucket.sh
```

- [ ] **Step 3: Update `STATUS.md`**

(Use the `session-context` skill convention: move from "In corso" to "Completato di recente" with today's date, add new "Decisioni aperte" entries if any.)

Key entries to add under "Completato di recente" (top):

```markdown
- 2026-05-05: **GCS Raw Staging Phase 4** — `gs://hotelops-raw` provisioned (Versioning ON + Autoclass→ARCHIVE). `core/lineage/raw_storage.py` (`LocalBackend` + `GCSBackend`). Schema migration `f_raw_objects.gcs_generation INT64`. Pilot `MPS_BANCA_ORTI_APPEND` su `backend: gcs` (APPEND lifecycle scelta over SNAPSHOT per esercitare content_hash dedup). `_invoke_parser` supporta `gs://` via download-to-temp. Phase 1+2 tests verdi (no regression). Smoke test su file MPS homebanking produzione: PASS, dedup re-upload short-circuit verificato.
```

Move the "GCS come Raw layer immutabile" entry from "Decisioni aperte" to the implementation note above. Add new "Decisioni aperte":

```markdown
- **Bulk flip altre 12 sources a backend=gcs** — pendente, scope di un PR separato. Trigger: stabilità del pilot su 1-2 settimane.
- **Backfill rows storiche `file://` → GCS** — opzionale. Costo: script ~30 min, valore: lineage uniforme. Decisione rimandata fino a quando un consumer ne ha bisogno.
```

- [ ] **Step 4: Lint + format docs (no Python lint applies)**

```bash
ruff check .
```

- [ ] **Step 5: Commit**

```bash
git add docs/DATAHUB_ONTOLOGY.md CLAUDE.md STATUS.md
git commit -m "docs(gcs): Phase 4 landed — GCS pilot live, doc-vs-impl drift closed (task 9)"
```

---

## Task 10: Smoke test (controller-only, NOT a subagent task)

This step touches production GCS + BQ. Controller executes manually after CI passes.

- [ ] **Step 1: Pick a real MPS homebanking file**

```bash
ls -lat ~/path/to/datahub/homebanking/ORTI/MPS/*.xlsx ~/path/to/datahub/homebanking/ORTI/MPS/*.csv 2>/dev/null | head -3
```

- [ ] **Step 2: Run intake**

```bash
hotelops intake /path/to/<mps_file>.xlsx \
  --source-name MPS_BANCA_ORTI_APPEND \
  --actor smoke_test_phase4
```

Expected output:

```
raw_object_id=<uuid>
content_hash=<md5>
source_name=MPS_BANCA_ORTI_APPEND
```

- [ ] **Step 3: Verify GCS object**

```bash
gsutil ls -l "gs://hotelops-raw/MPS_BANCA_ORTI_APPEND/2026/05/"
```

Expected: shows the uploaded file with non-zero size.

- [ ] **Step 4: Verify BQ row**

```bash
bq query --use_legacy_sql=false "
SELECT raw_object_id, raw_uri, raw_backend, gcs_generation, intake_actor
FROM hotelops.f_raw_objects
WHERE intake_actor='smoke_test_phase4'
ORDER BY intake_at DESC
LIMIT 1
"
```

Expected: `raw_uri` starts with `gs://hotelops-raw/`, `raw_backend='gcs'`, `gcs_generation` is non-null.

- [ ] **Step 5: Verify lineage event**

```bash
hotelops lineage <raw_object_id>
```

Expected: shows RAW_INGESTED event with `raw_backend=gcs` in payload.

- [ ] **Step 6: Dedup re-upload short-circuit (APPEND-pilot's distinctive value)**

```bash
hotelops intake /path/to/<same_mps_file>.xlsx \
  --source-name MPS_BANCA_ORTI_APPEND \
  --actor smoke_test_phase4_dedup
```

Expected:
- Returned `raw_object_id` is **the same** as Step 2 output
- `gsutil ls gs://hotelops-raw/MPS_BANCA_ORTI_APPEND/2026/05/` still shows
  exactly **1** object (no second upload)
- `bq query "SELECT COUNT(*) FROM hotelops.f_raw_objects WHERE intake_actor IN ('smoke_test_phase4','smoke_test_phase4_dedup')"` returns **1** (no second row)
- `bq query "SELECT COUNT(*) FROM hotelops.f_lineage_events WHERE raw_object_id = '<uuid>'"` should still be **1** RAW_INGESTED event (intake should skip emit on dedup hit; if it emits anyway, that's an open gap to flag)

- [ ] **Step 7 (optional): End-to-end via promote**

```bash
hotelops promote --raw-object-id <raw_object_id>
```

Expected: parser ran from temp download; status moves to PROMOTED; canonical write appended rows to `f_banche_movimenti`.

- [ ] **Step 8: Document smoke test result**

Append note to PR description with `raw_object_id` + `gs://` URI of the test object + dedup verification result. The object stays in GCS (immutable, not deleted).

---

## Task 11: PR + merge

- [ ] **Step 1: Push branch**

```bash
git push -u origin refactor/gcs-raw-staging
```

- [ ] **Step 2: Open PR against main**

Title: `Phase 4: GCS Raw Staging — pilot MPS_BANCA_ORTI_APPEND live`

Body:

```markdown
## Summary

- Provisions `gs://hotelops-raw` (Versioning ON + Autoclass→ARCHIVE)
- Adds `core/lineage/raw_storage.py` with `RawStorageBackend` ABC + `LocalBackend` (passthrough) + `GCSBackend` (upload + download)
- `intake_file` dispatches backend via `source_def.raw_storage.backend`
- `_invoke_parser` supports `gs://` via download-to-temp + cleanup
- Schema: `f_raw_objects` gains nullable `gcs_generation INT64`
- Pilot source: `MPS_BANCA_ORTI_APPEND` flipped to `backend: gcs` (APPEND chosen over SNAPSHOT to exercise content_hash dedup path)
- Other 12 sources unchanged (separate bulk-flip PR)
- Closes doc-vs-implementation drift on `DATAHUB_ONTOLOGY.md`

## Architecture invariants preserved

- I1 strict: all BQ writes still via `bq_write_validated(append)`
- Phase 1 state machine + naming grammar + hard gate untouched
- Phase 2 `cmd_drop --lineage` shadow flow untouched (transparently flips to GCS for pilot via source dispatch)
- Parser modules NOT modified

## Smoke test

- Real MPS homebanking file ingested → GCS object exists, BQ row references it with non-null generation
- Re-upload of the same file dedup-short-circuited (no second GCS object, no second f_raw_objects row) — APPEND-pilot's distinctive value verified
- `raw_object_id`: `<uuid from Task 10>`
- GCS URI: `<gs://... from Task 10>`

## Test plan

- [x] Phase 1 tests still green
- [x] Phase 2 (`test_drop_shadow.py`) still green
- [x] New tests: `test_raw_storage_local.py`, `test_raw_storage_gcs.py`, `test_intake_gcs.py`, `test_promotion.py` (additions), `test_source_registry_pilot.py`, `test_migration_add_gcs_generation.py`
- [x] Migration `2026_05_05_add_gcs_generation` applied to BQ production (idempotent, verified via INFORMATION_SCHEMA)
- [x] Smoke test on real production file passed
- [ ] Bulk flip of remaining 12 sources (separate PR after 1-2 weeks of pilot stability)
```

- [ ] **Step 3: Merge after review**

```bash
gh pr merge --squash --delete-branch
```

---

## Done criteria

- All 11 tasks above committed
- Full test suite green: `pytest -q`
- Lint clean: `ruff check .`
- Production smoke test (Task 10) succeeded
- PR merged to main
- `STATUS.md` reflects Phase 4 done
- `DATAHUB_ONTOLOGY.md` no longer lies about GCS
