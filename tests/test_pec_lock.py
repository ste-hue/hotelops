"""Lock globale del giro PEC. Nessun test tocca GCS: client iniettato.

Il fake implementa la semantica vera delle precondizioni GCS
(`if_generation_match` in scrittura e in cancellazione) e i metadati lato
server (`time_created`, `generation`): i test vincolano il comportamento
invece di assumerlo.
"""

import datetime as dt
import json
import logging

import pytest
from google.api_core.exceptions import Forbidden, NotFound, PreconditionFailed

from ingest import pec_lock
from ingest.pec_lock import LOCK_PATH, LockBusy, acquire, pec_lock_held, release


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class _FakeObj:
    """Un oggetto su GCS: i dati più i metadati che ci mette il server."""

    def __init__(self, data, time_created, generation):
        self.data, self.time_created, self.generation = data, time_created, generation


class _FakeBlob:
    def __init__(self, client, key):
        self._client, self._key = client, key
        self.generation = None
        self.time_created = None

    def _obj(self):
        return self._client.store.get(self._key)

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        if if_generation_match == 0 and self._key in self._client.store:
            raise PreconditionFailed("oggetto già presente")
        self._client.ultima_gen += 1
        obj = _FakeObj(data, _now(), self._client.ultima_gen)
        self._client.store[self._key] = obj
        self.generation, self.time_created = obj.generation, obj.time_created

    def reload(self):
        obj = self._obj()
        if obj is None:
            raise NotFound(self._key)
        self.generation, self.time_created = obj.generation, obj.time_created

    def delete(self, if_generation_match=None):
        obj = self._obj()
        if obj is None:
            raise NotFound(self._key)
        if if_generation_match is not None and obj.generation != if_generation_match:
            raise PreconditionFailed("generation diversa: non è più il tuo lock")
        del self._client.store[self._key]


class _FakeBucket:
    def __init__(self, client):
        self._client = client

    def blob(self, key):
        return _FakeBlob(self._client, key)


class _FakeClient:
    def __init__(self):
        self.store: dict[str, _FakeObj] = {}
        self.ultima_gen = 0

    def bucket(self, name):
        return _FakeBucket(self)


def _lock_altrui(c, eta: dt.timedelta, payload: str | None = None, pid=999) -> None:
    """Un lock preso da un altro processo `eta` fa. L'età che conta è
    `time_created` (lato server), non quello che dice il payload."""
    c.ultima_gen += 1
    if payload is None:
        payload = json.dumps(
            {"acquired_at": (_now() - eta).isoformat(), "host": "altro", "pid": pid}
        )
    c.store[LOCK_PATH] = _FakeObj(payload, _now() - eta, c.ultima_gen)


def _payload(c) -> dict:
    return json.loads(c.store[LOCK_PATH].data)


def test_lock_libero_si_acquisisce() -> None:
    c = _FakeClient()
    acquire(client=c)
    p = _payload(c)
    assert set(p) >= {"acquired_at", "host", "pid"}
    assert isinstance(p["pid"], int)
    dt.datetime.fromisoformat(p["acquired_at"])  # ISO valida


def test_lock_occupato_e_fresco_solleva_lockbusy() -> None:
    """Un giro vivo non è un guasto: chi arriva secondo se ne va."""
    c = _FakeClient()
    _lock_altrui(c, dt.timedelta(minutes=3))

    with pytest.raises(LockBusy) as exc:
        acquire(client=c)

    assert exc.value.acquired_at is not None
    assert _payload(c)["pid"] == 999, "il lock altrui resta intatto"


def test_lock_quasi_a_ttl_e_ancora_vivo() -> None:
    """Il TTL è 2h e il task timeout del job è 1h: a 1h59 il giro può
    ancora essere vivo, non si ruba il lock."""
    c = _FakeClient()
    _lock_altrui(c, dt.timedelta(hours=1, minutes=59))
    with pytest.raises(LockBusy):
        acquire(client=c)


def test_lock_piu_vecchio_di_due_ore_e_orfano(caplog) -> None:
    """Senza TTL un processo morto bloccherebbe il job per sempre."""
    c = _FakeClient()
    _lock_altrui(c, dt.timedelta(hours=2, minutes=1))

    with caplog.at_level(logging.WARNING, logger=pec_lock.__name__):
        acquire(client=c)

    assert _payload(c)["pid"] != 999, "sovrascritto dal nostro"
    assert "orfano" in caplog.text.lower()


# --- l'età viene dal server, non dal payload --------------------------------


def test_eta_dal_server_non_dal_payload() -> None:
    """Il payload è solo diagnostico. Se dicesse 5 ore ma l'oggetto è stato
    creato ora, il lock è vivo: un `acquired_at` sbagliato non deve poter
    far rubare il lock a un giro in corso."""
    c = _FakeClient()
    bugiardo = json.dumps(
        {"acquired_at": (_now() - dt.timedelta(hours=5)).isoformat(), "pid": 999}
    )
    _lock_altrui(c, dt.timedelta(minutes=1), payload=bugiardo)

    with pytest.raises(LockBusy):
        acquire(client=c)


def test_payload_corrotto_ma_lock_fresco_resta_occupato() -> None:
    """JSON illeggibile e oggetto creato un minuto fa: occupato. Il parsing
    fallito non è una licenza per rubare il lock a un giro vivo."""
    c = _FakeClient()
    _lock_altrui(c, dt.timedelta(minutes=1), payload="{non-json")

    with pytest.raises(LockBusy):
        acquire(client=c)

    assert c.store[LOCK_PATH].data == "{non-json", "intatto"


def test_payload_corrotto_e_lock_vecchio_e_orfano() -> None:
    """Simmetrico: decide il TTL, non la leggibilità del payload — così un
    file corrotto non blocca il job per sempre."""
    c = _FakeClient()
    _lock_altrui(c, dt.timedelta(hours=3), payload="{non-json")
    acquire(client=c)
    assert _payload(c)["pid"] > 0


def test_time_created_assente_e_occupato() -> None:
    """Senza l'ora lato server non si può dire che sia orfano: nel dubbio
    il lock è di qualcun altro."""
    c = _FakeClient()
    _lock_altrui(c, dt.timedelta(hours=9))
    c.store[LOCK_PATH].time_created = None

    with pytest.raises(LockBusy):
        acquire(client=c)


def test_lock_sparito_tra_creazione_e_lettura_si_riprova() -> None:
    """Corsa reale: la creazione atomica fallisce, ma l'altro giro rilascia
    prima che leggiamo i metadati. Si ritenta invece di dichiararsi occupati."""
    c = _FakeClient()
    _lock_altrui(c, dt.timedelta(minutes=1))
    bucket = c.bucket("x")
    blob = bucket.blob(LOCK_PATH)
    reload_vero = blob.reload

    def sparisce_e_poi_legge():
        c.store.pop(LOCK_PATH, None)
        return reload_vero()

    blob.reload = sparisce_e_poi_legge
    bucket.blob = lambda key: blob
    c.bucket = lambda name: bucket

    acquire(client=c)
    assert LOCK_PATH in c.store


# --- rilascio ---------------------------------------------------------------


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


def test_release_non_cancella_il_lock_di_un_altro(caplog) -> None:
    """A resta appeso oltre il TTL, B glielo ruba legittimamente e sta
    lavorando: quando A finisce non deve cancellare il lock di B."""
    c = _FakeClient()
    blob_a = acquire(client=c)
    c.store[LOCK_PATH].time_created = _now() - dt.timedelta(hours=3)
    acquire(client=c)  # B ruba l'orfano
    gen_b = c.store[LOCK_PATH].generation

    with caplog.at_level(logging.WARNING, logger=pec_lock.__name__):
        release(blob_a)

    assert LOCK_PATH in c.store, "il lock di B è sopravvissuto"
    assert c.store[LOCK_PATH].generation == gen_b
    assert "non è più nostro" in caplog.text


def test_release_non_fa_fallire_il_giro_se_gcs_nega(caplog) -> None:
    """Senza storage.objects.delete il rilascio dà 403: un giro riuscito non
    deve diventare un allarme per colpa della pulizia."""
    c = _FakeClient()
    blob = acquire(client=c)
    blob.delete = lambda **k: (_ for _ in ()).throw(Forbidden("niente delete"))

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
