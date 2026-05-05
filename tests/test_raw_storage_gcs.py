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
    assert (
        result.raw_uri
        == "gs://hotelops-raw/ESOLVER_PARTITE_ORTI_SNAPSHOT/2026/05/x.xlsx"
    )
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
