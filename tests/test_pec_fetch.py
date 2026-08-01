from dataclasses import dataclass

import pytest

from ingest.pec_fetch import Deps, fetch_mailbox


@dataclass
class _IntakeResult:
    raw_object_id: str
    content_hash: str
    deduped: bool


def _deps(messages, watermarks=None):
    wm = dict(watermarks or {})
    seen = set()
    calls = {"intake": [], "promote": []}

    def fake_fetch(cfg, since_uid, since_date=None, conn_factory=None):
        return [(u, b) for u, b in messages if u > since_uid]

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
        read_watermark=lambda b, e: wm.get(e, 0),
        write_watermark=lambda b, e, u: wm.__setitem__(e, u),
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
    assert wm["VIGNA"] == 12


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
    assert wm["VIGNA"] == 50


def test_sorgente_sconosciuta_solleva() -> None:
    deps, _, _ = _deps([])
    with pytest.raises(ValueError, match="non nel registry"):
        fetch_mailbox("PEC_MAILBOX_PIPPO_APPEND", deps=deps)
