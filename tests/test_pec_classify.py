"""Classificatore PEC: multi-match, priorità, AMBIGUO, versioning."""

from __future__ import annotations


from ingest.pec.classify import Rule, Ruleset, classify_message, load_ruleset


def _rs(rules) -> Ruleset:
    return Ruleset(version="9.9.9", rules=rules)


def test_load_ruleset_reale():
    rs = load_ruleset()
    assert rs.version == "1.0.0"
    assert any(r.id == "legale-oggetto" for r in rs.rules)


def test_match_singolo_banca():
    out = classify_message("filiale@pec.gruppobper.it", "Estratto conto", [], load_ruleset())
    assert out["stato"] == "CLASSIFICATO"
    assert out["primary_category"] == "BANCA"
    assert out["importance"] == "NORMALE"
    assert "banca" in out["matches"]


def test_multi_match_vince_priorita():
    # banca + oggetto legale → LEGALE (priority 100 > 70), entrambi in matches
    out = classify_message(
        "filiale@pec.gruppobper.it", "Diffida ad adempiere", [], load_ruleset()
    )
    assert out["primary_category"] == "LEGALE"
    assert out["importance"] == "ALTA"
    assert set(out["matches"]) >= {"banca", "legale-oggetto"}


def test_pari_priorita_categorie_diverse_ambiguo():
    rs = _rs([
        Rule(id="a", priority=50, match={"subject_regex": "x"},
             assign={"category": "BANCA"}),
        Rule(id="b", priority=50, match={"subject_regex": "x"},
             assign={"category": "FISCO"}),
    ])
    out = classify_message("chiunque@pec.it", "x", [], rs)
    assert out["stato"] == "AMBIGUO"
    assert set(out["matches"]) == {"a", "b"}


def test_nessun_match_non_classificato():
    out = classify_message("ignoto@pec.qualcosa.it", "Ciao", [], load_ruleset())
    assert out["stato"] == "NON_CLASSIFICATO"
    assert out["primary_category"] is None
    assert out["importance"] == "DA_RIVEDERE"


def test_document_type_da_allegato_non_decide_categoria():
    out = classify_message(
        "filiale@pec.gruppobper.it", "Invio", ["BILANCIO 2025.pdf"], load_ruleset()
    )
    assert out["primary_category"] == "BANCA"
    assert out["document_type"] == "BILANCIO"
    assert out["importance"] == "ALTA"  # doc-bilancio alza l'importanza


def test_regex_rotta_errore_classificazione():
    rs = _rs([Rule(id="rotta", priority=1, match={"subject_regex": "("},
                   assign={"category": "BANCA"})])
    out = classify_message("x@pec.it", "s", [], rs)
    assert out["stato"] == "ERRORE_CLASSIFICAZIONE"


def test_riga_classificazione_valida():
    from datetime import datetime

    from core.schemas import PecClassificazioneRow, validate_batch

    row = {
        "msgid": "m1", "entity_id": "ORTI", "stato": "CLASSIFICATO",
        "primary_category": "BANCA", "importance": "NORMALE",
        "document_type": "ALTRO", "matches": '["banca"]',
        "ruleset_version": "1.0.0", "classified_at": datetime(2026, 7, 17),
        "override_source": None, "override_note": None,
        "hash_riga": "h", "data_caricamento": datetime(2026, 7, 17),
    }
    validate_batch([row], PecClassificazioneRow, context="test")
