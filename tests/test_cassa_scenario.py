import json
from datetime import date, datetime

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
