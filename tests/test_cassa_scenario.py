import json
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from verticals.condges.cassa_motore import (
    Ancora,
    Finanziamento,
    Input,
    Pagamento,
    Progetto,
    Riga,
    ScalettaCanone,
    Scenario,
    calcola,
    to_cent,
    to_dict,
)
from verticals.condges.cassa_scenario import (
    SCHEMA,
    base_uguale,
    carica_seme,
    righe_p,
    scenario_da_righe,
    scenario_from_json,
    scenario_id,
    scenario_to_json,
)

MESI = [f"2026-{m:02d}" for m in (10, 11, 12)] + [f"2027-{m:02d}" for m in range(1, 13)]
SEI = MESI[:6]


def scenario_sintetico():
    pagamenti = [
        Pagamento(
            nome=n,
            mesi={m: to_cent(5000 + i) for i, m in enumerate(SEI)},
            aliquota_iva=22,
            stato="ipotesi",
            fornitore_id=f"F{k}",
        )
        for k, n in enumerate(("Lavori", "Arredi"))
    ]
    sc = Scenario(
        nome="s",
        progetti=[Progetto("P1", "Camere", "ORTI", True, "ipotesi", pagamenti)],
        finanziamenti=[
            Finanziamento(
                "FIN1",
                "Mutuo",
                "INTUR",
                {"2026-11": to_cent(300_000)},
                {"2027-01": to_cent(10_000), "2027-02": to_cent(10_000)},
                "ipotesi",
            )
        ],
        canone=ScalettaCanone({2027: to_cent(800_000)}, 4, "2027-03"),
        manuali=[Riga("ORTI", "extra", "2026-12", 10_000_000, "U", "manuale")],
        soglia=to_cent(50_000),
    )
    base = {
        "ORTI": {
            "file_sorgente": "o.xlsx",
            "raw_object_id": "r1",
            "data_caricamento": "2026-10-01",
        },
        "INTUR": {
            "file_sorgente": "i.xlsx",
            "raw_object_id": "r2",
            "data_caricamento": "2026-10-01",
        },
    }
    return sc, base


def inp_minimo(sc):
    return Input(
        mesi=MESI,
        mesi_ipotetici=frozenset(),
        ancore={
            "INTUR": Ancora("INTUR", date(2026, 9, 30), to_cent(100_000), True, {}),
            "ORTI": Ancora("ORTI", date(2026, 9, 30), to_cent(500_000), True, {}),
        },
        pf=[Riga("ORTI", "costi", m, to_cent(20_000), "U", "pf") for m in MESI],
        intercompany=[],
        fatti=[],
        scenario=sc,
    )


def test_round_trip_json_scenario():
    sc, base = scenario_sintetico()
    sc2, base2, meta = scenario_from_json(scenario_to_json(sc, base, nome="t"))
    assert sc2 == sc and base2 == base
    assert meta["schema"] == SCHEMA and meta["nome"] == "t"


def test_importo_non_intero_rifiutato():
    raw = scenario_to_json(*scenario_sintetico(), "t").replace(
        '"importo_cent": 10000000', '"importo_cent": 10000000.5', 1
    )
    assert "10000000.5" in raw
    with pytest.raises(ValueError, match="centesimi"):
        scenario_from_json(raw)


def test_importo_bool_rifiutato():
    raw = scenario_to_json(*scenario_sintetico(), "t").replace(
        '"importo_cent": 10000000', '"importo_cent": true', 1
    )
    assert '"importo_cent": true' in raw
    with pytest.raises(ValueError, match="centesimi"):
        scenario_from_json(raw)


def test_scenario_id_ignora_data_salvataggio():
    sc, base = scenario_sintetico()
    a = scenario_to_json(sc, base, "t", datetime(2026, 1, 1))
    b = scenario_to_json(sc, base, "t", datetime(2026, 2, 2))
    assert a != b and scenario_id(a) == scenario_id(b) and len(scenario_id(a)) == 16


def test_righe_p_e_ritorno_danno_lo_stesso_risultato():
    sc, base = scenario_sintetico()
    raw = scenario_to_json(sc, base, "t")
    s, f, p = righe_p(raw, "rid", datetime(2026, 10, 29), "stefano")
    assert len(s) == 1 and len(p) == 2 * 6
    assert all(r["raw_object_id"] == "rid" for r in f + p)
    assert s[0]["progetti_accesi"] == ["P1"]
    assert all(type(r["importo_cent"]) is int for r in f)
    ((sc2, base2, meta),) = scenario_da_righe(s, f, p)
    assert base2 == base and meta["nome"] == "t"
    assert sc2 == sc
    assert to_dict(calcola(inp_minimo(sc2))) == to_dict(calcola(inp_minimo(sc)))


def test_schema_diverso_rifiutato():
    with pytest.raises(ValueError, match="cdg-cassa-scenario/1"):
        scenario_from_json(json.dumps({"schema": "altro"}))


def test_base_diversa_si_vede():
    assert not base_uguale(
        {"ORTI": {"raw_object_id": "a"}}, {"ORTI": {"raw_object_id": "b"}}
    )
    assert base_uguale(
        {"ORTI": {"raw_object_id": "a"}}, {"ORTI": {"raw_object_id": "a"}}
    )
    assert not base_uguale({"ORTI": {"raw_object_id": "a"}}, {})


def test_carica_seme(tmp_path):
    sc, base = scenario_sintetico()
    f = tmp_path / "seme.json"
    f.write_text(scenario_to_json(sc, base, "seme"), encoding="utf-8")
    assert carica_seme(f) == (sc, base)


def _righe(sc, base):
    return righe_p(scenario_to_json(sc, base, "t"), "rid", datetime(2026, 10, 29), "s")


def test_manuali_stessa_chiave_importi_diversi_hash_diversi():
    sc, base = scenario_sintetico()
    sc = replace(
        sc,
        manuali=[
            Riga("ORTI", "x", "2026-12", 100, "U", "manuale"),
            Riga("ORTI", "x", "2026-12", 200, "U", "manuale"),
        ],
    )
    rows = _righe(sc, base)
    man = [r for r in rows[1] if r["origine"] == "manuale"]
    assert len({r["hash_riga"] for r in man}) == 2
    ((sc2, _, _),) = scenario_da_righe(*rows)
    assert sorted(r.importo for r in sc2.manuali) == [100, 200]


def test_pagamento_duplicato_nel_progetto_rifiutato():
    sc, base = scenario_sintetico()
    p = sc.progetti[0]
    dup = replace(sc, progetti=[replace(p, pagamenti=[p.pagamenti[0]] * 2)])
    with pytest.raises(ValueError, match="P1.*Lavori"):
        scenario_from_json(scenario_to_json(dup, base, "t"))


def test_manuale_con_altra_origine_resta_manuale():
    sc, base = scenario_sintetico()
    sc = replace(sc, manuali=[Riga("ORTI", "x", "2026-12", 123, "U", "pf")])
    ((sc2, _, _),) = scenario_da_righe(*_righe(sc, base))
    assert [(r.importo, r.origine) for r in sc2.manuali] == [(123, "manuale")]


@pytest.mark.parametrize(
    "path",
    [
        ("progetti", 0, "pagamenti", 0, "mesi", "2026-10"),
        ("soglia",),
        ("canone", "netto_per_anno", "2027"),
        ("canone", "calendario", "2027-05"),
        ("finanziamenti", 0, "rate", "2027-01"),
    ],
)
def test_importo_non_intero_in_ogni_campo(path):
    sc, base = scenario_sintetico()
    sc = replace(sc, canone=replace(sc.canone, calendario={"2027-05": 100}))
    doc = json.loads(scenario_to_json(sc, base, "t"))
    d = doc["scenario"]
    for k in path[:-1]:
        d = d[k]
    d[path[-1]] = 1.5
    with pytest.raises(ValueError, match="centesimi"):
        scenario_from_json(json.dumps(doc))


CONTRATTO_AMCN = {
    "fornitore": "AMCN",
    "totale": to_cent(482_000),
    "aliquota_iva": 0,
    "anticipo_pct": 15,
    "anticipo_mese": "2026-10",
    "ritenuta_pct": 10,
    "svincolo_mese": "2027-05",
    "sal_modo": "n",
    "sal_n": 5,
    "sal_ogni": 0,
    "sal_da": "2026-11",
    "sal_passo": 1,
}


def test_importo_del_finanziamento_sopravvive_a_json_e_righe():
    # L'importo promesso dalla banca è un campo facoltativo: la pagina lo usa per «erogato X di Y».
    sc, base = scenario_sintetico()
    con = replace(sc, finanziamenti=[replace(sc.finanziamenti[0], importo=to_cent(1_100_000))])
    doc = scenario_to_json(con, base)
    assert json.loads(doc)["scenario"]["finanziamenti"][0]["importo"] == to_cent(1_100_000)
    sc2, _, _ = scenario_from_json(doc)
    assert sc2.finanziamenti[0].importo == to_cent(1_100_000)
    s, f, p = righe_p(doc, "rid", datetime(2026, 10, 31, tzinfo=UTC), "stefano")
    ((sc3, _, _),) = scenario_da_righe(s, f, p)
    assert sc3.finanziamenti[0].importo == to_cent(1_100_000) and sc3 == con
    # senza importo il documento resta com'era (nessuna chiave nuova): i vecchi hash non cambiano
    assert "importo" not in json.loads(scenario_to_json(sc, base))["scenario"]["finanziamenti"][0]
    assert scenario_from_json(scenario_to_json(sc, base))[0].finanziamenti[0].importo is None


def test_contratti_del_progetto_sopravvivono_a_json_e_righe():
    """I parametri del contratto (da cui la pagina genera i pagamenti) non si perdono né
    nel file esportato né nel salvataggio su BigQuery; il calcolo non li usa."""
    sc, base = scenario_sintetico()
    p = replace(sc.progetti[0], contratti=[CONTRATTO_AMCN])
    sc = replace(sc, progetti=[p])
    raw = scenario_to_json(sc, base, nome="t")
    sc2, _, _ = scenario_from_json(raw)
    assert sc2.progetti[0].contratti == [CONTRATTO_AMCN]
    ((sc3, _, _),) = scenario_da_righe(*righe_p(raw, "rid", datetime(2026, 10, 29), "stefano"))
    assert sc3.progetti[0].contratti == [CONTRATTO_AMCN]
    assert to_dict(calcola(inp_minimo(sc3))) == to_dict(calcola(inp_minimo(scenario_sintetico()[0])))


def test_sostituzione_sopravvive_al_documento_e_alle_tabelle_p():
    """«sostituzione» è la seconda origine legale di una manuale: resta tale nel JSON della pagina
    e nelle righe p_*; ogni altra origine torna «manuale» come prima."""
    sc, base = scenario_sintetico()
    sc = replace(
        sc,
        manuali=[
            Riga("ORTI", "USCITE_TASSE", "2026-11", 7_000_000, "U", "sostituzione"),
            Riga("ORTI", "x", "2026-12", 123, "U", "manuale"),
            Riga("ORTI", "y", "2026-12", 5, "U", "pf"),
        ],
    )
    doc = scenario_to_json(sc, base, "t")
    sc_doc, _, _ = scenario_from_json(doc)
    assert sorted((r.voce_id, r.origine) for r in sc_doc.manuali) == [
        ("USCITE_TASSE", "sostituzione"), ("x", "manuale"), ("y", "manuale"),
    ]
    rows = _righe(sc, base)
    assert {r["origine"] for r in rows[1] if r["voce_id"] == "USCITE_TASSE"} == {"sostituzione"}
    ((sc2, _, _),) = scenario_da_righe(*rows)
    assert sorted((r.voce_id, r.origine, r.importo) for r in sc2.manuali) == [
        ("USCITE_TASSE", "sostituzione", 7_000_000), ("x", "manuale", 123), ("y", "manuale", 5),
    ]
