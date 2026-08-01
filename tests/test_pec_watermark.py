import json

from ingest.pec_watermark import read_watermark, write_watermark


class _FakeBlob:
    def __init__(self, store, key):
        self._store, self._key = store, key

    def exists(self):
        return self._key in self._store

    def download_as_text(self):
        return self._store[self._key]

    def upload_from_string(self, data, content_type=None):
        self._store[self._key] = data


class _FakeBucket:
    def __init__(self, store):
        self._store = store

    def blob(self, key):
        return _FakeBlob(self._store, key)


class _FakeClient:
    def __init__(self):
        self.store = {}

    def bucket(self, name):
        return _FakeBucket(self.store)


def test_watermark_assente_vale_zero() -> None:
    assert read_watermark("vigna-raw", "VIGNA", client=_FakeClient()) == 0


def test_roundtrip() -> None:
    c = _FakeClient()
    write_watermark("vigna-raw", "VIGNA", 4321, client=c)
    assert read_watermark("vigna-raw", "VIGNA", client=c) == 4321


def test_watermark_separato_per_entity() -> None:
    c = _FakeClient()
    write_watermark("hotelops-raw", "INTUR", 100, client=c)
    write_watermark("hotelops-raw", "ORTI", 200, client=c)
    assert read_watermark("hotelops-raw", "INTUR", client=c) == 100
    assert read_watermark("hotelops-raw", "ORTI", client=c) == 200


def test_payload_json_con_last_uid() -> None:
    c = _FakeClient()
    write_watermark("vigna-raw", "VIGNA", 7, client=c)
    assert json.loads(next(iter(c.store.values())))["last_uid"] == 7
