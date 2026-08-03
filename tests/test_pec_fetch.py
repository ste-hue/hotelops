import contextlib
import datetime as dt
import logging
import os
import signal
import sys
from dataclasses import dataclass

import pytest

from ingest import pec_fetch
from ingest.pec_fetch import Deps, FetchResult, fetch_mailbox
from ingest.pec_imap import Block
from ingest.pec_lock import LockBusy
from ingest.pec_watermark import Watermark

UV = 1000  # UIDVALIDITY finta, stabile in quasi tutti i test


@pytest.fixture
def lock_libero(monkeypatch):
    """main() prende il lock globale su GCS: qui lo si finge libero.
    La lista torna la sequenza acquisito/rilasciato, per i test che la guardano."""
    eventi: list[str] = []

    @contextlib.contextmanager
    def finto(*a, **k):
        eventi.append("acquisito")
        try:
            yield
        finally:
            eventi.append("rilasciato")

    monkeypatch.setattr(pec_fetch, "pec_lock_held", finto)
    return eventi


@dataclass
class _IntakeResult:
    raw_object_id: str
    content_hash: str
    deduped: bool


def _promotion(status="PROMOTED", reason=None):
    return type("P", (), {"status": status, "reason": reason, "noop": False})()


def _deps(messages, watermarks=None, chunk_size=50, promotion=None):
    """`messages` è o una lista (trattata come sola INBOX) o un dict
    {folder: [(uid, bytes), ...]} per test multi-cartella. Le cartelle non
    presenti nel dict tornano vuote (comportamento della vera Inviata quando
    un test non se ne occupa)."""
    messages_by_folder = messages if isinstance(messages, dict) else {"INBOX": messages}
    wm = {
        (entity, "INBOX"): Watermark(uid, UV) for entity, uid in (watermarks or {}).items()
    }
    seen = set()
    calls = {"intake": [], "promote": []}

    def fake_fetch(
        cfg, since_uid, folder="INBOX", since_date=None, conn_factory=None,
        uidvalidity=None, chunk_size=chunk_size,
    ):
        msgs = [(u, b) for u, b in messages_by_folder.get(folder, []) if u > since_uid]
        for start in range(0, len(msgs), chunk_size):
            yield Block(UV, since_uid, msgs[start : start + chunk_size])

    def fake_intake(path, source_name, actor):
        h = str(hash(path.read_bytes()))
        deduped = h in seen
        seen.add(h)
        calls["intake"].append((source_name, h, deduped))
        return _IntakeResult(f"ro-{h}", h, deduped)

    def fake_promote(raw_object_id, actor):
        calls["promote"].append(raw_object_id)
        return promotion() if promotion else _promotion()

    return Deps(
        fetch_since=fake_fetch,
        read_watermark=lambda b, e, folder="INBOX": wm.get((e, folder), Watermark(0)),
        write_watermark=lambda b, e, u, folder="INBOX", uidvalidity=None: wm.__setitem__(
            (e, folder), Watermark(u, uidvalidity)
        ),
        intake_file=fake_intake,
        promote_raw_object=fake_promote,
        get_password=lambda env: "s3cret",
    ), wm, calls


def test_ingerisce_le_buste_nuove() -> None:
    deps, _, calls = _deps([(11, b"una"), (12, b"due")])
    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert (res.fetched, res.ingested, res.status) == (2, 2, "OK")
    assert len(calls["intake"]) == 2


def test_watermark_avanza_al_uid_massimo() -> None:
    deps, wm, _ = _deps([(11, b"una"), (12, b"due")])
    fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert wm[("VIGNA", "INBOX")] == (12, UV)


def test_secondo_giro_zero_duplicati() -> None:
    """Il test che conta: stessa busta due volte, una riga sola."""
    deps, _, calls = _deps([(11, b"una"), (12, b"due")])
    fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    res2 = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert res2.fetched == 0
    assert len(calls["intake"]) == 2


def test_hash_protegge_se_il_watermark_si_perde() -> None:
    deps, wm, _ = _deps([(11, b"una"), (12, b"due")])
    fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    wm.clear()
    res2 = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert res2.fetched == 2, "riscarica, giustamente"
    assert (res2.deduped, res2.ingested) == (2, 0), "ma non duplica"


def test_casella_vuota_non_e_errore() -> None:
    deps, _, _ = _deps([])
    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert (res.status, res.fetched) == ("OK", 0)


def test_casella_irraggiungibile_torna_failed() -> None:
    deps, _, _ = _deps([])
    deps.fetch_since = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("giù"))
    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert res.status == "FAILED"


def test_watermark_fermo_su_fallimento() -> None:
    deps, wm, _ = _deps([], watermarks={"VIGNA": 50})
    deps.fetch_since = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("giù"))
    fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert wm[("VIGNA", "INBOX")].last_uid == 50


def test_sorgente_sconosciuta_solleva() -> None:
    deps, _, _ = _deps([])
    with pytest.raises(ValueError, match="non nel registry"):
        fetch_mailbox("PEC_MAILBOX_PIPPO_APPEND", deps=deps)


def test_intake_fallisce_a_meta_giro_produce_failed_e_non_avanza_watermark() -> None:
    """Errore transiente GCS/BQ su intake_file: non deve crashare, watermark fermo."""
    messages = [(11, b"una"), (12, b"due"), (13, b"tre")]
    wm: dict = {}
    calls = {"intake": [], "promote": []}

    def fake_fetch(cfg, since_uid, folder="INBOX", since_date=None, conn_factory=None,
                   uidvalidity=None, chunk_size=50):
        if folder != "INBOX":
            return
        yield Block(UV, since_uid, [(u, b) for u, b in messages if u > since_uid])

    def fake_intake(path, source_name, actor):
        calls["intake"].append(path.name)
        if len(calls["intake"]) == 2:
            raise ConnectionError("GCS giù")
        return _IntakeResult(f"ro-{path.name}", path.name, False)

    def fake_promote(raw_object_id, actor):
        calls["promote"].append(raw_object_id)
        return _promotion()

    deps = Deps(
        fetch_since=fake_fetch,
        read_watermark=lambda b, e, folder="INBOX": wm.get(e, Watermark(0)),
        write_watermark=lambda b, e, u, folder="INBOX", uidvalidity=None: wm.__setitem__(
            e, Watermark(u, uidvalidity)
        ),
        intake_file=fake_intake,
        promote_raw_object=fake_promote,
        get_password=lambda env: "s3cret",
    )

    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)

    assert res.status == "FAILED"
    assert "VIGNA" not in wm
    assert len(calls["intake"]) == 2, "si è fermato al secondo, non ha proseguito"


def test_cartella_inviata_irraggiungibile_non_blocca_inbox() -> None:
    """La cartella INBOX.Inviata registry di VIGNA è irraggiungibile:
    INBOX va comunque ingerita e il suo watermark avanza, quello di
    Inviata resta fermo, e lo stato riflette il fallimento parziale."""
    deps, wm, calls = _deps({"INBOX": [(11, b"una"), (12, b"due")]})
    real_fetch = deps.fetch_since

    def fake_fetch(cfg, since_uid, folder="INBOX", since_date=None, conn_factory=None,
                   uidvalidity=None, chunk_size=50):
        if folder == "INBOX.Inviata":
            raise ConnectionError("Inviata giù")
        return real_fetch(cfg, since_uid, folder=folder, since_date=since_date)

    deps.fetch_since = fake_fetch

    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)

    assert res.per_folder["INBOX"] == 2
    assert len(calls["intake"]) == 2
    assert wm[("VIGNA", "INBOX")].last_uid == 12
    assert ("VIGNA", "INBOX.Inviata") not in wm
    assert res.status == "FAILED"


def test_cartella_inbox_irraggiungibile_non_blocca_inviata() -> None:
    """Speculare al test sopra: se a fallire è la PRIMA cartella elencata
    nel registry (INBOX), la seconda (INBOX.Inviata) deve essere comunque
    tentata. Un try/except che avvolgesse l'intero ciclo invece della
    singola iterazione farebbe fallire anche questo assert."""
    deps, wm, calls = _deps({"INBOX.Inviata": [(21, b"ventuno"), (22, b"ventidue")]})
    real_fetch = deps.fetch_since

    def fake_fetch(cfg, since_uid, folder="INBOX", since_date=None, conn_factory=None,
                   uidvalidity=None, chunk_size=50):
        if folder == "INBOX":
            raise ConnectionError("INBOX giù")
        return real_fetch(cfg, since_uid, folder=folder, since_date=since_date)

    deps.fetch_since = fake_fetch

    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)

    assert res.per_folder["INBOX.Inviata"] == 2
    assert len(calls["intake"]) == 2
    assert wm[("VIGNA", "INBOX.Inviata")].last_uid == 22
    assert ("VIGNA", "INBOX") not in wm
    assert res.status == "FAILED"


# --- progresso monotono a blocchi -------------------------------------------


def test_watermark_avanza_a_ogni_blocco() -> None:
    scritture = []
    deps, wm, _ = _deps([(u, bytes([u])) for u in range(1, 8)], chunk_size=3)
    real_write = deps.write_watermark

    def spy(b, e, u, folder="INBOX", uidvalidity=None):
        scritture.append((folder, u))
        real_write(b, e, u, folder=folder, uidvalidity=uidvalidity)

    deps.write_watermark = spy
    fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)

    assert [u for f, u in scritture if f == "INBOX"] == [3, 6, 7]


def test_guasto_a_meta_cartella_conserva_i_blocchi_gia_fatti() -> None:
    """Il rilievo che ha originato il chunking: prima, un EOF a metà della
    cartella Inviata di INTUR (2800 messaggi) buttava via tutto e il
    watermark non avanzava mai — livelock a ogni notte."""
    deps, wm, calls = _deps([(u, bytes([u])) for u in range(1, 10)], chunk_size=3)
    real_fetch = deps.fetch_since

    def flaky(cfg, since_uid, folder="INBOX", since_date=None, conn_factory=None,
              uidvalidity=None, chunk_size=3):
        for n, blk in enumerate(real_fetch(cfg, since_uid, folder=folder)):
            if n == 2:
                raise ConnectionError("socket error: EOF")
            yield blk

    deps.fetch_since = flaky
    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)

    assert res.status == "FAILED"
    assert wm[("VIGNA", "INBOX")].last_uid == 6, "i due blocchi buoni restano acquisiti"
    assert res.ingested == 6

    # il giro dopo riparte da 6 e completa: la cartella avanza, non si azzera
    deps.fetch_since = real_fetch
    res2 = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert (res2.status, res2.ingested) == ("OK", 3)
    assert wm[("VIGNA", "INBOX")].last_uid == 9


def test_eml_cancellato_dopo_ogni_intake() -> None:
    """Su Cloud Run la temp dir è tmpfs (RAM): gli .eml non si accumulano."""
    presenti = []
    deps, _, _ = _deps([(u, bytes([u])) for u in range(1, 6)], chunk_size=5)
    real_intake = deps.intake_file

    def spy(path, source_name, actor):
        presenti.append(len(list(path.parent.glob("*.eml"))))
        return real_intake(path, source_name=source_name, actor=actor)

    deps.intake_file = spy
    fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)

    assert presenti == [1, 1, 1, 1, 1], "mai più di una busta per volta su disco"


def test_uidvalidity_scritta_nel_watermark() -> None:
    deps, wm, _ = _deps([(11, b"una")])
    fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert wm[("VIGNA", "INBOX")].uidvalidity == UV


# --- il promote non fallisce in silenzio ------------------------------------


def test_promote_rejected_conta_ma_non_fa_fallire_il_giro(caplog) -> None:
    """Una busta che il parser rifiuta è qualità del dato, non guasto di
    sistema: l'oggetto è su GCS e in f_raw_objects, si recupera con
    `hotelops promote --raw-object-id`. Farne un allarme notturno significa
    che l'utente smette di leggere gli allarmi."""
    deps, _, _ = _deps(
        [(11, b"una"), (12, b"due")],
        promotion=lambda: _promotion("REJECTED", "VALIDATE_FAIL"),
    )
    with caplog.at_level(logging.ERROR, logger="ingest.pec_fetch"):
        res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)

    assert (res.ingested, res.promoted, res.rejected) == (2, 0, 2)
    assert res.status == "OK", "rejected non è un guasto di sistema"
    assert res.error is None
    assert "ro-" in caplog.text, "ma il raw_object_id resta a log, recuperabile"


def test_rifiuti_non_mascherano_una_cartella_giu() -> None:
    """Se cade una cartella E ci sono rifiuti, il guasto vince: FAILED."""
    deps, _, _ = _deps(
        {"INBOX": [(11, b"una")]},
        promotion=lambda: _promotion("REJECTED", "VALIDATE_FAIL"),
    )
    real_fetch = deps.fetch_since

    def fake_fetch(cfg, since_uid, folder="INBOX", since_date=None, conn_factory=None,
                   uidvalidity=None, chunk_size=50):
        if folder == "INBOX.Inviata":
            raise ConnectionError("Inviata giù")
        return real_fetch(cfg, since_uid, folder=folder, since_date=since_date)

    deps.fetch_since = fake_fetch
    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)

    assert (res.status, res.rejected) == ("FAILED", 1)
    assert "Inviata" in res.error


def test_promote_ok_conta_i_promossi() -> None:
    deps, _, _ = _deps([(11, b"una"), (12, b"due")])
    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert (res.promoted, res.rejected, res.status) == (2, 0, "OK")


def test_intake_senza_raw_object_id_non_passa_in_silenzio() -> None:
    """Con il lineage gate optional/disabled l'intake non torna un id: il
    promote non può partire e il giro NON deve dirsi riuscito."""
    deps, wm, calls = _deps([(11, b"una")])
    real_intake = deps.intake_file

    def senza_id(path, source_name, actor):
        out = real_intake(path, source_name=source_name, actor=actor)
        out.raw_object_id = None
        return out

    deps.intake_file = senza_id
    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)

    assert res.status == "FAILED"
    assert "raw_object_id" in res.error
    assert calls["promote"] == []
    assert ("VIGNA", "INBOX") not in wm, "watermark fermo: niente è davvero atterrato"


def test_no_promote_non_richiede_raw_object_id() -> None:
    """--no-promote è un uso legittimo: nessun promote, nessun errore."""
    deps, wm, calls = _deps([(11, b"una")])
    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", promote=False, deps=deps)
    assert (res.status, res.ingested, res.promoted) == ("OK", 1, 0)
    assert calls["promote"] == []
    assert wm[("VIGNA", "INBOX")].last_uid == 11


def test_main_exit_2_su_fallimento(monkeypatch, capsys, lock_libero) -> None:
    def fake_fetch_mailbox(name, since_days=7, promote=True, deps=None):
        if name == "PEC_MAILBOX_ORTI_APPEND":
            return FetchResult(entity_id="ORTI", status="FAILED", error="giù")
        return FetchResult(entity_id=name, status="OK")

    monkeypatch.setattr(pec_fetch, "fetch_mailbox", fake_fetch_mailbox)
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--all"])

    with pytest.raises(SystemExit) as exc_info:
        pec_fetch.main()

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "ORTI" in captured.err


def test_main_ok_quando_tutte_riescono(monkeypatch, capsys, lock_libero) -> None:
    def fake_fetch_mailbox(name, since_days=7, promote=True, deps=None):
        return FetchResult(entity_id=name, status="OK")

    monkeypatch.setattr(pec_fetch, "fetch_mailbox", fake_fetch_mailbox)
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--all"])

    pec_fetch.main()  # non deve sollevare SystemExit

    captured = capsys.readouterr()
    assert "PARZIALE" not in captured.err


def test_main_all_seleziona_solo_caselle_con_imap(monkeypatch, lock_libero) -> None:
    """Legge il registry reale: deve includere le 3 caselle con blocco imap
    ed escludere PEC_MAILBOX_PERSONALE_APPEND, che non ce l'ha."""
    seen = []

    def fake_fetch_mailbox(name, since_days=7, promote=True, deps=None):
        seen.append(name)
        return FetchResult(entity_id=name, status="OK")

    monkeypatch.setattr(pec_fetch, "fetch_mailbox", fake_fetch_mailbox)
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--all"])

    pec_fetch.main()

    assert set(seen) == {
        "PEC_MAILBOX_INTUR_APPEND",
        "PEC_MAILBOX_ORTI_APPEND",
        "PEC_MAILBOX_VIGNA_APPEND",
    }
    assert "PEC_MAILBOX_PERSONALE_APPEND" not in seen


def test_main_all_senza_caselle_grida(monkeypatch) -> None:
    """Una modifica sbagliata al registry non deve trasformare il job
    notturno in un no-op verde."""

    class _VuotoRegistry:
        def find_all_by_detector_category(self, _cat):
            return []

    monkeypatch.setattr(
        "core.lineage.source_resolver.load_registry", lambda: _VuotoRegistry()
    )
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--all"])

    with pytest.raises(SystemExit) as exc_info:
        pec_fetch.main()

    assert exc_info.value.code != 0
    assert "imap" in str(exc_info.value.code)


def test_main_stampa_cartelle_e_rifiutate(monkeypatch, capsys, lock_libero) -> None:
    def fake_fetch_mailbox(name, since_days=7, promote=True, deps=None):
        return FetchResult(
            entity_id=name,
            fetched=5,
            ingested=5,
            promoted=4,
            rejected=1,
            status="FAILED",
            error="INBOX.Inviata: giù",
            per_folder={"INBOX": 5, "INBOX.Inviata": 0},
        )

    monkeypatch.setattr(pec_fetch, "fetch_mailbox", fake_fetch_mailbox)
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--source-name", "PEC_MAILBOX_VIGNA_APPEND"])

    with pytest.raises(SystemExit):
        pec_fetch.main()

    out = capsys.readouterr().out
    assert "rejected=1" in out
    assert "INBOX=5" in out and "INBOX.Inviata=0" in out


def test_main_continua_se_una_casella_solleva_inaspettatamente(
    monkeypatch, capsys, lock_libero
) -> None:
    """Un bug non intercettato in fetch_mailbox non deve fermare il giro:
    le altre caselle vanno comunque tentate, exit 2 con l'elenco."""
    seen = []

    def fake_fetch_mailbox(name, since_days=7, promote=True, deps=None):
        seen.append(name)
        if name == "PEC_MAILBOX_ORTI_APPEND":
            raise RuntimeError("bug inatteso")
        return FetchResult(entity_id=name, status="OK")

    monkeypatch.setattr(pec_fetch, "fetch_mailbox", fake_fetch_mailbox)
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--all"])

    with pytest.raises(SystemExit) as exc_info:
        pec_fetch.main()

    assert exc_info.value.code == 2
    assert "PEC_MAILBOX_INTUR_APPEND" in seen
    assert "PEC_MAILBOX_VIGNA_APPEND" in seen, "la casella dopo quella guasta va comunque tentata"
    captured = capsys.readouterr()
    assert "PEC_MAILBOX_ORTI_APPEND" in captured.err


# --- rifiuti visibili ma non allarmanti in main() ----------------------------


def test_main_non_esce_2_per_soli_rifiuti(monkeypatch, capsys, lock_libero) -> None:
    """Il job notturno non presidiato manda mail solo sui guasti veri."""

    def fake_fetch_mailbox(name, since_days=7, promote=True, deps=None):
        return FetchResult(entity_id=name, fetched=3, ingested=3, promoted=2, rejected=1)

    monkeypatch.setattr(pec_fetch, "fetch_mailbox", fake_fetch_mailbox)
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--all"])

    pec_fetch.main()  # niente SystemExit = exit 0

    out = capsys.readouterr()
    assert "rejected=1" in out.out
    assert "PARZIALE" not in out.err


def test_main_riepiloga_i_rifiuti_a_fine_giro(monkeypatch, capsys, lock_libero) -> None:
    """Non-allarmanti sì, invisibili no: nei log del job il totale si vede."""

    def fake_fetch_mailbox(name, since_days=7, promote=True, deps=None):
        return FetchResult(entity_id=name, promoted=1, rejected=2)

    monkeypatch.setattr(pec_fetch, "fetch_mailbox", fake_fetch_mailbox)
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--all"])

    pec_fetch.main()

    out = capsys.readouterr().out
    assert "6 buste rifiutate" in out, "3 caselle x 2 rifiuti"
    assert "promote --raw-object-id" in out, "dice come si recuperano"


def test_main_niente_riga_rifiuti_se_zero(monkeypatch, capsys, lock_libero) -> None:
    def fake_fetch_mailbox(name, since_days=7, promote=True, deps=None):
        return FetchResult(entity_id=name)

    monkeypatch.setattr(pec_fetch, "fetch_mailbox", fake_fetch_mailbox)
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--all"])

    pec_fetch.main()

    assert "rifiutate" not in capsys.readouterr().out


# --- lock globale in main() --------------------------------------------------


def test_main_esce_zero_se_un_giro_e_gia_in_corso(monkeypatch, capsys) -> None:
    """Lock occupato da un giro vivo: non è un errore. Exit 2 qui vorrebbe
    dire una mail d'allarme per un'esecuzione manuale innocua."""
    chiamate = []

    @contextlib.contextmanager
    def occupato(*a, **k):
        raise LockBusy(dt.datetime(2026, 7, 31, 4, 0, tzinfo=dt.timezone.utc))
        yield  # pragma: no cover

    monkeypatch.setattr(pec_fetch, "pec_lock_held", occupato)
    monkeypatch.setattr(
        pec_fetch, "fetch_mailbox", lambda *a, **k: chiamate.append(a) or FetchResult("X")
    )
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--all"])

    pec_fetch.main()  # niente SystemExit = exit 0

    out = capsys.readouterr().out
    assert "in corso" in out and "2026-07-31" in out
    assert chiamate == [], "nessuna casella lavorata in parallelo"


def test_main_prende_e_rilascia_il_lock(monkeypatch, capsys, lock_libero) -> None:
    def fake_fetch_mailbox(name, since_days=7, promote=True, deps=None):
        return FetchResult(entity_id=name)

    monkeypatch.setattr(pec_fetch, "fetch_mailbox", fake_fetch_mailbox)
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--all"])

    pec_fetch.main()

    assert lock_libero == ["acquisito", "rilasciato"]


def test_main_rilascia_il_lock_anche_se_il_giro_fallisce(
    monkeypatch, capsys, lock_libero
) -> None:
    """Il giro esce 2 (SystemExit): il lock non deve restare appeso, se no
    la notte dopo il job si trova bloccato dal proprio cadavere."""

    def fake_fetch_mailbox(name, since_days=7, promote=True, deps=None):
        return FetchResult(entity_id=name, status="FAILED", error="giù")

    monkeypatch.setattr(pec_fetch, "fetch_mailbox", fake_fetch_mailbox)
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--all"])

    with pytest.raises(SystemExit):
        pec_fetch.main()

    assert lock_libero == ["acquisito", "rilasciato"]


def test_main_prende_il_lock_anche_con_source_name(monkeypatch, capsys, lock_libero) -> None:
    """Il lock è globale: la stessa PEC arriva a INTUR e a ORTI con lo stesso
    msgid, quindi anche un giro su una sola casella deve prenderlo."""
    monkeypatch.setattr(
        pec_fetch, "fetch_mailbox", lambda *a, **k: FetchResult(entity_id="VIGNA")
    )
    monkeypatch.setattr(
        sys, "argv", ["pec_fetch", "--source-name", "PEC_MAILBOX_VIGNA_APPEND"]
    )

    pec_fetch.main()

    assert lock_libero == ["acquisito", "rilasciato"]


# --- il parser rotto non è "qualità del dato" -------------------------------


def test_main_esce_2_se_nessuna_busta_e_stata_promossa(
    monkeypatch, capsys, lock_libero
) -> None:
    """Una busta su mille rifiutata è qualità del dato; mille su mille è il
    parser rotto. Senza questa guardia un deploy sbagliato darebbe giri verdi
    per quante notti serve, senza una mail."""

    def fake_fetch_mailbox(name, since_days=7, promote=True, deps=None):
        return FetchResult(entity_id=name, fetched=4, ingested=4, promoted=0, rejected=4)

    monkeypatch.setattr(pec_fetch, "fetch_mailbox", fake_fetch_mailbox)
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--all"])

    with pytest.raises(SystemExit) as exc_info:
        pec_fetch.main()

    assert exc_info.value.code == 2
    assert "nessuna busta promossa" in capsys.readouterr().err


def test_main_resta_verde_se_almeno_una_busta_passa(
    monkeypatch, capsys, lock_libero
) -> None:
    """La guardia è sul caso degenere categorico, non su una soglia."""

    def fake_fetch_mailbox(name, since_days=7, promote=True, deps=None):
        return FetchResult(entity_id=name, fetched=10, ingested=10, promoted=9, rejected=1)

    monkeypatch.setattr(pec_fetch, "fetch_mailbox", fake_fetch_mailbox)
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--all"])

    pec_fetch.main()  # niente SystemExit

    assert "nessuna busta promossa" not in capsys.readouterr().err


def test_main_guarda_i_totali_del_giro_non_la_singola_casella(
    monkeypatch, capsys, lock_libero
) -> None:
    """Il parser è lo stesso per tutte le caselle: se una promuove, non è
    rotto. La guardia lavora sui totali del giro, di proposito."""

    def fake_fetch_mailbox(name, since_days=7, promote=True, deps=None):
        if name == "PEC_MAILBOX_ORTI_APPEND":
            return FetchResult(entity_id=name, ingested=2, promoted=0, rejected=2)
        return FetchResult(entity_id=name, ingested=2, promoted=2)

    monkeypatch.setattr(pec_fetch, "fetch_mailbox", fake_fetch_mailbox)
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--all"])

    pec_fetch.main()

    out = capsys.readouterr()
    assert "2 buste rifiutate" in out.out, "restano visibili"
    assert "nessuna busta promossa" not in out.err


def test_main_niente_falso_allarme_con_no_promote(monkeypatch, capsys, lock_libero) -> None:
    """`--no-promote` non promuove niente per definizione: non è un guasto."""

    def fake_fetch_mailbox(name, since_days=7, promote=True, deps=None):
        return FetchResult(entity_id=name, fetched=3, ingested=3, promoted=0, rejected=0)

    monkeypatch.setattr(pec_fetch, "fetch_mailbox", fake_fetch_mailbox)
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--all", "--no-promote"])

    pec_fetch.main()  # niente SystemExit


# --- SIGTERM: il timeout del job non deve diventare un successo -------------


def test_sigterm_rilascia_il_lock(monkeypatch, lock_libero) -> None:
    """Task timeout a 60m → SIGTERM. Senza handler Python non esegue i
    `finally`: il lock resta appeso, il retry lo trova fresco ed esce 0, e
    un timeout (che prima era rosso) diventa un'esecuzione riuscita."""
    precedente = signal.getsignal(signal.SIGTERM)

    def fake_fetch_mailbox(name, since_days=7, promote=True, deps=None):
        assert signal.getsignal(signal.SIGTERM) not in (
            signal.SIG_DFL,
            signal.SIG_IGN,
        ), "main() non ha installato l'handler SIGTERM"
        os.kill(os.getpid(), signal.SIGTERM)
        return FetchResult(entity_id=name)  # pragma: no cover

    monkeypatch.setattr(pec_fetch, "fetch_mailbox", fake_fetch_mailbox)
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--all"])

    try:
        with pytest.raises(SystemExit) as exc_info:
            pec_fetch.main()
        assert exc_info.value.code == 143, "128 + 15, la convenzione per SIGTERM"
        assert lock_libero == ["acquisito", "rilasciato"]
    finally:
        signal.signal(signal.SIGTERM, precedente)
