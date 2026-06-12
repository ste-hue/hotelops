"""PF xlsx ingest — hash generazionale."""

import hashlib

from ingest.flussi.ingest_piano_finanziario_xlsx import make_hash


def test_hash_legacy_senza_raw_object_id():
    # Righe pre-lineage / run standalone senza --raw-object-id: hash invariato
    h = make_hash("ORTI", "USCITE_UTENZE", 2026, 7, "PIANO_FINANZIARIO")
    atteso = hashlib.md5(
        "ORTI|USCITE_UTENZE|2026|7|PIANO_FINANZIARIO".encode()
    ).hexdigest()
    assert h == atteso


def test_hash_distinto_per_generazione():
    h1 = make_hash(
        "ORTI", "USCITE_UTENZE", 2026, 7, "PIANO_FINANZIARIO",
        raw_object_id="ro-generazione-aprile",
    )
    h2 = make_hash(
        "ORTI", "USCITE_UTENZE", 2026, 7, "PIANO_FINANZIARIO",
        raw_object_id="ro-generazione-maggio",
    )
    assert h1 != h2


def test_hash_generazionale_diverso_dal_legacy():
    legacy = make_hash("ORTI", "USCITE_UTENZE", 2026, 7, "PIANO_FINANZIARIO")
    gen = make_hash(
        "ORTI", "USCITE_UTENZE", 2026, 7, "PIANO_FINANZIARIO",
        raw_object_id="ro-x",
    )
    assert legacy != gen


def test_pf_sources_generazionali():
    from core.lineage.source_resolver import load_registry

    reg = load_registry()
    assert reg.get("ESOLVER_PF_ORTI_SNAPSHOT") is None, "rename non applicato"
    for name, societa in [
        ("ESOLVER_PF_ORTI_APPEND", "ORTI"),
        ("ESOLVER_PF_INTUR_APPEND", "INTUR"),
    ]:
        sd = reg.get(name)
        assert sd is not None, f"{name} mancante"
        assert sd.lifecycle == "APPEND"
        assert sd.societa == societa
        assert sd.canonical_table == "f_piano_finanziario_input"
