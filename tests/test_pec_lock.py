"""Lock globale del giro PEC. Nessun test tocca GCS: client iniettato."""

import datetime as dt
import json
import logging

import pytest
from google.api_core.exceptions import Forbidden, NotFound, PreconditionFailed

from ingest import pec_lock
from ingest.pec_lock import LOCK_PATH, LockBusy, acquire, pec_lock_held, release


class _FakeBlob:
    def __init__(self, store, key):
        self._store, self._key = store, key

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        if if_generation_match == 0 and self._key in self._store:
            raise PreconditionFailed("oggetto già presente")
        self._store[self._key] = data

    def download_as_text(self):
        if self._key not in self._store:
            raise NotFound(self._key)
        return self._store[self._key]

    def delete(self):
        if self._key not in self._store:
            raise NotFound(self._key)
        del self._store[self._key]


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


def _lock_di(eta: dt.timedelta, host="altro-host", pid=999) -> str:
    quando = dt.datetime.now(dt.timezone.utc) - eta
    return json.dumps(
        {"acquired_at": quando.isoformat(), "host": host, "pid": pid}
    )


def test_lock_libero_si_acquisisce() -> None:
    c = _FakeClient()
    acquire(client=c)
    payload = json.loads(c.store[LOCK_PATH])
    assert set(payload) >= {"acquired_at", "host", "pid"}
    assert isinstance(payload["pid"], int)
    dt.datetime.fromisoformat(payload["acquired_at"])  # ISO valida


def test_lock_occupato_e_fresco_solleva_lockbusy() -> None:
    """Un giro vivo non è un guasto: chi arriva secondo se ne va."""
    c = _FakeClient()
    c.store[LOCK_PATH] = _lock_di(dt.timedelta(minutes=3))

    with pytest.raises(LockBusy) as exc:
        acquire(client=c)

    assert exc.value.acquired_at is not None
    assert json.loads(c.store[LOCK_PATH])["pid"] == 999, "il lock altrui resta intatto"


def test_lock_quasi_a_ttl_e_ancora_vivo() -> None:
    """Il TTL è 2h e il task timeout del job è 1h: a 1h59 il giro può
    ancora essere vivo, non si ruba il lock."""
    c = _FakeClient()
    c.store[LOCK_PATH] = _lock_di(dt.timedelta(hours=1, minutes=59))
    with pytest.raises(LockBusy):
        acquire(client=c)


def test_lock_piu_vecchio_di_due_ore_e_orfano(caplog) -> None:
    """Senza TTL un processo morto bloccherebbe il job per sempre."""
    c = _FakeClient()
    c.store[LOCK_PATH] = _lock_di(dt.timedelta(hours=2, minutes=1))

    with caplog.at_level(logging.WARNING, logger=pec_lock.__name__):
        acquire(client=c)

    assert json.loads(c.store[LOCK_PATH])["pid"] != 999, "sovrascritto dal nostro"
    assert "orfano" in caplog.text.lower()


def test_lock_illeggibile_trattato_come_orfano(caplog) -> None:
    """Un payload corrotto non deve bloccare il job in eterno."""
    c = _FakeClient()
    c.store[LOCK_PATH] = "{non-json"

    with caplog.at_level(logging.WARNING, logger=pec_lock.__name__):
        acquire(client=c)

    assert json.loads(c.store[LOCK_PATH])["pid"] > 0
    assert "orfano" in caplog.text.lower()


def test_acquired_at_senza_timezone_non_esplode() -> None:
    """Un timestamp naive non deve far crashare il confronto col TTL."""
    c = _FakeClient()
    vecchio = dt.datetime.now() - dt.timedelta(hours=5)
    c.store[LOCK_PATH] = json.dumps(
        {"acquired_at": vecchio.isoformat(), "host": "x", "pid": 1}
    )
    acquire(client=c)  # lo tratta come orfano, non solleva TypeError
    assert json.loads(c.store[LOCK_PATH])["pid"] != 1


def test_lock_sparito_tra_creazione_e_lettura_si_riprova() -> None:
    """Corsa reale: la creazione atomica fallisce, ma l'altro giro rilascia
    prima che leggiamo il payload. Si ritenta invece di dichiararsi occupati."""
    c = _FakeClient()
    c.store[LOCK_PATH] = _lock_di(dt.timedelta(minutes=1))
    bucket = c.bucket("x")
    blob = bucket.blob(LOCK_PATH)
    originale = blob.download_as_text

    def sparisce_e_poi_legge():
        c.store.pop(LOCK_PATH, None)
        return originale()

    blob.download_as_text = sparisce_e_poi_legge
    bucket.blob = lambda key: blob
    c.bucket = lambda name: bucket

    acquire(client=c)
    assert LOCK_PATH in c.store


def test_release_toglie_il_lock() -> None:
    c = _FakeClient()
    blob = acquire(client=c)
    release(blob)
    assert LOCK_PATH not in c.store


def test_release_tollera_lock_gia_sparito() -> None:
    c = _FakeClient()
    blob = acquire(client=c)
    c.store.clear()
    release(blob)  # non deve sollevare


def test_release_non_fa_fallire_il_giro_se_gcs_nega(caplog) -> None:
    """Senza storage.objects.delete il rilascio dà 403: un giro riuscito non
    deve diventare un allarme per colpa della pulizia."""
    c = _FakeClient()
    blob = acquire(client=c)
    blob.delete = lambda: (_ for _ in ()).throw(Forbidden("niente delete"))

    with caplog.at_level(logging.ERROR, logger=pec_lock.__name__):
        release(blob)

    assert "TTL" in caplog.text


def test_context_manager_rilascia_anche_se_il_giro_solleva() -> None:
    c = _FakeClient()
    with pytest.raises(RuntimeError):
        with pec_lock_held(client=c):
            assert LOCK_PATH in c.store
            raise RuntimeError("il giro è esploso")
    assert LOCK_PATH not in c.store, "il lock si rilascia nel finally"


def test_context_manager_rilascia_a_fine_giro_riuscito() -> None:
    c = _FakeClient()
    with pec_lock_held(client=c):
        pass
    assert LOCK_PATH not in c.store


def test_due_giri_di_fila_non_si_bloccano() -> None:
    """Il rilascio deve rendere il lock riprendibile subito."""
    c = _FakeClient()
    with pec_lock_held(client=c):
        pass
    with pec_lock_held(client=c):
        assert LOCK_PATH in c.store


def test_path_del_lock_sotto_pec() -> None:
    assert LOCK_PATH == "pec/_lock/pec_fetch.lock"
