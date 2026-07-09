import hashlib
import json

from workspace.dossier_config import COMPANIES, WRITE_AS
from workspace.miners.dossier_apply import apply_census, plan_apply
from workspace.miners.dossier_census import load_ledger


def test_plan_apply_filters_ledger_and_applies_threshold():
    items = [
        {"key": "drive:a", "category": "01_Societario", "confidence": 0.9},
        {"key": "drive:b", "category": "02_Fiscale", "confidence": 0.3},
        {"key": "drive:c", "category": "03_Bilanci", "confidence": 0.8},
    ]
    plan = plan_apply(items, ledger_keys={"drive:c"}, threshold=0.6)
    assert [p["key"] for p in plan] == ["drive:a", "drive:b"]
    assert plan[0]["target_category"] == "01_Societario"
    assert plan[1]["target_category"] == "_DaRivedere"


# --- apply_census: scorciatoie Drive vs upload Gmail ---

class _Exec:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeFiles:
    def __init__(self):
        self.created = []
        self.get_media_calls = []
        self.export_calls = []
        self._next_id = 0

    def list(self, **kwargs):
        return _Exec({"files": []})

    def create(self, **kwargs):
        self._next_id += 1
        new_id = f"new{self._next_id}"
        self.created.append({**kwargs, "id": new_id})
        return _Exec({"id": new_id})

    def get_media(self, **kwargs):
        self.get_media_calls.append(kwargs)
        return _Exec(b"drive-bytes")

    def export(self, **kwargs):
        self.export_calls.append(kwargs)
        return _Exec(b"exported-bytes")


class FakeDriveService:
    def __init__(self):
        self.files_ = FakeFiles()

    def files(self):
        return self.files_


class FakeAttachment:
    def __init__(self, data):
        self.data = data


def _folder_id(fake_writer, category):
    for c in fake_writer.files_.created:
        if (
            c["body"]["name"] == category
            and c["body"].get("mimeType") == "application/vnd.google-apps.folder"
        ):
            return c["id"]
    raise AssertionError(f"folder {category} not created")


def _write_census(tmp_path, items):
    p = tmp_path / "census.jsonl"
    p.write_text("\n".join(json.dumps(it) for it in items) + "\n")
    return p


def test_apply_drive_item_creates_shortcut(monkeypatch, tmp_path):
    company = COMPANIES["INTUR"]
    fake_writer = FakeDriveService()
    monkeypatch.setattr(
        "workspace.miners.dossier_apply.get_drive_writer", lambda subject: fake_writer
    )
    monkeypatch.setattr("workspace.miners.dossier_apply.DOSSIER_STATE_DIR", tmp_path)
    monkeypatch.setattr(
        "workspace.miners.dossier_apply.ensure_shared_with", lambda *a: True
    )

    items = [{
        "key": "drive:F1",
        "source": "drive",
        "file_id": "F1",
        "name": "contratto.pdf",
        "mime_type": "application/pdf",
        "category": "01_Societario",
        "confidence": 0.9,
        "holders": ["a@panoramagroup.it"],
    }]
    census_path = _write_census(tmp_path, items)

    result = apply_census(company, census_path)

    assert result["applied"] == 1
    assert result["failed"] == []

    folder_id = _folder_id(fake_writer, "01_Societario")
    shortcut_calls = [
        c for c in fake_writer.files_.created
        if c["body"].get("mimeType") == "application/vnd.google-apps.shortcut"
    ]
    assert len(shortcut_calls) == 1
    call = shortcut_calls[0]
    assert call["body"] == {
        "name": "contratto.pdf",
        "mimeType": "application/vnd.google-apps.shortcut",
        "parents": [folder_id],
        "shortcutDetails": {"targetId": "F1"},
    }
    assert fake_writer.files_.get_media_calls == []
    assert fake_writer.files_.export_calls == []


def test_apply_drive_google_doc_shortcut_no_pdf_suffix(monkeypatch, tmp_path):
    company = COMPANIES["INTUR"]
    fake_writer = FakeDriveService()
    monkeypatch.setattr(
        "workspace.miners.dossier_apply.get_drive_writer", lambda subject: fake_writer
    )
    monkeypatch.setattr("workspace.miners.dossier_apply.DOSSIER_STATE_DIR", tmp_path)
    monkeypatch.setattr(
        "workspace.miners.dossier_apply.ensure_shared_with", lambda *a: True
    )

    items = [{
        "key": "drive:F2",
        "source": "drive",
        "file_id": "F2",
        "name": "Verbale Assemblea",
        "mime_type": "application/vnd.google-apps.document",
        "category": "01_Societario",
        "confidence": 0.9,
        "holders": ["a@panoramagroup.it"],
    }]
    census_path = _write_census(tmp_path, items)

    result = apply_census(company, census_path)

    assert result["applied"] == 1
    shortcut_calls = [
        c for c in fake_writer.files_.created
        if c["body"].get("mimeType") == "application/vnd.google-apps.shortcut"
    ]
    assert len(shortcut_calls) == 1
    assert shortcut_calls[0]["body"]["name"] == "Verbale Assemblea"
    assert fake_writer.files_.export_calls == []
    assert fake_writer.files_.get_media_calls == []


def test_apply_gmail_item_still_uploads_bytes(monkeypatch, tmp_path):
    company = COMPANIES["INTUR"]
    fake_writer = FakeDriveService()
    monkeypatch.setattr(
        "workspace.miners.dossier_apply.get_drive_writer", lambda subject: fake_writer
    )
    monkeypatch.setattr("workspace.miners.dossier_apply.DOSSIER_STATE_DIR", tmp_path)
    monkeypatch.setattr(
        "workspace.miners.dossier_apply.ensure_shared_with", lambda *a: True
    )

    content = b"hello world"
    sha = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(
        "workspace.miners.dossier_apply.get_gmail_service", lambda subject: object()
    )
    monkeypatch.setattr(
        "workspace.miners.dossier_apply.get_thread", lambda svc, thread_id: ["msg1"]
    )
    monkeypatch.setattr(
        "workspace.miners.dossier_apply.list_attachments",
        lambda svc, msg: [FakeAttachment(content)],
    )

    items = [{
        "key": f"hash:{sha}",
        "source": "gmail",
        "thread_id": "T1",
        "attachment_sha256": sha,
        "name": "allegato.pdf",
        "mime_type": "application/pdf",
        "category": "02_Fiscale",
        "confidence": 0.9,
        "holders": ["a@panoramagroup.it"],
    }]
    census_path = _write_census(tmp_path, items)

    result = apply_census(company, census_path)

    assert result["applied"] == 1
    folder_id = _folder_id(fake_writer, "02_Fiscale")
    upload_calls = [
        c for c in fake_writer.files_.created
        if c["body"].get("mimeType") != "application/vnd.google-apps.folder"
        and c["body"].get("mimeType") != "application/vnd.google-apps.shortcut"
    ]
    assert len(upload_calls) == 1
    assert upload_calls[0]["body"] == {"name": "allegato.pdf", "parents": [folder_id]}
    assert upload_calls[0]["media_body"] is not None


def test_apply_shortcut_appends_ledger_per_item(monkeypatch, tmp_path):
    company = COMPANIES["INTUR"]
    fake_writer = FakeDriveService()
    monkeypatch.setattr(
        "workspace.miners.dossier_apply.get_drive_writer", lambda subject: fake_writer
    )
    monkeypatch.setattr("workspace.miners.dossier_apply.DOSSIER_STATE_DIR", tmp_path)
    monkeypatch.setattr(
        "workspace.miners.dossier_apply.ensure_shared_with", lambda *a: True
    )

    items = [{
        "key": "drive:F1",
        "source": "drive",
        "file_id": "F1",
        "name": "contratto.pdf",
        "mime_type": "application/pdf",
        "category": "01_Societario",
        "confidence": 0.9,
        "holders": ["a@panoramagroup.it"],
    }]
    census_path = _write_census(tmp_path, items)

    result1 = apply_census(company, census_path)
    assert result1["applied"] == 1

    ledger_path = tmp_path / f"applied_{company.company_id}.jsonl"
    assert load_ledger(ledger_path) == {"drive:F1"}

    result2 = apply_census(company, census_path)
    assert result2["applied"] == 0
    assert result2["skipped"] == 1


def test_apply_drive_item_self_shares_then_shortcut(monkeypatch, tmp_path):
    company = COMPANIES["INTUR"]
    fake_writer = FakeDriveService()
    monkeypatch.setattr(
        "workspace.miners.dossier_apply.get_drive_writer", lambda subject: fake_writer
    )
    monkeypatch.setattr("workspace.miners.dossier_apply.DOSSIER_STATE_DIR", tmp_path)

    share_calls = []

    def fake_share(owner_or_holder, file_id, grantee):
        share_calls.append((owner_or_holder, file_id, grantee))
        return True

    monkeypatch.setattr(
        "workspace.miners.dossier_apply.ensure_shared_with", fake_share
    )

    items = [{
        "key": "drive:F1",
        "source": "drive",
        "file_id": "F1",
        "name": "contratto.pdf",
        "mime_type": "application/pdf",
        "category": "01_Societario",
        "confidence": 0.9,
        "owner": "b@panoramagroup.it",
        "holders": ["a@panoramagroup.it"],
    }]
    census_path = _write_census(tmp_path, items)

    result = apply_census(company, census_path)

    assert result["applied"] == 1
    assert share_calls == [("b@panoramagroup.it", "F1", WRITE_AS)]
    shortcut_calls = [
        c for c in fake_writer.files_.created
        if c["body"].get("mimeType") == "application/vnd.google-apps.shortcut"
    ]
    assert len(shortcut_calls) == 1
    assert result["not_shared"] == []


def test_apply_drive_external_owner_still_creates_shortcut(monkeypatch, tmp_path):
    company = COMPANIES["INTUR"]
    fake_writer = FakeDriveService()
    monkeypatch.setattr(
        "workspace.miners.dossier_apply.get_drive_writer", lambda subject: fake_writer
    )
    monkeypatch.setattr("workspace.miners.dossier_apply.DOSSIER_STATE_DIR", tmp_path)

    share_calls = []

    def failing_share(owner_or_holder, file_id, grantee):
        share_calls.append((owner_or_holder, file_id, grantee))
        return False

    monkeypatch.setattr(
        "workspace.miners.dossier_apply.ensure_shared_with", failing_share
    )

    items = [
        {
            # owner e holders tutti esterni al dominio: grant saltato del tutto
            "key": "drive:F1",
            "source": "drive",
            "file_id": "F1",
            "name": "esterno.pdf",
            "mime_type": "application/pdf",
            "category": "01_Societario",
            "confidence": 0.9,
            "owner": "ext@gmail.com",
            "holders": ["ext@gmail.com"],
        },
        {
            # owner interno ma grant fallito: shortcut comunque, key in not_shared
            "key": "drive:F2",
            "source": "drive",
            "file_id": "F2",
            "name": "interno.pdf",
            "mime_type": "application/pdf",
            "category": "01_Societario",
            "confidence": 0.9,
            "owner": "a@panoramagroup.it",
            "holders": ["a@panoramagroup.it"],
        },
    ]
    census_path = _write_census(tmp_path, items)

    result = apply_census(company, census_path)

    assert result["applied"] == 2
    assert result["failed"] == []
    # per F1 nessun utente interno impersonabile: ensure_shared_with mai chiamato
    assert share_calls == [("a@panoramagroup.it", "F2", WRITE_AS)]
    shortcut_calls = [
        c for c in fake_writer.files_.created
        if c["body"].get("mimeType") == "application/vnd.google-apps.shortcut"
    ]
    assert len(shortcut_calls) == 2
    assert result["not_shared"] == ["drive:F1", "drive:F2"]
