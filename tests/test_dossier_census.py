from pathlib import Path

from workspace.dossier_config import COMPANIES
from workspace.miners.dossier_census import (
    append_ledger,
    dedupe_items,
    drive_query,
    gmail_query,
    item_key,
    load_ledger,
    run_census,
)


def test_item_key_drive_vs_gmail():
    assert item_key({"source": "drive", "file_id": "abc"}) == "drive:abc"
    assert item_key({"source": "gmail", "attachment_sha256": "ff00"}) == "hash:ff00"


def test_dedupe_merges_holders():
    items = [
        {"source": "drive", "file_id": "abc", "holders": ["a@x.it"], "name": "doc"},
        {"source": "drive", "file_id": "abc", "holders": ["b@x.it"], "name": "doc"},
        {"source": "gmail", "attachment_sha256": "ff00", "holders": ["c@x.it"]},
    ]
    out = dedupe_items(items)
    assert len(out) == 2
    assert out[0]["holders"] == ["a@x.it", "b@x.it"]


def test_dedupe_does_not_mutate_inputs():
    original = {
        "source": "drive",
        "file_id": "abc",
        "holders": ["a@x.it"],
        "name": "doc",
    }
    dup = {"source": "drive", "file_id": "abc", "holders": ["b@x.it"], "name": "doc"}
    dedupe_items([original, dup])
    assert original["holders"] == ["a@x.it"]
    assert "key" not in original


def test_ledger_roundtrip(tmp_path):
    p = tmp_path / "sub" / "ledger.jsonl"
    assert load_ledger(p) == set()
    append_ledger(p, ["drive:abc", "hash:ff00"])
    append_ledger(p, ["drive:xyz"])
    assert load_ledger(p) == {"drive:abc", "hash:ff00", "drive:xyz"}


def test_drive_query_escapes_and_wraps():
    q = drive_query('"ORTI SRL"')
    assert q == "fullText contains '\"ORTI SRL\"' and trashed = false"


def test_gmail_query_joins_terms():
    assert gmail_query(["INTUR OR 00553430653"]) == "(INTUR OR 00553430653)"
    assert gmail_query(["a", "b"]) == "(a) OR (b)"


def test_run_census_with_injected_collectors(tmp_path):
    users = [
        {"email": "a@p.it", "suspended": False},
        {"email": "am@p.it", "suspended": True},
    ]

    def fake_drive(email, phrases, max_files=500):
        return [
            {
                "source": "drive",
                "file_id": "f1",
                "name": "doc.pdf",
                "mime_type": "application/pdf",
                "size": 1,
                "owner": email,
                "holders": [email],
                "link": "",
                "modified": "",
                "category": "01_Societario",
                "confidence": 0.9,
            }
        ]

    def fake_gmail(email, terms, max_threads=200):
        return []

    res = run_census(
        COMPANIES["INTUR"],
        users,
        tmp_path,
        drive_collector=fake_drive,
        gmail_collector=fake_gmail,
        folder_collector=lambda folder_id, subject: [],
    )
    assert Path(res["census_path"]).exists()
    assert len(res["items"]) == 1
    assert res["inaccessible"] == ["am@p.it"]
    assert res["by_category"]["01_Societario"] == 1
