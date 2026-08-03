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
    assert read_watermark("vigna-raw", "VIGNA", client=_FakeClient()) == (0, None)


def test_roundtrip() -> None:
    c = _FakeClient()
    write_watermark("vigna-raw", "VIGNA", 4321, client=c)
    assert read_watermark("vigna-raw", "VIGNA", client=c).last_uid == 4321


def test_watermark_separato_per_entity() -> None:
    c = _FakeClient()
    write_watermark("hotelops-raw", "INTUR", 100, client=c)
    write_watermark("hotelops-raw", "ORTI", 200, client=c)
    assert read_watermark("hotelops-raw", "INTUR", client=c).last_uid == 100
    assert read_watermark("hotelops-raw", "ORTI", client=c).last_uid == 200


def test_payload_json_con_last_uid() -> None:
    c = _FakeClient()
    write_watermark("vigna-raw", "VIGNA", 7, client=c)
    assert json.loads(next(iter(c.store.values())))["last_uid"] == 7


def test_migrazione_da_path_legacy() -> None:
    """Il watermark vecchio (per-casella) diventa quello di INBOX."""
    c = _FakeClient()
    c.store["pec/_watermark/VIGNA.json"] = '{"last_uid": 112}'
    assert (
        read_watermark("vigna-raw", "VIGNA", folder="INBOX", client=c).last_uid == 112
    )
    assert "pec/_watermark/VIGNA/INBOX.json" in c.store


def test_migrazione_non_contamina_altre_cartelle() -> None:
    c = _FakeClient()
    c.store["pec/_watermark/VIGNA.json"] = '{"last_uid": 112}'
    assert read_watermark("vigna-raw", "VIGNA", folder="INBOX.Inviata", client=c) == (
        0,
        None,
    )


def test_cartelle_hanno_watermark_indipendenti() -> None:
    c = _FakeClient()
    write_watermark("vigna-raw", "VIGNA", 112, folder="INBOX", client=c)
    write_watermark("vigna-raw", "VIGNA", 47, folder="INBOX.Inviata", client=c)
    assert (
        read_watermark("vigna-raw", "VIGNA", folder="INBOX", client=c).last_uid == 112
    )
    assert (
        read_watermark("vigna-raw", "VIGNA", folder="INBOX.Inviata", client=c).last_uid
        == 47
    )


def test_punto_nel_nome_cartella_non_crea_sottocartelle() -> None:
    c = _FakeClient()
    write_watermark("vigna-raw", "VIGNA", 47, folder="INBOX.Inviata", client=c)
    assert "pec/_watermark/VIGNA/INBOX_Inviata.json" in c.store


def test_uidvalidity_roundtrip() -> None:
    c = _FakeClient()
    write_watermark("vigna-raw", "VIGNA", 47, client=c, uidvalidity=12345)
    assert read_watermark("vigna-raw", "VIGNA", client=c) == (47, 12345)
    assert json.loads(next(iter(c.store.values())))["uidvalidity"] == 12345


def test_watermark_legacy_senza_uidvalidity_resta_valido() -> None:
    """I sei watermark già in produzione non hanno il campo: devono
    continuare a leggersi, con uidvalidity None (= nessun azzeramento)."""
    c = _FakeClient()
    c.store["pec/_watermark/INTUR/INBOX.json"] = '{"last_uid": 2822}'
    assert read_watermark("hotelops-raw", "INTUR", folder="INBOX", client=c) == (
        2822,
        None,
    )


def test_migrazione_legacy_conserva_last_uid_senza_uidvalidity() -> None:
    c = _FakeClient()
    c.store["pec/_watermark/INTUR.json"] = '{"last_uid": 2822}'
    assert read_watermark("hotelops-raw", "INTUR", folder="INBOX", client=c) == (
        2822,
        None,
    )


def test_migrazione_non_sovrascrive_watermark_nuovo() -> None:
    """Se il path nuovo esiste già, la migrazione non deve toccarlo:
    altrimenti un watermark avanzato tornerebbe indietro."""
    c = _FakeClient()
    c.store["pec/_watermark/VIGNA/INBOX.json"] = '{"last_uid": 999}'
    c.store["pec/_watermark/VIGNA.json"] = '{"last_uid": 1}'
    assert (
        read_watermark("vigna-raw", "VIGNA", folder="INBOX", client=c).last_uid == 999
    )
