import sys
from dataclasses import dataclass

import pytest

from ingest import pec_fetch
from ingest.pec_fetch import Deps, FetchResult, fetch_mailbox


@dataclass
class _IntakeResult:
    raw_object_id: str
    content_hash: str
    deduped: bool


def _deps(messages, watermarks=None):
    """`messages` è o una lista (trattata come sola INBOX) o un dict
    {folder: [(uid, bytes), ...]} per test multi-cartella. Le cartelle non
    presenti nel dict tornano vuote (comportamento della vera Inviata quando
    un test non se ne occupa)."""
    messages_by_folder = messages if isinstance(messages, dict) else {"INBOX": messages}
    wm = {(entity, "INBOX"): uid for entity, uid in (watermarks or {}).items()}
    seen = set()
    calls = {"intake": [], "promote": []}

    def fake_fetch(cfg, since_uid, folder="INBOX", since_date=None, conn_factory=None):
        return [(u, b) for u, b in messages_by_folder.get(folder, []) if u > since_uid]

    def fake_intake(path, source_name, actor):
        h = str(hash(path.read_bytes()))
        deduped = h in seen
        seen.add(h)
        calls["intake"].append((source_name, h, deduped))
        return _IntakeResult(f"ro-{h}", h, deduped)

    def fake_promote(raw_object_id, actor):
        calls["promote"].append(raw_object_id)
        return type("P", (), {"status": "PROMOTED", "reason": None, "noop": False})()

    return Deps(
        fetch_since=fake_fetch,
        read_watermark=lambda b, e, folder="INBOX": wm.get((e, folder), 0),
        write_watermark=lambda b, e, u, folder="INBOX": wm.__setitem__((e, folder), u),
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
    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert res.last_uid == 12
    assert wm[("VIGNA", "INBOX")] == 12


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
    assert wm[("VIGNA", "INBOX")] == 50


def test_sorgente_sconosciuta_solleva() -> None:
    deps, _, _ = _deps([])
    with pytest.raises(ValueError, match="non nel registry"):
        fetch_mailbox("PEC_MAILBOX_PIPPO_APPEND", deps=deps)


def test_intake_fallisce_a_meta_giro_produce_failed_e_non_avanza_watermark() -> None:
    """Errore transiente GCS/BQ su intake_file: non deve crashare, watermark fermo."""
    messages = [(11, b"una"), (12, b"due"), (13, b"tre")]
    wm: dict = {}
    calls = {"intake": [], "promote": []}

    def fake_fetch(cfg, since_uid, folder="INBOX", since_date=None, conn_factory=None):
        if folder != "INBOX":
            return []
        return [(u, b) for u, b in messages if u > since_uid]

    def fake_intake(path, source_name, actor):
        calls["intake"].append(path.name)
        if len(calls["intake"]) == 2:
            raise ConnectionError("GCS giù")
        return _IntakeResult(f"ro-{path.name}", path.name, False)

    def fake_promote(raw_object_id, actor):
        calls["promote"].append(raw_object_id)
        return type("P", (), {"status": "PROMOTED", "reason": None, "noop": False})()

    deps = Deps(
        fetch_since=fake_fetch,
        read_watermark=lambda b, e, folder="INBOX": wm.get(e, 0),
        write_watermark=lambda b, e, u, folder="INBOX": wm.__setitem__(e, u),
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

    def fake_fetch(cfg, since_uid, folder="INBOX", since_date=None, conn_factory=None):
        if folder == "INBOX.Inviata":
            raise ConnectionError("Inviata giù")
        return real_fetch(cfg, since_uid, folder=folder, since_date=since_date)

    deps.fetch_since = fake_fetch

    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)

    assert res.per_folder["INBOX"] == 2
    assert len(calls["intake"]) == 2
    assert wm[("VIGNA", "INBOX")] == 12
    assert ("VIGNA", "INBOX.Inviata") not in wm
    assert res.status == "FAILED"


def test_cartella_inbox_irraggiungibile_non_blocca_inviata() -> None:
    """Speculare al test sopra: se a fallire è la PRIMA cartella elencata
    nel registry (INBOX), la seconda (INBOX.Inviata) deve essere comunque
    tentata. Un try/except che avvolgesse l'intero ciclo invece della
    singola iterazione farebbe fallire anche questo assert."""
    deps, wm, calls = _deps({"INBOX.Inviata": [(21, b"ventuno"), (22, b"ventidue")]})
    real_fetch = deps.fetch_since

    def fake_fetch(cfg, since_uid, folder="INBOX", since_date=None, conn_factory=None):
        if folder == "INBOX":
            raise ConnectionError("INBOX giù")
        return real_fetch(cfg, since_uid, folder=folder, since_date=since_date)

    deps.fetch_since = fake_fetch

    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)

    assert res.per_folder["INBOX.Inviata"] == 2
    assert len(calls["intake"]) == 2
    assert wm[("VIGNA", "INBOX.Inviata")] == 22
    assert ("VIGNA", "INBOX") not in wm
    assert res.status == "FAILED"


def test_main_exit_2_su_fallimento(monkeypatch, capsys) -> None:
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


def test_main_ok_quando_tutte_riescono(monkeypatch, capsys) -> None:
    def fake_fetch_mailbox(name, since_days=7, promote=True, deps=None):
        return FetchResult(entity_id=name, status="OK")

    monkeypatch.setattr(pec_fetch, "fetch_mailbox", fake_fetch_mailbox)
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--all"])

    pec_fetch.main()  # non deve sollevare SystemExit

    captured = capsys.readouterr()
    assert "PARZIALE" not in captured.err


def test_main_all_seleziona_solo_caselle_con_imap(monkeypatch) -> None:
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


def test_main_continua_se_una_casella_solleva_inaspettatamente(monkeypatch, capsys) -> None:
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
