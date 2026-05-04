"""Audit trail per hotelops drop."""

from pathlib import Path

from ingest.classify import AUDIT_DROP_FILE, append_drop_audit, file_md5_hex


def test_append_drop_audit_creates_jsonl(tmp_path: Path) -> None:
    dh = tmp_path / "datahub"
    append_drop_audit(dh, {"file": "/tmp/x.xls", "status": "OK", "md5": "abc"})
    logf = dh / "ingresso" / "_audit" / AUDIT_DROP_FILE
    assert logf.is_file()
    line = logf.read_text(encoding="utf-8").strip()
    assert '"status": "OK"' in line
    assert '"md5": "abc"' in line
    assert '"ts":' in line


def test_file_md5_hex(tmp_path: Path) -> None:
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    assert file_md5_hex(p) == "5d41402abc4b2a76b9719d911017c592"
