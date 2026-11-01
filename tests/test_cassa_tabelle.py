"""Tabelle piatte per Excel: dal payload della pagina ai CSV, senza passare da BigQuery."""

import csv
import json

import pytest

from tests.test_build_cassa_artifact import _scenario_base, snapshot_sintetico
from verticals.condges.build_cassa_artifact import build_payload, render_html
from verticals.condges.cassa_tabelle import (
    SCHEMA_TABELLE,
    _euro,
    confronto_con_la_pagina,
    formatta,
    payload_da_file,
    scrivi_csv,
    scrivi_json,
    tabelle,
)


@pytest.fixture()
def payload():
    return build_payload(snapshot_sintetico(), [])


def test_euro_segno_e_centesimi():
    assert [_euro(c) for c in (0, 5, -5, 100, -100, 131556112, -12273356, -1)] == [
        "0,00",
        "0,05",
        "-0,05",
        "1,00",
        "-1,00",
        "1315561,12",
        "-122733,56",
        "-0,01",
    ]


def test_la_percentuale_iva_non_e_un_importo():
    """`aliquota_iva` è 22, non 0,22 €: il riconoscimento per sottostringa sbagliava."""
    assert formatta(["aliquota_iva", "iva"], [22, 4400]) == ["22", "44,00"]


def test_ogni_tabella_ha_le_colonne_delle_sue_righe(payload):
    for nome, (colonne, righe) in tabelle(payload).items():
        for r in righe:
            assert len(r) == len(colonne), (
                f"{nome}: riga di {len(r)} su {len(colonne)} colonne"
            )


def test_i_saldi_portano_il_solo_pf_e_lo_scenario(payload_con_seme):
    payload = payload_con_seme
    colonne, righe = tabelle(payload)["saldi_mensili"]
    etichette = {r[0] for r in righe}
    assert "solo PF" in etichette and len(etichette) == 2
    i = colonne.index("saldo_finale")
    pf = {(r[1], r[2]): r[i] for r in righe if r[0] == "solo PF"}
    atteso = {(r["mese"], r["societa"]): r["fin"] for r in payload["baseline"]["righe"]}
    assert pf == atteso


def test_entrate_e_uscite_totali_sono_la_somma_delle_origini(payload):
    colonne, righe = tabelle(payload)["saldi_mensili"]
    for r in righe:
        for lato in ("entrate", "uscite"):
            parti = [
                r[colonne.index(c)]
                for c in colonne
                if c.startswith(f"{lato}_") and c != f"{lato}_totali"
            ]
            assert sum(parti) == r[colonne.index(f"{lato}_totali")]


def test_il_saldo_finale_e_iniziale_piu_entrate_meno_uscite(payload):
    colonne, righe = tabelle(payload)["saldi_mensili"]
    c = {
        n: colonne.index(n)
        for n in ("saldo_iniziale", "entrate_totali", "uscite_totali", "saldo_finale")
    }
    for r in righe:
        assert (
            r[c["saldo_iniziale"]] + r[c["entrate_totali"]] - r[c["uscite_totali"]]
            == r[c["saldo_finale"]]
        )


@pytest.fixture()
def payload_con_seme():
    """Payload col seme dentro: è il caso vero, la pagina parte sempre da uno scenario."""
    return build_payload(snapshot_sintetico(), [], seme=_scenario_base())


def test_nei_pagamenti_netto_piu_imposta_fa_il_lordo(payload_con_seme):
    colonne, righe = tabelle(payload_con_seme)["pagamenti"]
    n, i, l = (colonne.index(x) for x in ("netto", "iva", "lordo"))
    assert righe, "lo scenario del seme ha pagamenti"
    for r in righe:
        assert r[n] + r[i] == r[l]


def test_il_canone_dice_le_rate_del_contratto_che_il_pf_non_ha():
    """Contratto art. 3: 30/06, 30/09, 30/12. Se il PF ha solo giugno, le altre sono dichiarate."""
    snap = snapshot_sintetico()
    dichiarato = {
        "netto_annuo": 60000000,
        "aliquota_iva": 22,
        "calendario_contratto": {"06": 20000000, "09": 20000000, "12": 20000000},
        "contratto_fonte": "contratto 01/04/2025 art. 3",
        "fonte": "prova",
        "dichiarato_il": "2026-10-29",
    }
    p = build_payload(snap, [], canone_dichiarato=dichiarato)
    colonne, righe = tabelle(p)["canone_rate"]
    manca = colonne.index("rata_del_contratto_che_il_pf_non_ha")
    mese = colonne.index("mese")
    senza_pf = {r[mese] for r in righe if r[manca] == "sì"}
    assert senza_pf, "almeno una rata del contratto non è nel PF"
    assert all(m[5:7] in ("06", "09", "12") for m in senza_pf)
    netto_c, lordo_c = (
        colonne.index("netto_da_contratto"),
        colonne.index("lordo_da_contratto"),
    )
    for r in righe:
        if r[netto_c]:
            assert r[lordo_c] == r[netto_c] * 122 // 100


def test_i_limiti_della_pagina_diventano_righe(payload):
    _colonne, righe = tabelle(payload)["limiti"]
    assert [r[1] for r in righe] == payload["limiti"]
    assert [r[0] for r in righe] == list(range(1, len(righe) + 1))


def test_il_payload_si_legge_dal_json_e_dalla_pagina(tmp_path, payload):
    pj = tmp_path / "dati.json"
    pj.write_text(json.dumps(payload), encoding="utf-8")
    ph = tmp_path / "pagina.html"
    ph.write_text(render_html(payload), encoding="utf-8")
    assert payload_da_file(pj)["mesi"] == payload["mesi"]
    assert payload_da_file(ph)["mesi"] == payload["mesi"]
    with pytest.raises(ValueError):
        (tmp_path / "x.html").write_text("<html>niente dati</html>", encoding="utf-8")
        payload_da_file(tmp_path / "x.html")


def test_i_csv_si_rileggono_con_il_punto_e_virgola(tmp_path, payload):
    scritti = scrivi_csv(tabelle(payload), tmp_path)
    assert {p.name for p in scritti} >= {
        "saldi_mensili.csv",
        "limiti.csv",
        "versioni.csv",
    }
    testo = (tmp_path / "saldi_mensili.csv").read_text(encoding="utf-8-sig")
    assert testo.splitlines()[0].startswith("scenario;mese;societa")
    with (tmp_path / "saldi_mensili.csv").open(encoding="utf-8-sig", newline="") as fh:
        righe = list(csv.DictReader(fh, delimiter=";"))
    assert (
        righe
        and "," in righe[0]["saldo_finale"]
        and "." not in righe[0]["saldo_finale"]
    )


def test_il_confronto_con_la_pagina_e_vuoto_quando_i_numeri_coincidono(payload):
    assert confronto_con_la_pagina(payload) == []


def test_il_confronto_dice_quale_mese_divergerebbe(payload):
    storto = json.loads(json.dumps(payload))
    storto["baseline"]["righe"][0]["fin"] += 1
    fuori = confronto_con_la_pagina(storto)
    assert len(fuori) == 1 and "Python" in fuori[0]


def test_senza_baseline_il_confronto_lo_dice(payload):
    senza = {k: v for k, v in payload.items() if k != "baseline"}
    assert confronto_con_la_pagina(senza) == [
        "il payload non porta il baseline: confronto non fatto"
    ]


def test_i_progetti_portano_il_totale_dei_loro_pagamenti(payload_con_seme):
    t = tabelle(payload_con_seme)
    cp, progetti = t["progetti"]
    cg, pagamenti = t["pagamenti"]
    tot = {}
    for r in pagamenti:
        tot[r[cg.index("progetto_id")]] = (
            tot.get(r[cg.index("progetto_id")], 0) + r[cg.index("netto")]
        )
    for r in progetti:
        assert r[cp.index("totale_netto")] == tot.get(r[cp.index("progetto_id")], 0)


def test_i_json_portano_record_con_centesimi_interi_e_un_manifesto_che_li_elenca(
    tmp_path, payload_con_seme
):
    import hashlib

    tab = tabelle(payload_con_seme)
    scritti = scrivi_json(tab, tmp_path, payload_con_seme, sorgente="prova.json")
    nomi = {p.name for p in scritti}
    assert (
        "manifest.json" in nomi
        and "saldi_mensili.json" in nomi
        and "pagamenti.json" in nomi
    )
    saldi = json.loads((tmp_path / "saldi_mensili.json").read_text(encoding="utf-8"))
    assert saldi["schema"] == SCHEMA_TABELLE and saldi["tabella"] == "saldi_mensili"
    assert saldi["unita"]["importi"] == "centesimi interi"
    riga = saldi["righe"][0]
    assert set(riga) == set(saldi["colonne"])
    assert isinstance(riga["saldo_finale"], int), (
        "centesimi interi, non euro formattati"
    )
    assert (
        riga["saldo_iniziale"] + riga["entrate_totali"] - riga["uscite_totali"]
        == riga["saldo_finale"]
    )
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert man["schema"] == SCHEMA_TABELLE and man["sorgente"] == "prova.json"
    assert man["scenario"] == payload_con_seme["seme"]["nome"]
    assert {v["tabella"] for v in man["tabelle"]} == set(tab)
    for v in man["tabelle"]:
        testo = (tmp_path / v["file"]).read_text(encoding="utf-8")
        assert hashlib.sha256(testo.encode("utf-8")).hexdigest() == v["sha256"], v[
            "file"
        ]
        assert v["righe"] == len(json.loads(testo)["righe"])
    assert "riservati" in man["nota"].lower()


def test_la_tabella_fornitori_aggrega_i_pagamenti_per_fornitore(payload_con_seme):
    tab = tabelle(payload_con_seme)
    colonne, righe = tab["fornitori"]
    assert colonne[:6] == [
        "fornitore_id",
        "nome",
        "codice_esolver",
        "societa",
        "n_pagamenti",
        "totale_lordo",
    ]
    per_id = {r[0]: r for r in righe}
    # lo scenario sintetico ha due pagamenti con fornitore F0 e F1, sei mesi ciascuno
    assert set(per_id) >= {"F0", "F1"}
    assert (
        per_id["F0"][4] == 1
        and per_id["F0"][5] > 0
        and per_id["F0"][6] <= per_id["F0"][7]
    )
    # totale_lordo è denaro: in CSV diventa euro con la virgola
    assert (
        formatta(colonne, per_id["F0"])[5].endswith(",00")
        or "," in formatta(colonne, per_id["F0"])[5]
    )


def test_i_patti_abituali_si_leggono_in_una_riga():
    from verticals.condges.cassa_tabelle import _riassunto_patti

    sal = {
        "modo": "sal",
        "aliquota_iva": 0,
        "anticipo_pct": 15,
        "anticipo_dopo": 0,
        "sal_modo": "n",
        "sal_n": 5,
        "sal_passo": 1,
        "sal_dopo": 1,
        "ritenuta_pct": 10,
        "svincolo_dopo": 7,
    }
    assert (
        _riassunto_patti(sal)
        == "anticipo 15% all'inizio · 5 SAL ogni mese · da 1 mese dopo l'inizio · ritenuta 10% svincolata 7 mesi dopo l'inizio · IVA 0%"
    )
    perc = {
        "modo": "percentuali",
        "aliquota_iva": 22,
        "quote": [{"pct": 40, "dopo": 0}, {"pct": 60, "dopo": 2}],
    }
    assert _riassunto_patti(perc) == "40% all'inizio · 60% 2 mesi dopo l'inizio"
    assert _riassunto_patti(None) == ""


def test_la_tabella_pf_correzioni_porta_le_voci_dichiarate():
    from verticals.condges.cassa_tabelle import DENARO

    p = build_payload(
        snapshot_sintetico(),
        [],
        pf_corretto={
            "correzioni": [
                {
                    "societa": "INTUR",
                    "voce_id": "USCITE_TASSE",
                    "mese": "2026-11",
                    "importo_cent": 3_500_000,
                    "dichiarato_da": "Rosa",
                    "dichiarato_il": "2026-10-31",
                    "fonte": "f",
                }
            ]
        },
    )
    colonne, righe = tabelle(p)["pf_correzioni"]
    assert (
        colonne[:5] == ["societa", "voce_id", "mese", "nel_pf", "corretto"]
        and {"nel_pf", "corretto"} <= DENARO
    )
    assert righe == [
        [
            "INTUR",
            "USCITE_TASSE",
            "2026-11",
            1_000_000,
            3_500_000,
            "sì",
            "Rosa",
            "2026-10-31",
            "f",
        ]
    ]
