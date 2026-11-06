"""Cassa senza pagina (fase 1 della spec 2026-11-04): seme immutabile, tracciabilità,
reversibilità, parità con il motore JS della pagina. Dati sintetici, nessun importo vero."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.test_build_cassa_artifact import (
    MESI_PF,
    _scenario_base,
    esegui_node_fn,
    snapshot_sintetico,
)
from verticals.condges import cassa_cli as cc
from verticals.condges.build_cassa_artifact import build_payload, render_html
from verticals.condges.cassa_scenario import scenario_id, scenario_to_json


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "stato"
    h.mkdir()
    (h / "latest.json").write_text(json.dumps(snapshot_sintetico()), encoding="utf-8")
    sc, base = _scenario_base()
    seme = json.loads(scenario_to_json(sc, base, nome="Scenario"))
    seme["scenari_ritirati"] = ["Vecchio"]
    (h / "base_scenario.json").write_text(json.dumps(seme, indent=1), encoding="utf-8")
    return h


def _tutti_i_file(h: Path) -> dict[str, str]:
    return {str(p.relative_to(h)): _md5(p) for p in sorted(h.rglob("*")) if p.is_file()}


# ── seme immutabile ──


def test_simula_confronta_variante_scenari_non_toccano_il_seme(home):
    prima = _md5(home / "base_scenario.json")
    payload = cc.payload_locale(home)
    seme = cc.risolvi("seme", home)
    cc.simula(payload, seme, home)
    cc.simula(payload, seme, home, vista="pf")
    cc.dettaglio_mese(payload, seme, MESI_PF[1])
    cc.variante("prova", seme, ["spegni P1"], payload, home)
    cc.confronta(payload, seme, cc.risolvi("prova", home), home)
    cc.elenco(home)
    assert _md5(home / "base_scenario.json") == prima


def test_promuovi_senza_autorizzazione_non_tocca_niente(home):
    payload = cc.payload_locale(home)
    cc.variante("prova", cc.risolvi("seme", home), ["spegni P1"], payload, home)
    prima = _tutti_i_file(home)
    for vuota in (None, "", "   "):
        with pytest.raises(cc.ErroreCassa, match="autorizzato-da"):
            cc.promuovi(cc.risolvi("prova", home), vuota, home)
    assert _tutti_i_file(home) == prima


def test_promuovi_lascia_la_copia_e_la_traccia(home):
    payload = cc.payload_locale(home)
    vecchio = (home / "base_scenario.json").read_bytes()
    cc.variante("prova", cc.risolvi("seme", home), ["spegni P1"], payload, home)
    var = cc.risolvi("prova", home)
    copia = cc.promuovi(var, "Stefano, 04/11, chat", home)
    assert copia.read_bytes() == vecchio
    nuovo = json.loads((home / "base_scenario.json").read_text())
    assert nuovo["provenienza"]["autorizzato_da"] == "Stefano, 04/11, chat"
    assert nuovo["provenienza"]["id_promosso"] == scenario_id(var.raw)
    assert nuovo["provenienza"]["seme_precedente"] == copia.name
    # Le chiavi del solo seme passano al seme nuovo: i ritirati non tornano nel menu.
    assert nuovo["scenari_ritirati"] == ["Vecchio"]
    assert nuovo["scenario"] == var.doc["scenario"]
    with pytest.raises(cc.ErroreCassa, match="già il seme"):
        cc.promuovi(cc.risolvi("seme", home), "Stefano", home)


# ── tracciabilità e reversibilità ──


def test_la_variante_dichiara_il_padre_e_si_ricalcola_da_lui(home):
    payload = cc.payload_locale(home)
    seme = cc.risolvi("seme", home)
    mods = cc.modifiche_da_argomenti(
        canone="12x1000@2027-01",
        spegni=["P1"],
        ipotesi=["prova: decorrenza da verificare"],
    )
    dest = cc.variante("prova", seme, mods, payload, home)
    doc = json.loads(dest.read_text())
    prov = doc["provenienza"]
    assert prov["origine"] == "variante" and prov["derivato_da"] == "seme"
    assert prov["id_padre"] == scenario_id(seme.raw)
    assert prov["snapshot_data"] == payload["acquisito_il"]
    assert prov["modifiche"] == mods
    rifatto = cc.deriva(seme, "prova", prov["modifiche"])
    togli = ("salvato_il", "provenienza")
    assert {k: v for k, v in doc.items() if k not in togli} == {
        k: v for k, v in rifatto.items() if k not in togli
    }
    assert doc["scenario"]["canone"]["netto_per_anno"] == {"2027": 12 * 1000 * 100}
    assert doc["ipotesi"] == ["prova: decorrenza da verificare"]
    assert "scenari_ritirati" not in doc
    # La catena: una variante di una variante punta alla prima.
    figlia = cc.variante(
        "prova2", cc.risolvi("prova", home), ["canone: pf"], payload, home
    )
    assert json.loads(figlia.read_text())["provenienza"]["id_padre"] == scenario_id(
        dest.read_bytes()
    )


def test_variante_non_sovrascrive_e_sostituisci_conserva_la_precedente(home):
    payload = cc.payload_locale(home)
    seme = cc.risolvi("seme", home)
    dest = cc.variante("prova", seme, ["spegni P1"], payload, home)
    primo = dest.read_bytes()
    with pytest.raises(cc.ErroreCassa, match="esiste già"):
        cc.variante("prova", seme, ["accendi P1"], payload, home)
    assert dest.read_bytes() == primo
    cc.variante("prova", seme, ["accendi P1"], payload, home, sostituisci=True)
    vecchie = list((home / "scenari").glob("prova_prima_*.json"))
    assert len(vecchie) == 1 and vecchie[0].read_bytes() == primo
    assert [e["nome"] for e in cc.elenco(home)] == ["seme", "prova"]


@pytest.mark.parametrize(
    "mods,errore",
    [
        ([], "nessuna modifica"),
        (["accendi NON_C_E"], "non c'è"),
        (["canone: 12@2027-01"], "NxRATA"),
        (["boh"], "sconosciuta"),
    ],
)
def test_variante_rifiuta_modifiche_sbagliate(home, mods, errore):
    payload = cc.payload_locale(home)
    with pytest.raises(cc.ErroreCassa, match=errore):
        cc.variante("prova", cc.risolvi("seme", home), mods, payload, home)
    assert not (home / "scenari" / "prova.json").exists()


def test_nome_seme_riservato(home):
    with pytest.raises(cc.ErroreCassa, match="riservato"):
        cc.variante(
            "seme",
            cc.risolvi("seme", home),
            ["spegni P1"],
            cc.payload_locale(home),
            home,
        )


# ── provenienza a video ──


def test_file_dell_app_senza_provenienza_e_origine_app(home, tmp_path):
    sc, base = _scenario_base()
    f = tmp_path / "esportato.json"
    f.write_text(scenario_to_json(sc, base, nome="Dal browser"), encoding="utf-8")
    d = cc.risolvi(str(f), home)
    assert d.origine == "app"
    s = cc.simula(cc.payload_locale(home), d, home)
    testo = cc.testo_simula(s)
    assert "origine: app (salvato il" in testo and "IPOTESI" in testo
    seme = cc.testo_simula(
        cc.simula(cc.payload_locale(home), cc.risolvi("seme", home), home)
    )
    assert "origine: seme" in seme and "IPOTESI" not in seme


def test_confronta_rifiuta_basi_diverse(home, tmp_path):
    sc, base = _scenario_base()
    altra = {s: {**b, "raw_object_id": "altro"} for s, b in base.items()}
    f = tmp_path / "altra.json"
    f.write_text(scenario_to_json(sc, altra, nome="Altra"), encoding="utf-8")
    payload = cc.payload_locale(home)
    a, b = cc.risolvi("seme", home), cc.risolvi(str(f), home)
    with pytest.raises(cc.ErroreCassa, match="PF diversi"):
        cc.confronta(payload, a, b, home)
    c = cc.confronta(payload, a, b, home, base_diverse=True)
    assert c["base_diverse"] and not c["b"]["base_uguale"]


def test_confronta_su_orizzonte_comune(home, tmp_path):
    # Se uno solo dei due cita un mese oltre l'orizzonte, anche l'altro va calcolato fin lì:
    # altrimenti quei mesi escono con il saldo vuoto e non vengono confrontati.
    sc, base = _scenario_oltre_orizzonte()
    f = tmp_path / "oltre.json"
    f.write_text(scenario_to_json(sc, base, nome="Oltre"), encoding="utf-8")
    payload = cc.payload_locale(home)
    seme, oltre = cc.risolvi("seme", home), cc.risolvi(str(f), home)
    for a, b in ((seme, oltre), (oltre, seme)):
        c = cc.confronta(payload, a, b, home)
        assert c["righe"][-1]["mese"] == "2027-09"
        for r in c["righe"]:
            for s in cc.SOCIETA:
                assert r[s]["a"] is not None and r[s]["b"] is not None, (r["mese"], s)
                assert r[s]["diff"] is not None


def test_scenario_sconosciuto(home):
    with pytest.raises(cc.ErroreCassa, match="non trovato"):
        cc.risolvi("non-esiste", home)


def test_vista_pf_e_la_baseline_della_pagina(home):
    payload = cc.payload_locale(home)
    s = cc.simula(payload, cc.risolvi("seme", home), home, vista="pf")
    assert s["risultato"] == payload["baseline"]


# ── parità con la pagina ──


def _scenario_oltre_orizzonte():
    from dataclasses import replace

    sc, base = _scenario_base()
    p = sc.progetti[0]
    pag = replace(p.pagamenti[0], mesi={**p.pagamenti[0].mesi, "2027-09": 123_456})
    return replace(sc, progetti=[replace(p, pagamenti=[pag, *p.pagamenti[1:]])]), base


def test_parita_python_js_con_pf_corretto_e_orizzonte_allungato(home, tmp_path):
    (home / "pf_corretto.json").write_text(
        json.dumps(
            {
                "correzioni": [
                    {
                        "societa": "INTUR",
                        "voce_id": "USCITE_TASSE",
                        "mese": MESI_PF[1],
                        "importo_cent": 777_700,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sc, base = _scenario_oltre_orizzonte()
    f = tmp_path / "oltre.json"
    f.write_text(scenario_to_json(sc, base, nome="Oltre"), encoding="utf-8")
    payload = cc.payload_locale(home)
    assert any(c["applicata"] for c in payload["pf_correzioni"])
    d = cc.risolvi(str(f), home)
    py = cc.simula(payload, d, home)
    assert py["mesi"][-1] == "2027-09" and "2027-09" not in payload["mesi"]
    assert "pf_corretto.json" in py["intestazione"]["strati_locali"]
    (tmp_path / "scenario.json").write_text(d.raw.decode(), encoding="utf-8")
    # Come la pagina (`allunga` nel template): orizzonte fino all'ultimo mese citato, poi calcola.
    js = esegui_node_fn(
        tmp_path,
        render_html(payload),
        "(()=>{const sc=require('./scenario.json').scenario;"
        "const f=[...M.mesiCitati(sc)].sort().pop();"
        "if(f&&f>D.mesi[D.mesi.length-1]){const o=M.allungaOrizzonte(D.mesi,D.mesi_ipotetici,f);"
        "D.mesi=o.mesi;D.mesi_ipotetici=o.mesi_ipotetici;}"
        "return JSON.stringify(M.calcola(D,sc));})()",
    )
    assert json.loads(js) == py["risultato"]


def test_parita_python_js_vista_pf(home, tmp_path):
    payload = cc.payload_locale(home)
    py = cc.simula(payload, cc.risolvi("seme", home), home, vista="pf")
    js = esegui_node_fn(
        tmp_path,
        render_html(payload),
        "JSON.stringify(M.calcola(D,{nome:'solo PF',progetti:[],finanziamenti:[],manuali:[],canone:null,soglia:0}))",
    )
    assert json.loads(js) == py["risultato"]


def test_payload_da_stato_uguale_a_build_payload(home):
    # La riga di comando e la pagina usano lo stesso payload.
    from verticals.condges.cassa_scenario import carica_seme

    snap = json.loads((home / "latest.json").read_text())
    atteso = build_payload(
        snap,
        [],
        seme=carica_seme(home / "base_scenario.json"),
        seme_salvato_il=json.loads((home / "base_scenario.json").read_text())[
            "salvato_il"
        ],
        scenari_ritirati=["Vecchio"],
    )
    got = cc.payload_locale(home)
    togli = ("generato_il",)
    assert {k: v for k, v in got.items() if k not in togli} == {
        k: v for k, v in atteso.items() if k not in togli
    }


def test_dettaglio_mese_mostra_quello_che_il_motore_conta(home):
    # Un canone di scenario nel 2026 sostituisce le rate PF del 2026: il dettaglio non deve
    # mostrare la rata del PF come se contasse.
    payload = cc.payload_locale(home)
    cc.variante(
        "can26", cc.risolvi("seme", home), ["canone: 2x1000@2026-11"], payload, home
    )
    det = cc.dettaglio_mese(payload, cc.risolvi("can26", home), "2026-11")["ORTI"]
    assert {"voce_id": "Fitto Hotel (canone)", "importo": 244_000 * 100} in det[
        "sostituiti"
    ]
    assert [
        f["stato"] for f in det["intercompany"] if f["nome"].startswith("Fitto")
    ] == ["scenario"]
    assert det["uscite"]["canone"] == sum(
        f["importo"] for f in det["intercompany"] if f["nome"].startswith("Fitto")
    )
    pf = cc.dettaglio_mese(payload, cc.risolvi("can26", home), "2026-11", vista="pf")[
        "ORTI"
    ]
    assert pf["sostituiti"] == []


def test_la_modifica_canone_riscrive_solo_l_anno_che_nomina():
    # Un calendario stagionale (il calendario di un anno vince sulle rate, motore
    # `flussi_canone`) non va azzerato da `canone: NxRATA@YYYY-MM`: la modifica
    # riscrive l'anno che nomina (lì contano le rate) e lascia gli altri come sono.
    doc = {
        "scenario": {
            "canone": {
                "netto_per_anno": {"2026": 11_111_100, "2027": 22_222_200},
                "rate_n": 3,
                "da_mese": "2026-06",
                "calendario": {
                    "2026-06": 3_333_300,
                    "2026-09": 7_777_800,
                    "2027-04": 1_111_100,
                    "2027-08": 2_222_200,
                },
                "aliquota_iva": 10,
            }
        }
    }
    cc.applica(doc, "canone: 3x111111@2027-06")
    c = doc["scenario"]["canone"]
    assert c["netto_per_anno"] == {"2026": 11_111_100, "2027": 33_333_300}
    assert (c["rate_n"], c["da_mese"], c["aliquota_iva"]) == (3, "2027-06", 10)
    assert c["calendario"] == {"2026-06": 3_333_300, "2026-09": 7_777_800}


def _canone_a_rate_2027() -> dict:
    return {
        "scenario": {
            "canone": {
                "netto_per_anno": {"2026": 11_111_100, "2027": 33_333_300},
                "rate_n": 3,
                "da_mese": "2027-06",
                "calendario": {"2026-09": 11_111_100},
                "aliquota_iva": 22,
            }
        }
    }


def test_calendario_scrive_l_anno_nominato_e_il_motore_lo_usa():
    # Uno stagionale 2027 si raggiunge con una modifica dichiarata, non editando il JSON:
    # la somma dei mesi deve tornare col netto dell'anno; gli altri anni restano.
    from verticals.condges import cassa_motore as M
    from verticals.condges.cassa_scenario import _scaletta_from_dict

    doc = _canone_a_rate_2027()
    cc.applica(doc, "calendario: 2027 apr=111111,lug=111111,set=111111")
    c = doc["scenario"]["canone"]
    assert c["calendario"] == {
        "2026-09": 11_111_100,
        "2027-04": 11_111_100,
        "2027-07": 11_111_100,
        "2027-09": 11_111_100,
    }
    assert (c["netto_per_anno"], c["rate_n"], c["da_mese"]) == (
        {"2026": 11_111_100, "2027": 33_333_300},
        3,
        "2027-06",
    )
    mesi = [f"2027-{m:02d}" for m in range(1, 13)]
    flussi = M.flussi_canone(_scaletta_from_dict(c), mesi)
    assert {f.mese: f.importo for f in flussi} == {
        "2027-04": M.iva(11_111_100, 22),
        "2027-07": M.iva(11_111_100, 22),
        "2027-09": M.iva(11_111_100, 22),
    }


@pytest.mark.parametrize(
    "mod,errore",
    [
        ("calendario: 2027 apr=111111,lug=111111", r"222\.222,00.*333\.333,00"),
        ("calendario: 2028 gen=1", "2028"),
        ("calendario: 2027 xyz=1", "mese"),
        ("calendario: 2027", "AAAA"),
    ],
)
def test_calendario_rifiuta_quello_che_non_quadra(mod, errore):
    doc = _canone_a_rate_2027()
    with pytest.raises(cc.ErroreCassa, match=errore):
        cc.applica(doc, mod)
    assert doc == _canone_a_rate_2027()


def test_calendario_senza_canone_e_un_errore():
    with pytest.raises(cc.ErroreCassa, match="canone"):
        cc.applica({"scenario": {"canone": None}}, "calendario: 2027 gen=1")


def test_variante_con_calendario_finisce_in_provenienza(home):
    payload = cc.payload_locale(home)
    mods = [
        "canone: 3x111111@2027-06",
        "calendario: 2027 apr=111111,lug=111111,set=111111",
    ]
    dest = cc.variante("stag", cc.risolvi("seme", home), mods, payload, home)
    doc = json.loads(dest.read_text())
    assert doc["provenienza"]["modifiche"] == mods
    assert doc["scenario"]["canone"]["calendario"] == {
        "2027-04": 11_111_100,
        "2027-07": 11_111_100,
        "2027-09": 11_111_100,
    }
