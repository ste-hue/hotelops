from workspace.drive import create_shortcut


class _Exec:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeFilesService:
    def __init__(self):
        self.create_calls = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return _Exec({"id": "shortcut123"})


class FakeDriveService:
    def __init__(self):
        self._files = FakeFilesService()

    def files(self):
        return self._files


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
