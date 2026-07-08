from workspace.miners.dossier_census import (
    append_ledger,
    dedupe_items,
    item_key,
    load_ledger,
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
    original = {"source": "drive", "file_id": "abc", "holders": ["a@x.it"], "name": "doc"}
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
