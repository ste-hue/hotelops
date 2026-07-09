import base64
import io
import zipfile

import pytest

from workspace.miners.dossier_official import (
    _extract_attachments,
    expand_archives,
    order_summary,
)


def test_order_summary_costs():
    orders, total = order_summary(["visura", "soci"])
    assert [o["order_id"] for o in orders] == ["visura", "soci"]
    assert total == pytest.approx(5.90 + 2.30)


def test_order_summary_rejects_unknown():
    with pytest.raises(KeyError):
        order_summary(["visura", "ubo"])


# --- _extract_attachments ---

def test_extract_attachments_single_flat_dict():
    content = b"%PDF-1.4 fake"
    raw = {"file": base64.b64encode(content).decode(), "nome": "bilancio.pdf"}
    out = _extract_attachments(raw, fallback_name="bilancio_c1")
    assert out == [("bilancio.pdf", content)]


def test_extract_attachments_dict_with_allegati_list():
    c1, c2 = b"content-one", b"content-two"
    raw = {
        "allegati": [
            {"file": base64.b64encode(c1).decode(), "filename": "a.pdf"},
            {"file": base64.b64encode(c2).decode(), "nome": "b.pdf"},
        ]
    }
    out = _extract_attachments(raw, fallback_name="fallback")
    assert out == [("a.pdf", c1), ("b.pdf", c2)]


def test_extract_attachments_bare_list():
    c1 = b"only-content"
    raw = [{"content": base64.b64encode(c1).decode(), "name": "x.pdf"}]
    out = _extract_attachments(raw, fallback_name="fallback")
    assert out == [("x.pdf", c1)]


# --- expand_archives ---

def _make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_expand_archives_expands_zip_into_inner_files():
    pdf_bytes = b"%PDF-1.4 fake"
    xbrl_bytes = b"<xbrl/>"
    zip_bytes = _make_zip({"bilancio.pdf": pdf_bytes, "bilancio.xbrl": xbrl_bytes})

    out = expand_archives([("archive.zip", zip_bytes)])

    assert len(out) == 2
    by_name = {name: (data, mime) for name, data, mime in out}
    assert by_name["bilancio.pdf"] == (pdf_bytes, "application/pdf")
    xbrl_data, xbrl_mime = by_name["bilancio.xbrl"]
    assert xbrl_data == xbrl_bytes
    assert xbrl_mime in ("application/octet-stream", "text/xml", "application/xml")


def test_expand_archives_passthrough_non_zip():
    pdf_bytes = b"%PDF-1.4 fake"
    out = expand_archives([("bilancio.pdf", pdf_bytes)])
    assert out == [("bilancio.pdf", pdf_bytes, "application/pdf")]
