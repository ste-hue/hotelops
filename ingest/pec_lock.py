"""Lock globale del giro PEC, su GCS.

Serve a una cosa sola: impedire che due giri lavorino le caselle insieme.
La deduplicazione a valle è legge-poi-scrivi su `msgid`, quindi due processi
sovrapposti producono righe doppie in `f_pec_messages` (osservato: due righe a
417 ms di distanza). Il lock è **globale, non per casella**: la stessa PEC
inviata a INTUR e a ORTI ha lo stesso `msgid`, quindi anche due giri su
caselle diverse possono duplicarla.

La presa è atomica: `if_generation_match=0` fa fallire la scrittura se
l'oggetto esiste già — leggi-poi-scrivi qui sarebbe lo stesso difetto che
stiamo chiudendo. Un lock più vecchio di TTL è di un processo morto (il task
timeout del job è 1h) e si sovrascrive, se no un crash bloccherebbe il job
per sempre.

**L'età del lock viene da `time_created`, lato server**, non da quello che
c'è scritto dentro: il payload è solo diagnostico e un payload corrotto o
con un timestamp sballato non deve poter far rubare il lock a un giro vivo.
Se `time_created` mancasse, il lock si considera occupato — mai orfano.

Limite noto e accettato: la sovrascrittura di un lock orfano non è atomica,
quindi due processi che scoprono lo stesso lock scaduto nello stesso istante
proseguono entrambi. Perché accada servono un crash *e* due giri partiti a
millisecondi di distanza: con uno scheduler notturno solo, non capita.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import os
import socket

log = logging.getLogger(__name__)

BUCKET = "hotelops-raw"
LOCK_PATH = "pec/_lock/pec_fetch.lock"
TTL = dt.timedelta(hours=2)


class LockBusy(Exception):
    """Un altro giro è in corso. NON è un guasto: chi arriva secondo esce 0."""

    def __init__(self, acquired_at: dt.datetime | None):
        self.acquired_at = acquired_at
        super().__init__(f"giro PEC già in corso da {acquired_at}")


def _blob(bucket: str, client):
    if client is None:
        from google.cloud import storage

        client = storage.Client()
    return client.bucket(bucket).blob(LOCK_PATH)


def _payload() -> str:
    return json.dumps(
        {
            "acquired_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "host": socket.gethostname(),
            "pid": os.getpid(),
        }
    )


def acquire(bucket: str = BUCKET, client=None):
    """Prende il lock e torna il blob da passare a `release`.

    Solleva `LockBusy` se un altro giro è vivo."""
    from google.api_core.exceptions import NotFound, PreconditionFailed

    blob = _blob(bucket, client)
    for _ in range(2):
        try:
            blob.upload_from_string(
                _payload(), content_type="application/json", if_generation_match=0
            )
            return blob
        except PreconditionFailed:
            pass
        try:
            blob.reload()  # metadati lato server: incorruttibili
        except NotFound:
            continue  # rilasciato mentre guardavamo: ritenta la presa atomica
        held = blob.time_created
        if held is None:
            # Senza l'ora del server non si può dire che sia orfano, e nel
            # dubbio il lock è di qualcun altro.
            log.warning("Lock PEC senza time_created: lo considero occupato")
            raise LockBusy(None)
        eta = dt.datetime.now(dt.timezone.utc) - held
        if eta < TTL:
            raise LockBusy(held)
        log.warning(
            "Lock PEC orfano (fermo da %s, oltre il TTL di %s): lo sovrascrivo",
            eta,
            TTL,
        )
        blob.upload_from_string(_payload(), content_type="application/json")
        return blob
    raise LockBusy(None)


def release(blob) -> None:
    """Cancella SOLO la generation che abbiamo scritto noi: se nel frattempo
    qualcuno ci ha rubato il lock scaduto e sta lavorando, il suo non si tocca.

    Il rilascio non può far fallire un giro riuscito: se GCS non collabora
    (403 senza storage.objects.delete, 5xx) si logga e basta — il lock resta
    al massimo fino al TTL, che è la stessa rete di sicurezza dei crash."""
    from google.api_core.exceptions import NotFound, PreconditionFailed

    try:
        blob.delete(if_generation_match=blob.generation)
    except NotFound:
        log.warning("Lock PEC già assente al rilascio")
    except PreconditionFailed:
        log.warning("Lock PEC non è più nostro (rubato dopo il TTL): non lo tocco")
    except Exception as exc:  # noqa: BLE001
        log.error("Lock PEC non rilasciato (%s): scadrà da solo al TTL", exc)


@contextlib.contextmanager
def pec_lock_held(bucket: str = BUCKET, client=None):
    blob = acquire(bucket, client)
    try:
        yield
    finally:
        release(blob)
