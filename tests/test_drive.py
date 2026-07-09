import httplib2
from googleapiclient.errors import HttpError

from workspace.drive import create_shortcut, ensure_shared_with


class _Exec:
    def __init__(self, result, error=None):
        self._result = result
        self._error = error

    def execute(self):
        if self._error is not None:
            raise self._error
        return self._result


class FakeFilesService:
    def __init__(self):
        self.create_calls = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return _Exec({"id": "shortcut123"})


class FakePermissionsService:
    def __init__(self, error=None):
        self.create_calls = []
        self._error = error

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return _Exec({"id": "perm123"}, error=self._error)


class FakeDriveService:
    def __init__(self, permissions_error=None):
        self._files = FakeFilesService()
        self._permissions = FakePermissionsService(error=permissions_error)

    def files(self):
        return self._files

    def permissions(self):
        return self._permissions


def _http_error(status: int, content: bytes) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), content)


def test_create_shortcut_builds_shortcut_body_and_returns_id():
    service = FakeDriveService()

    shortcut_id = create_shortcut(service, "PARENT1", "contratto.pdf", "TARGET1")

    assert shortcut_id == "shortcut123"
    assert len(service._files.create_calls) == 1
    call = service._files.create_calls[0]
    assert call["body"] == {
        "name": "contratto.pdf",
        "mimeType": "application/vnd.google-apps.shortcut",
        "parents": ["PARENT1"],
        "shortcutDetails": {"targetId": "TARGET1"},
    }
    assert call["fields"] == "id"
    assert call["supportsAllDrives"] is True


# --- ensure_shared_with ---

def test_ensure_shared_with_grants_reader_no_notification(monkeypatch):
    service = FakeDriveService()
    seen_subjects = []

    def fake_writer(subject):
        seen_subjects.append(subject)
        return service

    monkeypatch.setattr("workspace.drive.get_drive_writer", fake_writer)

    ok = ensure_shared_with("owner@panoramagroup.it", "F1", "stefano@panoramagroup.it")

    assert ok is True
    assert seen_subjects == ["owner@panoramagroup.it"]
    assert len(service._permissions.create_calls) == 1
    call = service._permissions.create_calls[0]
    assert call["fileId"] == "F1"
    assert call["body"] == {
        "type": "user",
        "role": "reader",
        "emailAddress": "stefano@panoramagroup.it",
    }
    assert call["sendNotificationEmail"] is False
    assert call["supportsAllDrives"] is True


def test_ensure_shared_with_duplicate_is_success(monkeypatch):
    err = _http_error(
        400,
        b'{"error": {"message": "The user already has access to this file."}}',
    )
    service = FakeDriveService(permissions_error=err)
    monkeypatch.setattr("workspace.drive.get_drive_writer", lambda subject: service)

    ok = ensure_shared_with("owner@panoramagroup.it", "F1", "stefano@panoramagroup.it")

    assert ok is True


def test_ensure_shared_with_external_owner_returns_false(monkeypatch):
    err = _http_error(
        403,
        b'{"error": {"message": "The user does not have sufficient permissions."}}',
    )
    service = FakeDriveService(permissions_error=err)
    monkeypatch.setattr("workspace.drive.get_drive_writer", lambda subject: service)

    ok = ensure_shared_with("ext@gmail.com", "F1", "stefano@panoramagroup.it")

    assert ok is False
