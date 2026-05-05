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
