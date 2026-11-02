import json
import re
import shutil
import subprocess
from dataclasses import asdict, replace
from datetime import date, datetime
from pathlib import Path

import pytest

from tests.test_cassa_scenario import scenario_sintetico
from verticals.condges.build_cassa_artifact import (
    KV_DATA_KEY,
    KV_KEY,
    PUSH_ENV_VARS,
    applica_pf_corretto,
    build_payload,
    input_da_dict,
    input_da_snapshot,
    push_to_kv,
    render_html,
    snapshot_da_fonti,
)
from verticals.condges.cassa_motore import (
    Ancora,
    Conto,
    Fatto,
    Finanziamento,
    Flusso,
    Input,
    Pagamento,
    Progetto,
    Riga,
    Scenario,
    calcola,
    to_cent,
    to_dict,
)
from verticals.condges.cassa_scenario import SCHEMA, scenario_to_json

NODE = shutil.which("node") or (
    "/opt/homebrew/bin/node" if Path("/opt/homebrew/bin/node").exists() else None
)

MESI_PF = ["2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03"]
CODA = ["2027-04", "2027-05", "2027-06"]
MESI_9 = MESI_PF + CODA


def _ancore():
    return {
        "ORTI": Ancora(
            "ORTI",
            date(2026, 9, 30),
            to_cent(500_000),
            False,
            {
                "MPS": Conto(
                    to_cent(300_000), True, "quadra con movimenti dal 2026-08-31"
                ),
                "INTESA": Conto(
                    to_cent(200_000), False, "movimenti fino al 2026-09-28"
                ),
            },
        ),
        "INTUR": Ancora(
            "INTUR",
            date(2026, 9, 30),
            to_cent(100_000),
            True,
            {
                "SELLA": Conto(
                    to_cent(100_000), True, "quadra con movimenti dal 2026-08-31"
                )
            },
        ),
    }


def _pf():
    righe = [
        Riga("ORTI", "USCITE_SALARI", m, to_cent(100_000), "U", "pf")
        for m in MESI_PF[:3]
    ]
    righe += [
        Riga("ORTI", "ENTRATE_HOTEL", m, to_cent(200_000), "E", "pf")
        for m in MESI_PF[3:]
    ]
    righe += [
        Riga("INTUR", "USCITE_TASSE", m, to_cent(10_000), "U", "pf") for m in MESI_PF
    ]
    righe.append(
        Riga(
            "INTUR",
            "ENTRATE_FINANZIAMENTI",
            "2026-11",
            to_cent(1_000),
            "E",
            "finanziamento",
        )
    )
    return righe


def _flussi():
    return [
        Flusso(
            "Fitto Hotel (canone)",
            "ORTI",
            "INTUR",
            "2026-10",
            to_cent(50_000),
            "una_gamba",
        ),
        Flusso(
            "Fitto Hotel (canone)", "ORTI", "INTUR", "2026-11", to_cent(244_000), "pf"
        ),
        Flusso(
            "Godimento beni di terzi", "ORTI", "TERZI", "2026-10", to_cent(50_000), "pf"
        ),
    ]


def _fatti():
    return [
        Fatto("ORTI", "P1", "F0", "2026-10", to_cent(3_000), "ev-1"),
        Fatto("INTUR", "PX", None, "2026-11", to_cent(1), "ev-2"),
    ]


BASE = {
    "ORTI": {
        "file_sorgente": "ORTI_PF_2026-09.xlsx",
        "raw_object_id": "r1",
        "data_caricamento": "2026-10-29",
    },
    "INTUR": {
        "file_sorgente": "INTUR_PF_2026-09.xlsx",
        "raw_object_id": "r2",
        "data_caricamento": "2026-10-29",
    },
}


def snapshot_sintetico():
    return snapshot_da_fonti(
        ancore=_ancore(),
        pf=_pf(),
        intercompany=_flussi(),
        base=BASE,
        mesi=MESI_9,
        mesi_ipotetici=frozenset(CODA),
        fatti=_fatti(),
        scenari=[],
        acquisito_il=datetime(2026, 10, 29, 12, 0),
    )


def _scenario_base():
    sc, base = scenario_sintetico()
    return sc, {s: dict(BASE[s]) for s in BASE}


def _estrai(html: str) -> tuple[str, str]:
    dati = re.search(
        r'<script type="application/json" id="dati">(.*?)</script>', html, re.S
    ).group(1)
    motore = re.search(r'<script id="motore">(.*?)</script>', html, re.S).group(1)
    return dati.replace("<\\/", "</"), motore


def esegui_node_fn(tmp_path: Path, html: str, espressione: str) -> str:
    """Esegue `espressione` con M = MOTORE, D = payload, MESI_9 = D.mesi; stampa il risultato."""
    if NODE is None:
        pytest.skip("node non installato")
    dati, motore = _estrai(html)
    (tmp_path / "motore.js").write_text(motore, encoding="utf-8")
    formato = re.search(r'<script id="formato">(.*?)</script>', html, re.S)
    if formato:
        (tmp_path / "formato.js").write_text(formato.group(1), encoding="utf-8")
    (tmp_path / "dati.json").write_text(dati, encoding="utf-8")
    (tmp_path / "run.js").write_text(
        "const M=require('./motore.js'),D=require('./dati.json'),MESI_9=D.mesi;"
        f"console.log({espressione});",
        encoding="utf-8",
    )
    r = subprocess.run([NODE, "run.js"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def esegui_node(tmp_path: Path, html: str, payload: dict, scenario_json: str) -> dict:
    (tmp_path / "scenario.json").write_text(scenario_json, encoding="utf-8")
    out = esegui_node_fn(
        tmp_path,
        html,
        "JSON.stringify(M.calcola(D, require('./scenario.json').scenario))",
    )
    return json.loads(out)


# ── payload ──


def test_payload_porta_limiti_versioni_e_interi():
    p = build_payload(snapshot_sintetico(), [])
    assert "dichiarat" in " ".join(p["limiti"]).lower()
    assert p["base"]["ORTI"]["file_sorgente"] == "ORTI_PF_2026-09.xlsx"
    assert p["baseline"]["minimi"]["ORTI"]["mese"] == "2026-12"
    assert all(isinstance(r["fin"], int) for r in p["baseline"]["righe"])
    assert p["mesi_ipotetici"] == CODA and p["mesi"] == MESI_9
    assert p["ancore"]["ORTI"]["attestato"] is False
    assert (
        p["ancore"]["ORTI"]["conti"]["INTESA"]["motivo"]
        == "movimenti fino al 2026-09-28"
    )
    assert p["seme"]["schema"] == SCHEMA and p["baseline"]["non_riconciliati"]


def test_limiti_dicono_mesi_senza_pf_e_fatti_non_riconciliati():
    testo = " ".join(build_payload(snapshot_sintetico(), [])["limiti"]).lower()
    assert "da apr 27 a giu 27 il pf non c'è" in testo
    assert "nessun saldo" in testo and "quanto le leve dello scenario spostano la cassa" in testo
    assert "omologo" not in testo
    assert "non trovano un pagamento di progetto" in testo and "iva" in testo


def test_limiti_saldi_una_frase_per_societa_in_parole_semplici():
    lim = build_payload(snapshot_sintetico(), [])["limiti"]
    orti = [x for x in lim if x.startswith("ORTI ·")]
    assert orti == [
        "ORTI · saldi di fine mese al 30/09/2026. Verificati con i movimenti: MPS. "
        "Da verificare: Intesa (movimenti caricati fino al 28/09/2026)."
    ]
    # INTUR ha tutti i conti verificati: nessuna frase
    assert not [x for x in lim if x.startswith("INTUR ·")]


def test_limiti_saldi_motivi_tradotti():
    snap = snapshot_sintetico()
    snap["ancore"]["ORTI"]["conti"] = {
        "MPS_KROSS": {"saldo": 1, "attestato": False, "motivo": "scostamento 1.549,23"},
        "UNICREDIT": {"saldo": 1, "attestato": False, "motivo": "nessun movimento dopo il 2026-08-31"},
        "SELLA": {"saldo": 1, "attestato": False, "motivo": "nessuna chiusura precedente"},
        "INTESA": {"saldo": 1, "attestato": False, "motivo": "nessuna chiusura al 2026-09-30 (ultima 2026-08-31)"},
    }
    (orti,) = [x for x in build_payload(snap, [])["limiti"] if x.startswith("ORTI ·")]
    assert "Nessuno verificato con i movimenti." in orti
    assert "MPS Kross (la somma dei movimenti non torna di 1.549,23 €)" in orti
    assert "Unicredit (nessun movimento caricato dopo il 31/08/2026)" in orti
    assert "Sella (manca il saldo del mese prima)" in orti
    assert "Intesa (nessun saldo al 30/09/2026, l'ultimo è del 31/08/2026)" in orti


def test_payload_toglie_righe_pf_e_flussi_dalla_coda():
    """Snapshot vecchi portavano la coda copiata dal mese omologo: il payload la
    scarta, e la baseline nei mesi senza PF resta piatta (nessun saldo inventato)."""
    snap = snapshot_sintetico()
    snap["pf"].append(
        {"societa": "ORTI", "voce_id": "USCITE_SALARI", "mese": "2027-05",
         "importo": to_cent(1000), "direzione": "U", "origine": "pf"}
    )
    snap["intercompany"].append(
        {"nome": "Fitto Hotel (canone)", "da": "ORTI", "a": "INTUR", "mese": "2027-06",
         "importo": to_cent(244_000), "stato": "pf"}
    )
    p = build_payload(snap, [])
    assert all(r["mese"] not in CODA for r in p["pf"])
    assert all(f["mese"] not in CODA for f in p["intercompany"])
    orti = [r for r in p["baseline"]["righe"] if r["societa"] == "ORTI"]
    fin_pf = next(r["fin"] for r in orti if r["mese"] == MESI_PF[-1])
    assert all(r["fin"] == fin_pf for r in orti if r["mese"] in CODA)
    assert snapshot_sintetico()["pf"] == snap["pf"][:-1]  # l'input non è mutato


def test_salvato_con_il_nome_del_seme_resta_fuori_dal_menu():
    sc, base = _scenario_base()
    meta = {"nome": sc.nome, "salvato_il": "2026-10-29T13:47"}
    p = build_payload(snapshot_sintetico(), [(sc, base, meta)], seme=(sc, base))
    assert p["scenari"] == []
    assert p["scenari_sostituiti"] == [
        {"nome": sc.nome, "salvato_il": "2026-10-29T13:47", "motivo": "stesso nome del seme"}
    ]
    # senza seme (o con nome diverso) il salvato resta nel menu
    assert build_payload(snapshot_sintetico(), [(sc, base, meta)])["scenari"][0]["nome"] == sc.nome
    altro = {"nome": "altro", "salvato_il": "2026-10-29T13:47"}
    p2 = build_payload(snapshot_sintetico(), [(sc, base, altro)], seme=(sc, base))
    assert [s["nome"] for s in p2["scenari"]] == ["altro"] and p2["scenari_sostituiti"] == []


def test_il_seme_ritira_dei_nomi_dal_menu_senza_toccare_bigquery():
    sc, base = _scenario_base()
    vecchi = [
        (sc, base, {"nome": "Base 29/10", "salvato_il": "2026-10-29T13:47"}),
        (sc, base, {"nome": "Base 30/10", "salvato_il": "2026-10-30T16:39"}),
        (sc, base, {"nome": "Base 30/10", "salvato_il": "2026-10-30T19:00"}),
        (sc, base, {"nome": "Fotografia 31/10", "salvato_il": "2026-10-31T13:30"}),
    ]
    p = build_payload(
        snapshot_sintetico(), vecchi, seme=(sc, base), scenari_ritirati=["Base 29/10", "Base 30/10"]
    )
    # nel menu resta solo chi non è ritirato; i ritirati sono dichiarati, con il motivo e l'ora
    assert [s["nome"] for s in p["scenari"]] == ["Fotografia 31/10"]
    assert [(s["nome"], s["motivo"]) for s in p["scenari_sostituiti"]] == [
        ("Base 29/10", "ritirato nel seme"),
        ("Base 30/10", "ritirato nel seme"),
        ("Base 30/10", "ritirato nel seme"),
    ]
    assert [s["salvato_il"] for s in p["scenari_sostituiti"]][1:] == ["2026-10-30T16:39", "2026-10-30T19:00"]
    # senza la lista nel seme, nulla cambia rispetto a prima
    assert len(build_payload(snapshot_sintetico(), vecchi, seme=(sc, base))["scenari"]) == 4


def test_canone_riferimento_dichiarato_o_dalle_rate_pf():
    # senza file dichiarato: l'annuo è la somma delle rate PF nell'orizzonte, e si dice
    p = build_payload(snapshot_sintetico(), [])
    c = p["canone_rif"]
    assert c["dichiarato"] is False and c["netto_annuo"] == to_cent(200_000)
    assert c["rate_orizzonte"] == [{"mese": "2026-11", "lordo": to_cent(244_000), "netto": to_cent(200_000)}]
    assert "NON è l'annuo" in " ".join(p["limiti"])
    # con il file dichiarato: annuo 600.000, rate PF note, fonte; le rate nell'orizzonte restano dal PF
    dich = {"netto_annuo": to_cent(600_000), "aliquota_iva": 22, "rate_pf": {"2026-09": to_cent(244_000), "2026-11": to_cent(244_000)}, "fonte": "Stefano 29/10", "dichiarato_il": "2026-10-29"}
    p2 = build_payload(snapshot_sintetico(), [], canone_dichiarato=dich)
    c2 = p2["canone_rif"]
    assert c2["dichiarato"] is True and c2["netto_annuo"] == to_cent(600_000) and c2["lordo_annuo"] == to_cent(732_000)
    assert c2["netto_pf_orizzonte"] == to_cent(200_000) and c2["rate_pf"]["2026-09"] == to_cent(244_000)
    testo = " ".join(p2["limiti"])
    assert "600.000,00 € netto l'anno" in testo and "set 26" in testo
    assert c2["contratto"] is None
    # con il calendario del contratto: le rate contrattuali che il PF non ha diventano limiti
    dich["calendario_contratto"] = {"06": to_cent(200_000), "09": to_cent(200_000), "12": to_cent(200_000)}
    dich["contratto_fonte"] = "art. 3"
    p3 = build_payload(snapshot_sintetico(), [], canone_dichiarato=dich)
    assert p3["canone_rif"]["contratto"] == {"rate_mese": {"06": to_cent(200_000), "09": to_cent(200_000), "12": to_cent(200_000)}, "fonte": "art. 3", "anni_pagati": {}}
    lim = [x for x in p3["limiti"] if x.startswith("Canone, contratto art. 3")]
    # orizzonte PF ott 26–mar 27: il contratto ha dic 26; il PF sintetico ha 244.000 a nov 26 e niente a dic
    assert len(lim) == 1 and "30/12/2026" in lim[0] and "244.000,00 €" in lim[0] and "nel PF non c'è" in lim[0]
    # anno già pagato in banca: le rate del contratto di quell'anno non sono dovute e non sono limiti
    dich["anni_pagati"] = {"2026": "3 × 244.000 il 13/07, 31/07, 21/09/2026"}
    p4 = build_payload(snapshot_sintetico(), [], canone_dichiarato=dich)
    assert p4["canone_rif"]["contratto"]["anni_pagati"] == {"2026": "3 × 244.000 il 13/07, 31/07, 21/09/2026"}
    assert not [x for x in p4["limiti"] if x.startswith("Canone, contratto art. 3")]
    assert "Canone 2026 già pagato: 3 × 244.000 il 13/07, 31/07, 21/09/2026." in p4["limiti"]
    # IVA scorporata half-up anche con lordo non divisibile
    snap = snapshot_sintetico()
    snap["intercompany"].append({"nome": "Fitto Hotel (canone)", "da": "ORTI", "a": "INTUR", "mese": "2026-12", "importo": 1, "stato": "pf"})
    c3 = build_payload(snap, [])["canone_rif"]
    assert c3["rate_orizzonte"][-1] == {"mese": "2026-12", "lordo": 1, "netto": (1 * 100 + 61) // 122}


def test_scenario_salvato_con_base_diversa_marcato():
    sc, base = _scenario_base()
    base["ORTI"]["raw_object_id"] = "altro"
    p = build_payload(
        snapshot_sintetico(),
        [(sc, base, {"nome": "x", "salvato_il": "2026-10-29T10:00"})],
    )
    assert p["scenari"][0]["compatibile"] is False and p["scenari"][0]["nome"] == "x"
    sc2, base2 = _scenario_base()
    p2 = build_payload(snapshot_sintetico(), [(sc2, base2, {"nome": "y"})])
    assert p2["scenari"][0]["compatibile"] is True


def test_seme_porta_i_limiti_dei_finanziamenti():
    sc, base = _scenario_base()
    mcc = Finanziamento(
        "MCC",
        "MCC 550.000",
        "INTUR",
        {"2026-11": to_cent(550_000)},
        {},
        "da verificare",
    )
    sc = replace(sc, finanziamenti=[mcc])
    p = build_payload(snapshot_sintetico(), [], seme=(sc, base))
    testo = " ".join(p["limiti"]).lower()
    assert "mcc 550.000: da verificare, non ancora deliberato; senza rate di rimborso" in testo
    assert "le entrate da finanziamenti del pf di quella società non contano" in testo
    assert p["seme"]["scenario"]["nome"] == "s" and p["seme"]["compatibile"] is True
    # senza seme: scenario vuoto, nessuna frase sui finanziamenti
    senza = " ".join(build_payload(snapshot_sintetico(), [])["limiti"]).lower()
    assert "finanziament" not in senza


def test_snapshot_andata_e_ritorno():
    sc, _ = _scenario_base()
    snap = snapshot_sintetico()
    inp = input_da_snapshot(json.loads(json.dumps(snap)), sc)
    assert inp == Input(
        MESI_9, frozenset(CODA), _ancore(), _pf(), _flussi(), _fatti(), sc
    )


def test_input_da_dict_con_scenario_dentro():
    sc, base = _scenario_base()
    d = snapshot_sintetico()
    d["scenario"] = json.loads(scenario_to_json(sc, base))
    assert input_da_dict(d) == input_da_snapshot(d, sc)


# ── html ──


def test_render_html_incapsula_dati_e_motore():
    html = render_html(build_payload(snapshot_sintetico(), []))
    assert "__DATA__" not in html and '<script id="motore">' in html
    assert "Salva scenario (.json)" in html and "prefers-color-scheme" in html
    assert "non conta finché il progetto è spento" in html
    assert "attestato" in html and "dichiarato" in html


def test_badge_dei_saldi_dice_cosa_vuol_dire():
    """Il chip dice CHE COS'È il saldo (una delle quattro parole §A); il perché sta nel title (brief UI §B)."""
    html = render_html(build_payload(snapshot_sintetico(), []))
    assert "chipStato(statoAncora(a)," in html and "chipStato(statoAncora(c), c.motivo)" in html
    assert "quadra con i movimenti in banca" in html  # la provenienza, nel title, non nell'etichetta
    assert '"attestata" : "dichiarata"' not in html and '"quadra coi movimenti" : "dichiarata"' not in html
    assert "solo dichiarato" not in html and '"quadra con i movimenti"' not in html


# ── parità JS/Python: interi, nessun round ──


def test_js_uguale_a_python(tmp_path):
    snap = snapshot_sintetico()
    p = build_payload(snap, [])
    sc, _ = _scenario_base()
    out = esegui_node(tmp_path, render_html(p), p, scenario_to_json(sc, p["base"]))
    assert out == to_dict(calcola(input_da_snapshot(snap, sc)))


def test_js_residuo_uguale_a_python(tmp_path):
    snap = snapshot_sintetico()
    p = build_payload(snap, [])
    pag = Pagamento(
        "da assegnare",
        {"2026-10": to_cent(1_000), "2026-11": to_cent(1_000)},
        0,
        residuo=True,
    )
    sc = Scenario("r", [Progetto("p", "P", "INTUR", True, "ipotesi", [pag])], [])
    fatti = [Fatto("INTUR", "p", "AMCN", "2026-10", to_cent(1_500), "ev")]
    atteso = calcola(replace(input_da_snapshot(snap, sc), fatti=fatti))
    assert atteso.non_riconciliati == []
    (tmp_path / "scenario.json").write_text(
        scenario_to_json(sc, p["base"]), encoding="utf-8"
    )
    (tmp_path / "fatti.json").write_text(
        json.dumps([asdict(f) for f in fatti]), encoding="utf-8"
    )
    out = esegui_node_fn(
        tmp_path,
        render_html(p),
        "JSON.stringify(M.calcola({...D, fatti: require('./fatti.json')}, "
        "require('./scenario.json').scenario))",
    )
    js = json.loads(out)
    assert js["non_riconciliati"] == []
    assert js["righe"] == to_dict(atteso)["righe"]


def test_js_baseline_uguale_a_python(tmp_path):
    p = build_payload(snapshot_sintetico(), [])
    vuoto = Scenario("v", [], [])
    out = esegui_node(tmp_path, render_html(p), p, scenario_to_json(vuoto, p["base"]))
    assert out == p["baseline"]


def test_js_arrotondamenti(tmp_path):
    js = esegui_node_fn(
        tmp_path,
        render_html(build_payload(snapshot_sintetico(), [])),
        "JSON.stringify([M.iva(1001,22), M.iva(5,10), "
        "M.distribuisci(10000000,'2026-10',3,['2026-10','2026-11','2026-12']), "
        "M.flussiCanone({netto_per_anno:{2027:10000000},rate_n:3,da_mese:'2027-03',"
        "calendario:null,aliquota_iva:22}, MESI_9).map(f=>f.importo)])",
    )
    assert json.loads(js) == [
        1221,
        6,
        {"2026-10": 3333333, "2026-11": 3333333, "2026-12": 3333334},
        [4066666, 4066666, 4066668],
    ]


def test_js_progetto_spento_non_muove(tmp_path):
    p = build_payload(snapshot_sintetico(), [])
    spento = Scenario(
        "off",
        [
            Progetto(
                "T",
                "Terrazza",
                "INTUR",
                False,
                "tua",
                [Pagamento("Pavimento", {"2026-11": to_cent(130_000)}, 22, "tua")],
            )
        ],
        [],
    )
    out = esegui_node(tmp_path, render_html(p), p, scenario_to_json(spento, p["base"]))
    assert out["righe"] == p["baseline"]["righe"]


# ── push KV ──


class _FakeResp:
    ok = True
    status_code = 200
    text = ""

    def json(self):
        return {"success": True}


def test_push_to_kv_bulk(monkeypatch):
    import requests

    calls = {}

    def fake_put(url, json=None, headers=None, timeout=None):
        calls.update(url=url, body=json, headers=headers)
        return _FakeResp()

    monkeypatch.setattr(requests, "put", fake_put)
    env = {
        "CLOUDFLARE_API_TOKEN": "tok",
        "CLOUDFLARE_ACCOUNT_ID": "acc",
        "CDG_KV_NAMESPACE_ID": "ns",
    }
    assert set(env) == set(PUSH_ENV_VARS)
    push_to_kv("<html>", '{"a":1}', env)
    assert (
        calls["url"]
        == "https://api.cloudflare.com/client/v4/accounts/acc/storage/kv/namespaces/ns/bulk"
    )
    assert calls["headers"]["Authorization"] == "Bearer tok"
    assert {e["key"]: e["value"] for e in calls["body"]} == {
        KV_KEY: "<html>",
        KV_DATA_KEY: '{"a":1}',
    }


# ── replica del simulatore (dati veri, fuori da git) ──


def test_replica_cassa_panorama():
    f = Path(".hotelops_state/cdg_cassa/replica_cassa_panorama.json")
    if not f.exists():
        pytest.skip("snapshot locale assente")
    d = json.loads(f.read_text(encoding="utf-8"))
    ris = to_dict(calcola(input_da_dict(d["input"])))
    assert (
        ris["minimi"]["INTUR"]["mese"] == "2027-06"
        and ris["minimi"]["ORTI"]["mese"] == "2027-01"
    )
    assert ris["minimi"]["INTUR"]["saldo"] // 100 == d["atteso"]["INTUR"]
    assert ris["minimi"]["ORTI"]["saldo"] // 100 == d["atteso"]["ORTI"]
    if "atteso_cent" in d:
        assert ris["minimi"]["INTUR"]["saldo"] == d["atteso_cent"]["INTUR"]
        assert ris["minimi"]["ORTI"]["saldo"] == d["atteso_cent"]["ORTI"]


# ── fix round 1: niente finestre modali, input euro validato, calendario al centesimo ──


def esegui_node_formato(tmp_path: Path, html: str, espressione: str) -> str:
    """Esegue `espressione` con F = FORMATO (script id="formato"); stampa il risultato."""
    if NODE is None:
        pytest.skip("node non installato")
    formato = re.search(r'<script id="formato">(.*?)</script>', html, re.S).group(1)
    (tmp_path / "formato.js").write_text(formato, encoding="utf-8")
    (tmp_path / "run.js").write_text(
        f"const F=require('./formato.js');console.log({espressione});", encoding="utf-8"
    )
    r = subprocess.run([NODE, "run.js"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_html_senza_finestre_modali():
    html = render_html(build_payload(snapshot_sintetico(), []))
    assert "alert(" not in html and "prompt(" not in html and "confirm(" not in html
    assert '<script id="formato">' in html and "Nessuna leva" in html
    assert "Azzera leve" not in html


def test_js_parse_euro_validato(tmp_path):
    html = render_html(build_payload(snapshot_sintetico(), []))
    out = esegui_node_formato(
        tmp_path,
        html,
        "JSON.stringify([F.parseEuro('abc'), F.parseEuro('1.234,567'), F.parseEuro('100,01'), "
        "F.parseEuro('1.234'), F.parseEuro('-1.549,23'), F.parseEuro(''), F.parseEuro('1.234.567,8')])",
    )
    assert json.loads(out) == [None, None, 10001, 123400, -154923, 0, 123456780]


def test_js_calendario_conserva_i_centesimi(tmp_path):
    html = render_html(build_payload(snapshot_sintetico(), []))
    out = esegui_node_formato(
        tmp_path,
        html,
        "JSON.stringify([F.calendarioParse(F.calendarioTesto({'2027-06': 30000000, '2027-03': 20000050})), "
        "F.calendarioParse('2027-03=abc'), F.calendarioParse('')])",
    )
    assert json.loads(out) == [{"2027-03": 20000050, "2027-06": 30000000}, None, {}]


def test_script_della_pagina_compila(tmp_path):
    """Ogni script della pagina si carica: i test sui blocchi estratti non vedono una
    dichiarazione doppia nello script `app` (pagina bianca, 30/10)."""
    if NODE is None:
        pytest.skip("node non installato")
    html = render_html(build_payload(snapshot_sintetico(), []))
    for nome in ("motore", "formato", "app"):
        js = re.search(rf'<script id="{nome}">(.*?)</script>', html, re.S).group(1)
        f = tmp_path / f"{nome}.js"
        f.write_text(js, encoding="utf-8")
        r = subprocess.run([NODE, "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, f"{nome}: {r.stderr}"


def test_js_netto_da_lordo_rientra_nel_lordo(tmp_path):
    """Lo slider è in lordo IVA inclusa: 732.000 lordo al 22% → 600.000 netto, e l'IVA sul netto rifà il lordo."""
    html = render_html(build_payload(snapshot_sintetico(), []))
    out = esegui_node_formato(
        tmp_path,
        html,
        "JSON.stringify([F.nettoDaLordo(73200000, 22), F.nettoDaLordo(24400000, 22), "
        "F.nettoDaLordo(0, 22), F.nettoDaLordo(100, 0), F.nettoDaLordo(12201, 22)])",
    )
    assert json.loads(out) == [60000000, 20000000, 0, 100, 10001]


def test_js_canone_tondo_resta_tondo(tmp_path):
    """1.200.000 lordo sullo slider: rate scalate in lordo (400.000,00 ciascuna) e annuo mostrato
    1.200.000,00, non 1.199.999,99 (il giro lordo→netto→scala→lordo perdeva un centesimo)."""
    html = render_html(build_payload(snapshot_sintetico(), []))
    out = esegui_node_formato(
        tmp_path,
        html,
        "JSON.stringify([F.scalaRate({'2027-06': 24400000, '2027-09': 24400000}, 120000000, 73200000, 22), "
        "F.annuoDaLordi(80000000, 48800000, 73200000), F.annuoDaLordi(5, 0, 73200000)])",
    )
    assert json.loads(out) == [{"2027-06": 32786885, "2027-09": 32786885}, 120000000, 5]


def test_js_canone_non_divisibile_resto_sull_ultima_rata(tmp_path):
    """1.000.000 lordo in tre rate: 333.333,33 + 333.333,33 + 333.333,34, e ogni netto ridà
    esattamente il suo lordo con l'IVA del motore."""
    html = render_html(build_payload(snapshot_sintetico(), []))
    rif = "{'2026-12': 24400000, '2027-06': 24400000, '2027-09': 24400000, '2027-12': 24400000}"
    out = esegui_node_fn(
        tmp_path,
        html,
        "(() => { const F = require('./formato.js');"
        f" const cal = F.scalaRate({rif}, 100000000, 73200000, 22);"
        " return JSON.stringify(Object.fromEntries(Object.entries(cal).map(([m, n]) => [m, M.iva(n, 22)]))); })()",
    )
    assert json.loads(out) == {
        "2026-12": 33333333,
        "2027-06": 33333333,
        "2027-09": 33333333,
        "2027-12": 33333334,
    }


ORIZ_JS = "['2026-10','2026-11','2026-12','2027-01','2027-02','2027-03','2027-04','2027-05','2027-06']"


def test_js_spalma_con_cadenza_e_resto_sull_ultima(tmp_path):
    """Rateizza: 100.000 in 3 rate ogni 2 mesi da nov 26 -> nov, gen, mar; il resto va sull'ultima."""
    html = render_html(build_payload(snapshot_sintetico(), []))
    out = esegui_node_formato(
        tmp_path,
        html,
        f"JSON.stringify([F.spalma(10000000, '2026-11', 3, 2, {ORIZ_JS}), F.spalma(100, '2026-10', 1, 1, {ORIZ_JS})])",
    )
    assert json.loads(out) == [
        {"2026-11": 3333333, "2027-01": 3333333, "2027-03": 3333334},
        {"2026-10": 100},
    ]


def test_js_spalma_oltre_orizzonte_dice_dove_cade(tmp_path):
    html = render_html(build_payload(snapshot_sintetico(), []))
    out = esegui_node_formato(
        tmp_path,
        html,
        f"(() => {{ try {{ F.spalma(100, '2027-04', 3, 2, {ORIZ_JS}); return 'nessun errore'; }} catch (e) {{ return e.message; }} }})()",
    )
    assert "giu 27" in out and "ago 27" in out


def test_js_sposta_mantiene_importi_e_totale(tmp_path):
    html = render_html(build_payload(snapshot_sintetico(), []))
    out = esegui_node_formato(
        tmp_path,
        html,
        f"(() => {{ const r = [F.sposta({{'2026-11': 5, '2027-01': 7}}, 1, {ORIZ_JS})];"
        f" try {{ F.sposta({{'2027-06': 5}}, 1, {ORIZ_JS}); }} catch (e) {{ r.push('errore'); }}"
        f" return JSON.stringify(r); }})()",
    )
    assert json.loads(out) == [{"2026-12": 5, "2027-02": 7}, "errore"]


def test_js_forma_rate_legge_come_si_paga(tmp_path):
    html = render_html(build_payload(snapshot_sintetico(), []))
    out = esegui_node_formato(
        tmp_path,
        html,
        "JSON.stringify(["
        f"F.formaRate({{'2026-11': 3333333, '2027-01': 3333333, '2027-03': 3333334}}, {ORIZ_JS}),"
        f"F.formaRate({{'2026-11': 100, '2026-12': 900}}, {ORIZ_JS}),"
        f"F.formaRate({{'2026-11': 100, '2026-12': 100, '2027-03': 100}}, {ORIZ_JS}),"
        f"F.formaRate({{}}, {ORIZ_JS})])",
    )
    assert json.loads(out) == [
        {"n": 3, "primo": "2026-11", "ultimo": "2027-03", "passo": 2, "quota": 3333333, "totale": 10000000},
        {"n": 2, "primo": "2026-11", "ultimo": "2026-12", "passo": 1, "quota": None, "totale": 1000},
        {"n": 3, "primo": "2026-11", "ultimo": "2027-03", "passo": None, "quota": 100, "totale": 300},
        {"n": 0, "primo": None, "ultimo": None, "passo": None, "quota": None, "totale": 0},
    ]


def test_js_leggi_documento_importato(tmp_path):
    """Importa scenario: il file esportato dalla pagina rientra; file sbagliati danno un errore leggibile."""
    p = build_payload(snapshot_sintetico(), [])
    html = render_html(p)
    sc, _ = scenario_sintetico()
    doc = scenario_to_json(sc, p["base"])
    (tmp_path / "doc.json").write_text(doc, encoding="utf-8")
    out = esegui_node_formato(
        tmp_path,
        html,
        f"(() => {{ const fs = require('fs'); const t = fs.readFileSync('./doc.json', 'utf8');"
        f" const ok = F.leggiDocumento(t, '{SCHEMA}');"
        f" const rotto = JSON.parse(t); rotto.scenario.progetti[0].pagamenti[0].mesi = {{'2027-1': 5}};"
        f" return JSON.stringify([ok.errore || null, ok.nome, ok.scenario.progetti.length,"
        f" F.leggiDocumento('non json', '{SCHEMA}').errore,"
        f" F.leggiDocumento(JSON.stringify({{schema: 'altro/1'}}), '{SCHEMA}').errore,"
        f" F.leggiDocumento(JSON.stringify(rotto), '{SCHEMA}').errore]); }})()",
    )
    errore, nome, n_prog, e_json, e_schema, e_mese = json.loads(out)
    assert errore is None and nome and n_prog >= 1
    assert "JSON" in e_json
    assert "altro/1" in e_schema
    assert "2027-1" in e_mese


AMCN_JS = (
    "{fornitore: 'AMCN', totale: 48200000, aliquota_iva: 0, modo: 'sal', anticipo_pct: 15,"
    " anticipo_mese: '2026-10', ritenuta_pct: 10, svincolo_mese: '2027-05', sal_modo: 'n', sal_n: 5,"
    " sal_ogni: 0, sal_da: '2026-11', sal_passo: 1, quote: []}"
)
AMCN_PAGAMENTI = [
    {"nome": "AMCN · anticipo 15%", "mesi": {"2026-10": 7230000}, "aliquota_iva": 0, "stato": "contratto", "fornitore_id": "AMCN"},
    {
        "nome": "AMCN · SAL",
        "mesi": {m: 7230000 for m in ("2026-11", "2026-12", "2027-01", "2027-02", "2027-03")},
        "aliquota_iva": 0,
        "stato": "contratto",
        "fornitore_id": "AMCN",
    },
    {"nome": "AMCN · svincolo ritenuta 10%", "mesi": {"2027-05": 4820000}, "aliquota_iva": 0, "stato": "contratto", "fornitore_id": "AMCN"},
]


def test_js_contratto_anticipo_sal_ritenuta(tmp_path):
    """Contratto AMCN 482.000: anticipo 15% a ott 26, 5 SAL mensili da nov 26, ritenuta 10% a mag 27."""
    html = render_html(build_payload(snapshot_sintetico(), []))
    out = esegui_node_formato(tmp_path, html, f"JSON.stringify(F.pagamentiDaContratto({AMCN_JS}, {ORIZ_JS}))")
    assert json.loads(out) == AMCN_PAGAMENTI


def test_js_contratto_sal_ogni_importo_di_lavori(tmp_path):
    """SAL ogni 100.000 di lavori su 250.000, anticipo 10%, ritenuta 5%: 3 SAL da 85.000, 85.000, 42.500."""
    html = render_html(build_payload(snapshot_sintetico(), []))
    c = (
        "{fornitore: 'X', totale: 25000000, aliquota_iva: 22, modo: 'sal', anticipo_pct: 10, anticipo_mese: '2026-10',"
        " ritenuta_pct: 5, svincolo_mese: '2027-06', sal_modo: 'ogni', sal_n: 0, sal_ogni: 10000000,"
        " sal_da: '2026-12', sal_passo: 2, quote: []}"
    )
    out = esegui_node_formato(tmp_path, html, f"JSON.stringify(F.pagamentiDaContratto({c}, {ORIZ_JS}).map((g) => g.mesi))")
    assert json.loads(out) == [
        {"2026-10": 2500000},
        {"2026-12": 8500000, "2027-02": 8500000, "2027-04": 4250000},
        {"2027-06": 1250000},
    ]


def test_js_contratto_a_percentuali_e_errori(tmp_path):
    html = render_html(build_payload(snapshot_sintetico(), []))
    base = "fornitore: 'Y', totale: 10000000, aliquota_iva: 10, modo: 'percentuali', quote: "
    espr = (
        "(() => { const r = [F.pagamentiDaContratto({" + base + "[{pct: 30, mese: '2026-11'}, {pct: 40, mese: '2027-02'},"
        " {pct: 30, mese: '2027-05'}]}, " + ORIZ_JS + ")[0].mesi];"
        " for (const c of [{" + base + "[{pct: 30, mese: '2026-11'}]}, {...{" + base + "[]}, fornitore: ''},"
        " {fornitore: 'Z', totale: 100, aliquota_iva: 0, modo: 'sal', anticipo_pct: 60, anticipo_mese: '2026-10',"
        " ritenuta_pct: 50, svincolo_mese: '2027-01', sal_modo: 'n', sal_n: 1, sal_da: '2026-11', sal_passo: 1, quote: []}])"
        " { try { F.pagamentiDaContratto(c, " + ORIZ_JS + "); r.push('nessun errore'); } catch (e) { r.push(e.message); } }"
        " return JSON.stringify(r); })()"
    )
    out = json.loads(esegui_node_formato(tmp_path, html, espr))
    assert out[0] == {"2026-11": 3000000, "2027-02": 4000000, "2027-05": 3000000}
    assert "30%" in out[1] and "100%" in out[1]
    assert "fornitore" in out[2]
    assert "anticipo" in out[3] and "ritenuta" in out[3]


def test_js_contratto_ricostruito_dai_pagamenti_rigenera_gli_stessi(tmp_path):
    """Dai pagamenti AMCN già nel seme la pagina ricostruisce il contratto; «Genera» rifà gli stessi importi."""
    html = render_html(build_payload(snapshot_sintetico(), []))
    pag = json.dumps(AMCN_PAGAMENTI)
    out = esegui_node_formato(
        tmp_path,
        html,
        f"(() => {{ const c = F.contrattoDaPagamenti({pag}, 'AMCN', {ORIZ_JS});"
        f" return JSON.stringify([c, F.pagamentiDaContratto(c, {ORIZ_JS})]); }})()",
    )
    c, rigenerati = json.loads(out)
    assert c["totale"] == 48200000 and c["anticipo_pct"] == 15 and c["ritenuta_pct"] == 10
    assert c["sal_n"] == 5 and c["sal_da"] == "2026-11" and c["svincolo_mese"] == "2027-05"
    assert [g["mesi"] for g in rigenerati] == [g["mesi"] for g in AMCN_PAGAMENTI]


def test_js_sposta_una_rata_nel_calendario(tmp_path):
    """Trascinare una rata: l'importo passa al mese di arrivo (si somma se c'è già), il totale non cambia."""
    html = render_html(build_payload(snapshot_sintetico(), []))
    out = esegui_node_formato(
        tmp_path,
        html,
        "JSON.stringify([F.spostaRata({'2026-11': 5, '2027-01': 7}, '2026-11', '2026-12'),"
        " F.spostaRata({'2026-11': 5, '2027-01': 7}, '2026-11', '2027-01'),"
        " F.spostaRata({'2026-11': 5}, '2026-11', '2026-11'),"
        " F.spostaRata({'2026-11': 5}, '2026-12', '2027-01')])",
    )
    assert json.loads(out) == [
        {"2026-12": 5, "2027-01": 7},
        {"2027-01": 12},
        {"2026-11": 5},
        {"2026-11": 5},
    ]


# ── andata e ritorno: documento costruito come lo esporta la pagina → scenario_from_json ──


def test_documento_esportato_dalla_pagina_rientra_in_python(tmp_path: Path):
    """La pagina esporta `{schema, nome, salvato_il, base, scenario}` con lo scenario così come lo
    tiene in memoria (copia del seme, MAI `MOTORE.normalizza`, che riscrive i manuali in `importo`
    e romperebbe `scenario_from_json`) più i progetti e i finanziamenti nuovi creati con i default
    letterali del template («+ progetto», «+ finanziamento») e una sottovoce scritta nella tabella a livelli,
    con i pagamenti derivati come fa la pagina. Tutto deve rientrare
    in `scenario_from_json` senza perdere nulla: è l'unico ponte browser → BigQuery."""
    import json as _json

    from verticals.condges.cassa_scenario import scenario_from_json

    p = build_payload(snapshot_sintetico(), [], seme=_scenario_base())
    html = render_html(p)
    # I letterali con cui la pagina crea le leve nuove, presi dal template: se cambiano, il test
    # cambia con loro (e non mente).
    nuovo_p = re.search(r"sc\.progetti\.push\((\{.*?\})\);", html).group(1)
    nuovo_f = re.search(r"sc\.finanziamenti\.push\((\{.*?\})\);", html).group(1)
    espr = (
        "(() => { const sc = JSON.parse(JSON.stringify(D.seme.scenario)); const id = 'P1'; "
        f"sc.progetti.push({nuovo_p}); const p = sc.progetti[sc.progetti.length - 1]; "
        "const F = require('./formato.js'); "
        "p.livelli.macro.push({ id: 'm1', nome: 'Lavori', budget_netto: null, mesi_budget: null, aliquota_iva: null, area: 'Opere', voci: ["
        " { id: 'v1', nome: 'Pagamento', fornitore_id: null, area: null, netto: 0, mesi: {}, aliquota_iva: null, stato: null, documenti: [], note: '' },"
        " { id: 'v2', nome: 'Nuovo pagamento', fornitore_id: null, area: null, netto: 12000000, mesi: M.distribuisci(12000000, D.mesi[1], 3, D.mesi), aliquota_iva: null, stato: null, documenti: [], note: '' }] }); "
        "p.pagamenti = F.derivaPagamenti(p, D.mesi); "
        f"sc.finanziamenti.push({nuovo_f}); const f = sc.finanziamenti[sc.finanziamenti.length - 1]; "
        "f.erogazioni[D.mesi[0]] = 10000000; f.rate[D.mesi[2]] = 500000; "
        "sc.canone = { netto_per_anno: { '2026': 30000000 }, rate_n: 2, da_mese: D.mesi[0], calendario: null, aliquota_iva: 22 }; "
        "sc.soglia = 5000000; "
        "return JSON.stringify({ schema: D.schema, nome: 'prova', salvato_il: new Date(0).toISOString(), base: D.base, scenario: { ...sc, nome: 'prova' } }); })()"
    )
    doc = esegui_node_fn(tmp_path, html, espr)
    sc, base, meta = scenario_from_json(doc)
    assert meta["nome"] == "prova" and base == p["base"]
    assert sc.soglia == 5_000_000 and sc.canone.netto_per_anno == {2026: 30_000_000}
    assert sc.canone.rate_n == 2 and sc.canone.aliquota_iva == 22
    nuovo = sc.progetti[-1]
    assert nuovo.id == "P1" and nuovo.acceso is True and len(nuovo.pagamenti) == 2
    assert sum(nuovo.pagamenti[1].mesi.values()) == 12_000_000
    assert nuovo.pagamenti[1].macro == "Lavori" and nuovo.pagamenti[1].area == "Opere"
    assert [v["id"] for v in nuovo.livelli["macro"][0]["voci"]] == ["v1", "v2"]
    fin = sc.finanziamenti[-1]
    assert fin.erogazioni == {p["mesi"][0]: 10_000_000} and fin.rate == {p["mesi"][2]: 500_000}
    # il giro completo: il documento riletto e riserializzato è identico nel contenuto
    doc2 = _json.loads(doc)
    assert doc2["schema"] == SCHEMA and set(doc2["scenario"]) >= {"progetti", "finanziamenti", "canone", "soglia", "manuali"}


# ── fluidità: barra fissa dei minimi, battito sul numero cambiato, trascinamento con soglia ──
# Il comportamento vive nel browser (verificato a mano con Playwright, 30/10/2026); qui si
# pinnano i pezzi di template che lo rendono possibile, così una regressione non passa in silenzio.


def test_template_porta_barra_fissa_battito_e_preferenze_di_movimento():
    html = render_html(build_payload(snapshot_sintetico(), []))
    assert 'id="barra-minimi"' in html and "IntersectionObserver" in html
    assert "scroll-padding-top" in html, "la barra fissa non deve coprire la destinazione di uno scroll"
    assert "@keyframes battito" in html and 'classList.add("cambiato")' in html
    assert "prefers-reduced-motion" in html and "prefers-reduced-transparency" in html
    assert "backdrop-filter" in html, "la barra è un materiale traslucido, il contenuto scorre sotto"


def test_template_porta_la_scelta_dello_scenario_in_alto():
    html = render_html(build_payload(snapshot_sintetico(), []))
    # una pillola per scenario sotto il titolo, prima dei minimi; stessa chiave del menu
    assert html.index('id="scelta-scenario"') < html.index('id="minimi"')
    assert "data-scelta=" in html and 'aria-pressed="${(stato.chiave || "seme") === s._k}"' in html
    assert ".scelta button[aria-pressed=\"true\"]" in html


def test_template_porta_il_bottone_esporta_excel_e_il_writer_puro():
    html = render_html(build_payload(snapshot_sintetico(), []))
    assert '<script id="excel">' in html and 'id="esporta-excel"' in html
    assert "EXCEL.costruisci(fogliExcel())" in html
    # i fogli promessi dal bottone sono quelli costruiti
    for nome in ("Minimi", "Saldi mese per mese", "Calendario", "Canone", "Progetti", "Finanziamenti", "Voci PF corrette", "PF", "Fonti"):
        assert f'nome: "{nome}"' in html, nome


def test_excel_scritto_dal_browser_si_riapre_con_openpyxl(tmp_path):
    # Il writer è puro (stesso codice in pagina e qui): node lo esegue, openpyxl rilegge.
    if NODE is None:
        pytest.skip("node non installato")
    openpyxl = pytest.importorskip("openpyxl")
    html = render_html(build_payload(snapshot_sintetico(), []))
    js = re.search(r'<script id="excel">(.*?)</script>', html, re.S).group(1)
    (tmp_path / "excel.js").write_text(js, encoding="utf-8")
    (tmp_path / "run.js").write_text(
        'const E=require("./excel.js");const fs=require("fs");'
        'const fogli=[{nome:"Minimi",colonne:["scenario","società","saldo €"],euro:[2],righe:[["Prova","INTUR",-1234.56],["Prova","ORTI",987654.3]]},'
        '{nome:"Fonti/versioni:[sì]?",colonne:["cosa","valore"],righe:[["a","b & c <d>"]]},{nome:"Minimi",colonne:["x"],righe:[[true]]}];'
        'fs.writeFileSync("prova.xlsx",Buffer.from(E.costruisci(fogli,new Date(2026,9,31,15,0,0))));',
        encoding="utf-8",
    )
    r = subprocess.run([NODE, "run.js"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    wb = openpyxl.load_workbook(tmp_path / "prova.xlsx")
    # nomi puliti dai caratteri vietati, doppioni numerati, prima riga in grassetto, euro con due decimali
    assert wb.sheetnames == ["Minimi", "Fonti versioni  sì", "Minimi 2"]
    ws = wb["Minimi"]
    assert [c.value for c in ws[1]] == ["scenario", "società", "saldo €"] and ws["A1"].font.b
    assert ws["C2"].value == -1234.56 and ws["C2"].number_format == "#,##0.00" and ws["C3"].value == 987654.3
    assert wb["Fonti versioni  sì"]["B2"].value == "b & c <d>" and wb["Minimi 2"]["A2"].value is True


def test_template_brief_ui_1_3_parole_stati_e_finanziamenti():
    html = render_html(build_payload(snapshot_sintetico(), []))
    # 1. il bottone dice il risultato; nessuna parola con due significati; via il doppione della pillola
    assert "Salva scenario (.json)" in html and "Excel (.xlsx)" in html and "Apri scenario (.json)" in html
    assert "Esporta scenario" not in html and "Esporta Excel" not in html and 'id="nessuna"' not in html
    assert ">Genera le rate<" in html and ">Rateizza<" not in html
    # 2. finanziamenti: due riquadri nelle parole di Stefano, generatore delle tranche, controllo «erogato X di Y»
    assert "Quando la banca ti dà i soldi" in html and "Quando li restituisci" in html
    assert "data-genera-tranche" in html and "erogato ${fmt(erogato, false)} di ${fmt(f.importo, false)}" in html
    assert "metà a metà lavori, metà a fine lavori" in html
    # 3. vocabolario di stato: attributo del dato + classe CSS, riusato da card, barra, fonti, finanziamenti
    assert 'class="stato' in html and 'data-stato="' in html and ".stato[data-stato=\"non-registrato\"]" in html
    assert "const STATI = { attestato:" in html and "function condizioni(soc, m)" in html
    assert "quadra con i movimenti</span>" not in html and "solo dichiarato" not in html
    # bozze finte: il documento si completa all'apertura e una bozza nasce solo se è diversa da tutto il menu
    assert "function completa(scenario)" in html and "data-scarta=" in html
    # il «×» di una sottovoce sta sulla sua riga, non dentro il dettaglio; la riga nuova tiene il fuoco
    assert html.index("data-elimina-voce=") < html.index("function dettaglioVoce(p, m, v)")
    assert "rinomina = { k, da: r, a: `v:${m.id}:${x.id}` };" in html


def test_template_vista_scenario_a_tutto_schermo():
    html = render_html(build_payload(snapshot_sintetico(), []))
    # ingresso, barra alta, segmenti, scrim; una classe sul body, stesso DOM
    for pezzo in ('id="apri-leve"', 'id="leve-top"', 'id="esci-leve"', 'id="leve-seg"', 'id="leve-scrim"', "function entraVista(", "function esciVista("):
        assert pezzo in html, pezzo
    # un editor alla volta: il foglio è l'unica leva aperta (fixed al telefono, pannello a destra dai 900 px)
    assert "body.vista-leve details.leva.aperta{position:fixed" in html and "function apriFoglio(d, anima = true)" in html
    assert "@media (min-width:900px){\n  body.vista-leve details.leva.aperta{left:auto;right:0" in html
    # dentro una leva, un pagamento aperto alla volta
    assert 'd.classList.contains("sotto") || !d.open' in html
    # entra dal basso ed esce dal basso; la velocità decide; «riduci movimento» = dissolvenza
    assert 'transform: "translateY(100%)" }, { transform: "translateY(0)" }' in html and "if (v > 500 || (dy > h * 0.35" in html
    assert 'ridotto() && d.animate) d.animate([{ opacity: 0 }, { opacity: 1 }]' in html
    # il riepilogo apre il foglio, non la tendina; l'indirizzo ricorda la vista
    assert 'location.hash.startsWith("#leve")' in html and "`#leve/${seg}`" in html


def test_template_dividi_unisci_e_documenti_drive():
    html = render_html(build_payload(snapshot_sintetico(), []))
    # dividi: metà resta, metà al mese dopo; unisci: con la rata successiva; la somma non cambia
    assert "function dividiRata(mesi, m)" in html and "function unisciRata(mesi, m)" in html
    assert "data-${pref}-dividi=" in html and "data-${pref}-unisci=" in html
    assert "mesi[m] = v - meta;" in html and "mesi[dopo] = (mesi[dopo] || 0) + meta;" in html
    # documenti sul pagamento (link Drive) e cartella Drive sul progetto, anche nell'Excel
    assert "data-aggiungi-doc" in html and 'data-campo="drive_url"' in html and 'class="doc"' in html
    assert '"documenti", "cartella Drive"]' in html
    # anche il finanziamento porta i suoi documenti (relazione notarile, delibera), nella tendina e nell'Excel
    assert "relazione notarile 22/10/2026" in html and 'f.documenti.push({ titolo: "", url: "" })' in html
    assert '"importo finanziamento €", "documenti"]' in html


def test_template_i_patti_col_fornitore_non_si_chiamano_contratto():
    # «contratto» sembrava un documento; è «come paghi questo fornitore», e genera i pagamenti che il calcolo legge
    html = render_html(build_payload(snapshot_sintetico(), []))
    assert "+ come paghi un fornitore" in html and ">+ contratto<" not in html
    assert "<strong>Come paghi ${esc(F ||" in html and "<strong>Contratto ${esc(F ||" not in html
    assert "togli i patti" in html and "togli il contratto" not in html
    assert "il calcolo legge solo quelle" in html
    # nella vista a tutto schermo ogni riga ha un tasto «apri ›» esplicito, oltre al tocco sulla riga
    assert html.count("data-apri-foglio aria-label=\"apri\"") == 4 and 'e.target.closest("button[data-apri-foglio]")' in html
    # a tutto schermo c'è un editor alla volta: «apri tutto / chiudi tutto» spariscono (aprivano tendine che la vista non mostra)
    assert "body.vista-leve .strumenti button[data-apri],body.vista-leve .strumenti button[data-chiudi]{display:none}" in html


def test_template_ricorda_la_bozza_nel_browser():
    # Brief UI punto 9: la pagina rigenerata dal seme non deve cancellare il lavoro fatto a mano nel browser.
    html = render_html(build_payload(snapshot_sintetico(), []))
    assert 'id="bozza-avviso"' in html and 'const CHIAVE_BOZZA = "cdg-cassa-bozza"' in html
    assert "function ricordaBozza()" in html and "function proponiBozza()" in html and "ricordaBozza();" in html
    # si ricorda solo se è cambiata; al ricaricamento propone «Riprendi» o «Scarta»; «Salva» la marca salvata
    assert "if (!modificato()) return;" in html and 'id="bozza-riprendi"' in html and 'id="bozza-scarta"' in html
    assert "b.salvata = true" in html
    # l'avviso prima di chiudere c'è solo se il browser non ha memoria
    assert "if (modificato() && !memoriaOk)" in html


def test_template_fornitore_come_oggetto():
    html = render_html(build_payload(snapshot_sintetico(), []))
    # scheda Fornitori, segmento nella vista, mappa nello scenario, riconoscimento dall'anagrafica Esolver
    assert 'id="fornitori"' in html and 'data-seg="fornitori"' in html and "function renderFornitori()" in html
    assert "function riconosci(nome)" in html and "s.fornitori = s.fornitori || {};" in html
    # il campo «fornitore» del pagamento suggerisce gli id noti; il nuovo fornitore eredita il codice riconosciuto
    assert 'list="lista-fornitori-id"' in html and 'id="aggiungi-v"' in html and "data-vf-usa" in html
    # l'Excel ha il foglio Fornitori con le colonne della tabella CLI
    assert 'nome: "Fornitori", colonne: ["fornitore_id", "nome", "codice_esolver"' in html
    # il payload porta l'anagrafica (vuota nello snapshot sintetico)
    assert build_payload(snapshot_sintetico(), [])["fornitori"] == []
    # patti abituali: si ricordano da un contratto (mesi → distanze dall'inizio) e si riapplicano a uno nuovo
    assert "function pattiDaContratto(c)" in html and "function contrattoDaPatti(p, inizio, fornitore, totale)" in html
    assert "data-ricorda-patti" in html and "data-usa-patti" in html and "data-vf-dimentica" in html
    # un contratto ancora vuoto eredita i patti del fornitore appena scritto; uno già scritto no
    assert 'x.dataset.cc === "fornitore" && pattiDi(x.value) && contrattoVuoto(c)' in html
    # il nome è il nostro, il codice aggancia Esolver
    assert "il nome è il nostro, il codice aggancia Esolver" in html


def test_pf_corretto_sostituisce_la_voce_per_tutti_gli_scenari():
    # Le tasse dichiarate da Rosa valgono per tutti: Solo PF, seme, salvati. Il file del PF non cambia.
    snap = snapshot_sintetico()
    mese = MESI_PF[1]
    prima = sum(r["importo"] for r in snap["pf"] if (r["societa"], r["voce_id"], r["mese"]) == ("INTUR", "USCITE_TASSE", mese))
    corr = {"schema": "cdg-cassa-pf-corretto/1", "correzioni": [
        {"societa": "INTUR", "voce_id": "USCITE_TASSE", "mese": mese, "importo_cent": prima + 5_000_00, "dichiarato_da": "Rosa", "dichiarato_il": "2026-10-31", "fonte": "test"},
        {"societa": "INTUR", "voce_id": "USCITE_TASSE", "mese": "2031-01", "importo_cent": 1, "dichiarato_da": "Rosa"},
    ]}
    nuovo, esito = applica_pf_corretto(snap, corr)
    assert snap["pf"] is not nuovo["pf"]  # l'originale non cambia
    dopo = [r for r in nuovo["pf"] if (r["societa"], r["voce_id"], r["mese"]) == ("INTUR", "USCITE_TASSE", mese)]
    assert len(dopo) == 1 and dopo[0]["importo"] == prima + 5_000_00 and dopo[0]["origine"] == "pf" and dopo[0]["direzione"] == "U"
    assert [(c["applicata"], c["nel_pf"]) for c in esito] == [(True, prima), (False, 0)] and esito[1]["motivo"] == "mese fuori dal PF"
    # nel payload: Solo PF (baseline) più basso di 5.000 nel mese, la lista pf_correzioni e una riga nei limiti
    p0 = build_payload(snapshot_sintetico(), [])
    p1 = build_payload(snapshot_sintetico(), [], pf_corretto=corr)
    fin0 = next(r["fin"] for r in p0["baseline"]["righe"] if r["societa"] == "INTUR" and r["mese"] == mese)
    fin1 = next(r["fin"] for r in p1["baseline"]["righe"] if r["societa"] == "INTUR" and r["mese"] == mese)
    assert fin0 - fin1 == 5_000_00
    assert [c["corretto"] for c in p1["pf_correzioni"]] == [prima + 5_000_00, 1]
    assert any(x.startswith("PF corretto: 1 voce del PF dichiarate da Rosa") for x in p1["limiti"])
    assert p0["pf_correzioni"] == [] and not any(x.startswith("PF corretto") for x in p0["limiti"])


def test_template_mostra_il_pf_corretto_come_dichiarato():
    html = render_html(build_payload(snapshot_sintetico(), []))
    assert "D.pf_correzioni" in html and 'class="pf-corretto"' in html
    assert "vale per tutti gli scenari, anche Solo PF" in html and 'nome: "PF corretto"' in html
    assert 'chipStato("dichiarato", `${c.dichiarato_da ? `dichiarato da ${c.dichiarato_da}`' in html


def test_template_importa_budget_e_lettore_xlsx():
    html = render_html(build_payload(snapshot_sintetico(), []))
    # il lettore: zip dalla directory centrale, deflate del browser, shared strings, inlineStr, csv con «;» o «,»
    for pezzo in ("async function leggiXlsx(buf)", "function leggiCsv(testo)", 'new DecompressionStream("deflate-raw")', "xl/sharedStrings.xml", "leggi, leggiCsv, leggiXlsx, colIndice"):
        assert pezzo in html, pezzo
    # l'import: bottone, pannello, colonne indovinate dalle parole, righe di totale saltate, anteprima prima di applicare
    for pezzo in ('id="importa-budget"', 'id="budget-pannello"', "function indovinaColonne(righe)", "const PAROLE_SALTA", "function riconosciFornitoreBudget(nome)", "function pianoRigaBudget(riga)", 'id="budget-applica"',
                  # colonne, salti e «senza fornitore» vivono in FORMATO: l'app li prende da lì (un solo regex)
                  "const { PAROLE_SALTA, senzaFornitore, indovinaColonne } = FORMATO;", "if (senzaFornitore(n)) return"):
        assert pezzo in html, pezzo
    # i mesi dai patti abituali se ci sono, altrimenti una rata al mese scelto; stato «ipotesi»
    assert "contrattoDaPatti(p, budget.mese, riga.ric.id, riga.importo)" in html and 'stato: "ipotesi", fornitore_id: riga.ric.id || null' in html


def test_lettore_csv_e_colonne_xlsx_in_node(tmp_path):
    # Le parti pure del lettore girano in node: csv con «;» e decimali italiani, indice di colonna da «AB7».
    if NODE is None:
        pytest.skip("node non installato")
    html = render_html(build_payload(snapshot_sintetico(), []))
    js = re.search(r'<script id="excel">(.*?)</script>', html, re.DOTALL).group(1)
    (tmp_path / "excel.js").write_text(js, encoding="utf-8")
    (tmp_path / "run.js").write_text(
        'const E=require("./excel.js");'
        'const f=E.leggiCsv("Fornitore;Area;Totale\\nAMCN;Edile;\\"470.000,00\\"\\nSTE;Impianti;180000\\n");'
        'console.log(JSON.stringify([f[0].righe, E.colIndice("A1"), E.colIndice("AB7")]));',
        encoding="utf-8",
    )
    r = subprocess.run([NODE, "run.js"], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    righe, a, ab = json.loads(r.stdout)
    assert righe == [["Fornitore", "Area", "Totale"], ["AMCN", "Edile", 470000], ["STE", "Impianti", 180000]]
    assert (a, ab) == (0, 27)


def test_template_trascina_con_soglia_presa_e_volo():
    html = render_html(build_payload(snapshot_sintetico(), []))
    assert "touch-action:pan-y" in html, "lo scorrimento verticale resta al browser"
    assert "SOGLIA_PRESA" in html and "Math.hypot(dx, dy) < SOGLIA_PRESA" in html
    assert "presaX" in html and "transformOrigin" in html, "il fantasma rispetta il punto di presa"
    assert "f.animate([" in html and "in-volo" in html, "la rata vola fino alla cella, non si teletrasporta"
    assert "min-height:24px" in html, "bersaglio tattile minimo delle pillole"
    assert "touch-action:none" not in html


def test_js_sostituzione_uguale_a_python(tmp_path):
    """La sostituzione nel motore JS fa esattamente quello che fa in Python."""
    from dataclasses import replace as _replace

    sc, base = _scenario_base()
    sc = _replace(
        sc,
        manuali=[
            Riga("ORTI", "USCITE_TASSE", "2026-12", 9_000_000, "U", "sostituzione"),
            Riga("INTUR", "USCITE_TASSE", "2027-01", 1_000, "U", "sostituzione"),
        ],
    )
    snap = snapshot_sintetico()
    payload = build_payload(snap, [], seme=(sc, base))
    html = render_html(payload)
    doc = scenario_to_json(sc, base, "t")
    js = esegui_node(tmp_path, html, payload, doc)
    py = calcola(input_da_snapshot(snap, sc))
    for r_js, r_py in zip(js["righe"], py.righe, strict=True):
        assert r_js["fin"] == r_py.fin, (r_js["mese"], r_js["societa"])
        assert r_js["uscite"]["pf"] == r_py.uscite["pf"]
    assert js["minimi"]["ORTI"]["saldo"] == py.minimi["ORTI"].saldo


# ── livelli: totalone → macro → sottovoci, i pagamenti si derivano ──

TRE_MESI = {"2027-01": 1, "2027-02": 1, "2027-03": 1}


def _livelli(budget, mesi_budget, macro, aliquota_iva=22):
    return {
        "budget_netto": budget,
        "mesi_budget": mesi_budget,
        "aliquota_iva": aliquota_iva,
        "macro": macro,
    }


def _macro(id_, nome, voci, budget=None, mesi_budget=None, **extra):
    return {
        "id": id_,
        "nome": nome,
        "budget_netto": budget,
        "mesi_budget": mesi_budget,
        "aliquota_iva": None,
        "area": None,
        "voci": voci,
        **extra,
    }


def _voce(id_, nome, mesi, fornitore=None, **extra):
    return {
        "id": id_,
        "nome": nome,
        "fornitore_id": fornitore,
        "area": None,
        "netto": sum(mesi.values()),
        "mesi": mesi,
        "aliquota_iva": None,
        "stato": "ipotesi",
        "documenti": [],
        "note": "",
        **extra,
    }


def _deriva(tmp_path, livelli, nome="Soft restyling"):
    p = {"id": "S", "nome": nome, "stato": "ipotesi", "pagamenti": [], "livelli": livelli}
    out = esegui_node_formato(
        tmp_path,
        render_html(build_payload(snapshot_sintetico(), [])),
        f"(() => {{ const p = {json.dumps(p)}; const prima = JSON.stringify(p);"
        f" const g = F.derivaPagamenti(p, {ORIZ_JS});"
        " if (JSON.stringify(p) !== prima) throw new Error('p mutato');"
        f" return JSON.stringify({{g, b: F.buste(p.livelli), a: F.avvisiLivelli(p.livelli, {ORIZ_JS})}}); }})()",
    )
    r = json.loads(out)
    return r["g"], r["b"], r["a"]


def _somma(pagamenti):
    return sum(v for g in pagamenti for v in g["mesi"].values())


def test_busta_consuma_senza_spostare_il_totale(tmp_path):
    amcn = _voce("v1", "pitture camere", {"2027-02": 3_000_000}, "AMCN")
    g, b, _ = _deriva(tmp_path, _livelli(16_500_000, TRE_MESI, [_macro("m1", "Pitture", [amcn])]))
    assert _somma(g) == 16_500_000
    assert [x["nome"] for x in g] == ["Pitture · pitture camere", "da assegnare"]
    assert g[0]["fornitore_id"] == "AMCN" and g[0]["macro"] == "Pitture"
    assert g[1]["residuo"] is True and "residuo" not in g[0]
    assert (g[0]["macro_id"], g[0]["voce_id"]) == ("m1", "v1")
    assert (g[1]["macro"], g[1]["macro_id"], g[1]["voce_id"]) == (None, None, None)
    assert g[1]["mesi"] == {"2027-01": 4_500_000, "2027-02": 4_500_000, "2027-03": 4_500_000}
    assert b["progetto"] == {
        "budget": 16_500_000,
        "assegnato": 3_000_000,
        "da_assegnare": 13_500_000,
        "oltre": 0,
    }


def test_sforamento_macro_assorbito_dal_progetto(tmp_path):
    voci = [
        _voce("v1", "tende", {"2027-01": 2_500_000}),
        _voce("v2", "testate", {"2027-02": 2_500_000}),
    ]
    g, b, a = _deriva(tmp_path, _livelli(16_500_000, TRE_MESI, [_macro("A", "A", voci, 4_000_000)]))
    assert b["macro"] == [
        {"id": "A", "budget": 4_000_000, "assegnato": 5_000_000, "da_assegnare": 0, "oltre": 1_000_000}
    ]
    assert b["progetto"]["da_assegnare"] == 11_500_000 and b["progetto"]["oltre"] == 0
    assert _somma(g) == 16_500_000
    assert "A: oltre di 10.000" in a


def test_sforamento_oltre_il_progetto_fa_crescere_il_totale(tmp_path):
    voci = [_voce("v1", "lavori", {"2027-01": 12_000_000})]
    g, b, a = _deriva(tmp_path, _livelli(10_000_000, TRE_MESI, [_macro("m1", "Opere", voci)]))
    assert b["progetto"]["oltre"] == 2_000_000 and b["progetto"]["da_assegnare"] == 0
    assert _somma(g) == 12_000_000
    assert not any(x.get("residuo") for x in g)
    assert any("oltre di 20.000" in x for x in a)


def test_residui_pesi_resto_iva_e_mesi_del_progetto(tmp_path):
    """Pesi proporzionali, resto sull'ultimo mese; la macro senza mesi usa quelli del progetto."""
    tessili = _macro(
        "m1", "Tessili", [_voce("v1", "tende", {"2027-01": 1_000})], 2_000, aliquota_iva=10
    )
    tessili["area"] = "Fornitura e posa"
    pitture = _macro("m2", "Pitture", [], 900, {"2026-12": 1, "2027-01": 2})
    pesi = {"2027-01": 1, "2027-02": 1, "2027-03": 1}
    g, b, _ = _deriva(tmp_path, _livelli(10_000, pesi, [tessili, pitture], aliquota_iva=4))
    per_nome = {x["nome"]: x for x in g}
    assert list(per_nome) == ["Tessili · tende", "Pitture", "Tessili · da assegnare", "da assegnare"]
    assert per_nome["Pitture"]["mesi"] == {"2026-12": 300, "2027-01": 600}
    # una macro senza sottovoci è denaro non assegnato: un fatto la consuma come ogni «da assegnare»
    assert per_nome["Pitture"]["residuo"] is True
    assert (per_nome["Pitture"]["macro_id"], per_nome["Pitture"]["voce_id"]) == ("m2", None)
    assert (per_nome["Tessili · tende"]["macro_id"], per_nome["Tessili · tende"]["voce_id"]) == ("m1", "v1")
    r = per_nome["Tessili · da assegnare"]
    assert (r["macro_id"], r["voce_id"]) == ("m1", None)
    assert r["mesi"] == {"2027-01": 333, "2027-02": 333, "2027-03": 334}
    assert (r["aliquota_iva"], r["area"], r["residuo"]) == (10, "Fornitura e posa", True)
    assert per_nome["Tessili · tende"]["aliquota_iva"] == 10
    assert per_nome["Tessili · tende"]["area"] == "Fornitura e posa"
    assert per_nome["da assegnare"]["aliquota_iva"] == 4
    assert per_nome["da assegnare"]["mesi"] == {"2027-01": 2366, "2027-02": 2366, "2027-03": 2368}
    assert _somma(g) == 10_000 == b["progetto"]["budget"]


def test_conversione_v1_cassa_identica(tmp_path):
    sc, base = _scenario_base()
    p0 = sc.progetti[0]
    doc = [{"titolo": "preventivo", "url": "https://x/p.pdf"}]
    pag = [replace(p0.pagamenti[0], documenti=doc, stato="contratto", aliquota_iva=10)]
    sc = replace(sc, progetti=[replace(p0, pagamenti=pag + p0.pagamenti[1:])])
    payload = build_payload(snapshot_sintetico(), [], seme=(sc, base))
    (tmp_path / "scenario.json").write_text(scenario_to_json(sc, base), encoding="utf-8")
    out = esegui_node_fn(
        tmp_path,
        render_html(payload),
        "(() => { const F = require('./formato.js'); const sc = require('./scenario.json').scenario;"
        " const nuovo = JSON.parse(JSON.stringify(sc));"
        " nuovo.progetti = nuovo.progetti.map((p) => ({...p, pagamenti: F.derivaPagamenti("
        "{...p, livelli: F.livelliDaPagamenti(p)}, D.mesi)}));"
        " return JSON.stringify({prima: sc.progetti[0].pagamenti, dopo: nuovo.progetti[0].pagamenti,"
        " livelli: F.livelliDaPagamenti(sc.progetti[0]),"
        " r1: M.calcola(D, sc).righe, r2: M.calcola(D, nuovo).righe}); })()",
    )
    r = json.loads(out)
    campi = ("nome", "mesi", "aliquota_iva", "fornitore_id", "stato")
    assert [{k: g[k] for k in campi} for g in r["dopo"]] == [
        {k: g[k] for k in campi} for g in r["prima"]
    ]
    assert r["dopo"][0]["documenti"] == doc and "documenti" not in r["dopo"][1]
    assert all(g["macro"] == "Camere" and "residuo" not in g for g in r["dopo"])
    assert r["livelli"]["budget_netto"] is None and r["livelli"]["aliquota_iva"] == 22
    (m,) = r["livelli"]["macro"]
    assert (m["id"], m["nome"], m["budget_netto"]) == ("m1", "Camere", None)
    assert m["voci"][0]["netto"] == sum(pag[0].mesi.values())
    assert r["r1"] == r["r2"]


def test_nomi_derivati_unici(tmp_path):
    m = TRE_MESI
    macro = [
        _macro("m1", "Tessili", [_voce("v1", "tende", {"2027-01": 100})]),
        _macro(
            "m2",
            "Camere",
            [_voce("v2", "tende", {"2027-01": 100}), _voce("v3", "tende", {"2027-02": 100})],
        ),
    ]
    g, _, _ = _deriva(tmp_path, _livelli(None, m, macro))
    assert [x["nome"] for x in g] == ["Tessili · tende", "Camere · tende", "Camere · tende (2)"]


def test_budget_senza_mesi_segnalato(tmp_path):
    g, b, a = _deriva(tmp_path, _livelli(16_500_000, None, []))
    assert g == []
    assert b["progetto"]["da_assegnare"] == 16_500_000
    assert any("senza mesi" in x for x in a)
    assert "budget 165.000 senza mesi: non entra in cassa" in a


def test_mesi_budget_in_parte_fuori_orizzonte_vanno_sugli_altri(tmp_path):
    """Uno scenario salvato prima: i mesi usciti dall'orizzonte cadono, il totale resta esatto."""
    pitture = _macro("m1", "Pitture", [], 1_000, {"2026-09": 5, "2027-01": 1, "2027-02": 2})
    pesi = {"2026-08": 1, "2027-03": 1, "2027-04": 1}
    g, _, a = _deriva(tmp_path, _livelli(10_000, pesi, [pitture]))
    per_nome = {x["nome"]: x["mesi"] for x in g}
    assert per_nome == {
        "Pitture": {"2027-01": 333, "2027-02": 667},
        "da assegnare": {"2027-03": 4_500, "2027-04": 4_500},
    }
    assert _somma(g) == 10_000
    assert "Pitture: mesi del budget fuori orizzonte (set 26)" in a
    assert "progetto: mesi del budget fuori orizzonte (ago 26)" in a


def test_mesi_budget_tutti_fuori_orizzonte_nessun_pagamento(tmp_path):
    tessili = _macro("m1", "Tessili", [_voce("v1", "tende", {"2027-01": 100})], 1_000)
    g, _, a = _deriva(tmp_path, _livelli(5_000, {"2026-08": 1, "2026-09": 1}, [tessili]))
    assert [x["nome"] for x in g] == ["Tessili · tende"]
    assert "progetto: mesi del budget fuori orizzonte (ago 26, set 26)" in a


# ── Task 4: Excel del progetto — righe, «Quando», import e differenze ──


def _formato(tmp_path, espressione):
    html = render_html(build_payload(snapshot_sintetico(), []))
    return json.loads(esegui_node_formato(tmp_path, html, espressione))


def test_quando_giro_testo(tmp_path):
    calendari = [
        {"2027-03": 1_234_567},
        {"2027-01": 333, "2027-03": 333, "2027-05": 334},
        {"2026-10": 7_230_000, "2026-12": 1_000_050, "2027-05": 500},
    ]
    r = _formato(
        tmp_path,
        "JSON.stringify({tre: F.quandoParse('gen 27–mar 27 ×3', 16500000),"
        " misto: F.quandoParse('ott 26 15% · nov 26–mar 27 ×5 · mag 27 10%', 48200000),"
        " quota: F.quandoParse('mar 27 30% · giu 27', 1000), importo: F.quandoParse('mar 27 12.000 · giu 27', 2000000),"
        " cal: F.quandoParse('2027-03=12.000,00; 2027-06=8.000,00', 2000000),"
        f" giro: {json.dumps(calendari)}.map((m) => {{ const t = F.quandoTesto(m);"
        " return [t, F.quandoParse(t, Object.values(m).reduce((a, b) => a + b, 0))]; }),"
        " boh: F.quandoParse('boh', 100), troppo: F.quandoParse('mar 27 12.000', 100)})",
    )
    assert r["tre"] == {"2027-01": 5_500_000, "2027-02": 5_500_000, "2027-03": 5_500_000}
    assert sum(r["misto"].values()) == 48_200_000
    assert r["misto"]["2026-10"] == 7_230_000 and r["misto"]["2027-05"] == 4_820_000
    assert [r["misto"][m] for m in ("2026-11", "2026-12", "2027-01", "2027-02", "2027-03")] == [7_230_000] * 5
    assert r["quota"] == {"2027-03": 300, "2027-06": 700}
    assert r["importo"] == {"2027-03": 1_200_000, "2027-06": 800_000}
    assert r["cal"] == {"2027-03": 1_200_000, "2027-06": 800_000}
    for (testo, riletto), m in zip(r["giro"], calendari):
        assert riletto == m, testo
    assert r["giro"][0][0] == "mar 27" and r["giro"][1][0] == "gen 27–mag 27 ×3"
    assert r["boh"] is None and r["troppo"] is None


def _progetto_tre_righe():
    amcn = _voce("v1", "pitture camere", {"2027-02": 3_000_000}, "AMCN", aliquota_iva=22)
    amcn["documenti"] = [{"titolo": "preventivo", "url": "https://x/p.pdf"}]
    tende = _voce("v2", "tende", {"2027-01": 1_000_000, "2027-03": 1_200_000}, "PRISCO", aliquota_iva=10)
    tende["area"], tende["note"] = "Fornitura e posa", "testate comprese"
    tessili = _macro("m1", "Tessili", [tende], 4_000_000, {"2027-01": 1, "2027-03": 2})
    pitture = _macro("m2", "Pitture", [amcn])
    return {
        "id": "S",
        "nome": "Soft restyling",
        "stato": "ipotesi",
        "pagamenti": [],
        "contratti": [{"fornitore": "AMCN", "totale": 3_000_000}],
        "livelli": _livelli(16_500_000, TRE_MESI, [tessili, pitture]),
    }


def _giro(p, modifica=""):
    """Esporta p con righeProgetto, applica `modifica` (JS su `r`), reimporta: diff e progetto applicato."""
    return (
        f"(() => {{ const p = {json.dumps(p)}; const r = [F.TESTA_PROGETTO, ...F.righeProgetto(p)]; {modifica}"
        " const g = F.indovinaColonne(r);"
        " const L = F.livelliDaFoglio(r, g.colonne, {testa: g.testa, mese_default: '2027-01', iva_default: 22});"
        " const d = F.diffLivelli(p.livelli, L.livelli, p.contratti);"
        " return JSON.stringify({r, colonne: g.colonne, L, d, dopo: F.applicaLivelli(p, L.livelli),"
        " vuoto: F.righeProgetto(p, true)}); })()"
    )


def test_giro_excel_identita(tmp_path):
    p = _progetto_tre_righe()
    p["livelli"]["macro"].append(_macro("m3", "Arredi", [], aliquota_iva=10))  # macro vuota: niente budget né voci
    r = _formato(tmp_path, _giro(p))
    assert r["r"][0] == ["Macro", "Sottovoce", "Fornitore", "Area", "Totale netto €", "Quando", "IVA %", "Note"]
    assert r["r"][1] == ["budget progetto", "", "", "", 165000, "gen 27–mar 27 ×3", 22, ""]
    assert r["r"][2] == ["Tessili", "budget", "", "", 40000, "gen 27 13.333,33 · mar 27", "", ""]
    assert r["r"][3] == ["Tessili", "tende", "PRISCO", "Fornitura e posa", 22000, "gen 27 10.000 · mar 27", 10, "testate comprese"]
    assert r["r"][4] == ["Pitture", "pitture camere", "AMCN", "", 30000, "feb 27", 22, ""]
    assert r["r"][5] == ["Arredi", "", "", "", "", "", 10, ""]
    assert r["vuoto"] == [r["r"][1]]
    c = r["colonne"]
    assert (c["macro"], c["sottovoce"], c["opera"], c["area"], c["importo"], c["quando"], c["iva"], c["note"]) == (0, 1, 1, 3, 4, 5, 6, 7)
    assert r["L"]["da_sistemare"] == []
    assert r["d"] == []
    dopo = r["dopo"]
    assert dopo["contratti"] == p["contratti"]
    voci = {v["nome"]: v for m in dopo["livelli"]["macro"] for v in m["voci"]}
    assert voci["pitture camere"]["documenti"] == p["livelli"]["macro"][1]["voci"][0]["documenti"]
    assert (voci["pitture camere"]["id"], voci["tende"]["id"]) == ("v1", "v2")
    assert [m["id"] for m in dopo["livelli"]["macro"]] == ["m1", "m2", "m3"]
    assert dopo["livelli"]["macro"][2] == p["livelli"]["macro"][2]
    assert dopo["livelli"]["budget_netto"] == 16_500_000


def test_import_per_fornitore_hpan26(tmp_path):
    righe = [
        ["Struttura", "Fornitore", "Area di intervento", "Totale netto €", "Note"],
        ["Hotel", "AMCN", "Opere", 12263.79, "pitture e cartongessi"],
        ["Hotel", "Da assegnare", "Opere", 0, "da prezzare"],
        ["Hotel", "Da assegnare", "Fornitura e posa", 2400, "tende"],
        ["Hotel", "Flab", "Da comprare", 1650, "lampade"],
        ["TOTALE", None, None, 13913.79, None],
    ]
    r = _formato(
        tmp_path,
        f"(() => {{ const r = {json.dumps(righe)}; const g = F.indovinaColonne(r);"
        " return JSON.stringify({g, L: F.livelliDaFoglio(r, g.colonne,"
        " {testa: g.testa, macro_scelta: 'Camere', mese_default: '2027-02', iva_default: 22})}); })()",
    )
    c = r["g"]["colonne"]
    assert (c["fornitore"], c["opera"], c["area"], c["importo"], c["note"]) == (1, 2, 2, 3, 4)
    assert (c["macro"], c["sottovoce"], c["quando"], c["iva"]) == (-1, -1, -1, -1)
    (m,) = r["L"]["livelli"]["macro"]
    assert m["nome"] == "Camere"
    assert [(v["nome"], v["fornitore_id"], v["area"], v["netto"]) for v in m["voci"]] == [
        ("Opere", "AMCN", "Opere", 1_226_379),
        ("Fornitura e posa", None, "Fornitura e posa", 240_000),
        ("Da comprare", "Flab", "Da comprare", 165_000),
    ]
    assert m["voci"][0]["mesi"] == {"2027-02": 1_226_379} and m["voci"][0]["aliquota_iva"] == 22
    assert m["voci"][0]["note"] == "pitture e cartongessi"
    assert r["L"]["da_sistemare"] == []


def test_import_righe_sporche(tmp_path):
    righe = [
        ["Macro", "Sottovoce", "Fornitore", "Totale netto €", "Quando"],
        ["Opere", "pitture", "AMCN", "30.000,00", "feb 27"],
        [None, "", None, None, ""],
        ["Opere", "cartongessi", "TBD", 5000, "boh"],
        ["Opere", "rasature", "-", "12.5x", ""],
        ["Opere", "TOTALE", "", 35000, ""],
    ]
    r = _formato(
        tmp_path,
        f"(() => {{ const r = {json.dumps(righe)}; const g = F.indovinaColonne(r);"
        " return JSON.stringify(F.livelliDaFoglio(r, g.colonne, {testa: g.testa, mese_default: '2027-01'})); })()",
    )
    (m,) = r["livelli"]["macro"]
    assert [(v["nome"], v["netto"], v["mesi"]) for v in m["voci"]] == [("pitture", 3_000_000, {"2027-02": 3_000_000})]
    assert r["da_sistemare"] == [{"n": 4, "motivo": "quando illeggibile"}, {"n": 5, "motivo": "importo illeggibile"}]


def test_diff_sostituisce_e_segnala(tmp_path):
    p = _progetto_tre_righe()
    # riga 3 (tende): cifra cambiata; riga 4 (AMCN) cancellata
    r = _formato(tmp_path, _giro(p, "r[3][4] = 25000; r.splice(4, 1);"))
    assert [(d["tipo"], d["macro"], d["sottovoce"]) for d in r["d"]] == [
        ("cambia", "Tessili", "tende"),
        ("sparisce", "Pitture", ""),
        ("sparisce", "Pitture", "pitture camere"),
    ]
    assert r["d"][0]["prima"]["netto"] == 2_200_000 and r["d"][0]["dopo"]["netto"] == 2_500_000
    assert "patti_persi" not in r["d"][0]
    # «Quando» cambiato su una voce con patti: i patti di quel fornitore cadono, i documenti restano
    r = _formato(tmp_path, _giro(p, "r[4][5] = 'mar 27';"))
    (d,) = r["d"]
    assert (d["tipo"], d["fornitore"], d["patti_persi"]) == ("cambia", "AMCN", True)
    assert r["dopo"]["contratti"] == []
    amcn = r["dopo"]["livelli"]["macro"][1]["voci"][0]
    assert amcn["mesi"] == {"2027-03": 3_000_000} and amcn["documenti"] == p["livelli"]["macro"][1]["voci"][0]["documenti"]
    assert amcn["id"] == "v1"


def test_import_in_una_macro_tocca_solo_quella(tmp_path):
    p = _progetto_tre_righe()
    righe = [["Fornitore", "Area di intervento", "Totale netto €"], ["AMCN", "Opere", 12000], ["Da assegnare", "Opere", 500]]
    r = _formato(
        tmp_path,
        f"(() => {{ const p = {json.dumps(p)}; const r = {json.dumps(righe)}; const g = F.indovinaColonne(r);"
        " const L = F.livelliDaFoglio(r, g.colonne, {testa: g.testa, macro_scelta: 'Tessili', mese_default: '2027-02', iva_default: 22});"
        " return JSON.stringify(F.applicaLivelli(p, L.livelli, {macro_scelta: 'Tessili'}).livelli); })()",
    )
    tessili, pitture = r["macro"]
    assert pitture == p["livelli"]["macro"][1]
    assert (tessili["id"], tessili["budget_netto"]) == ("m1", 4_000_000)
    assert [(v["nome"], v["fornitore_id"], v["netto"]) for v in tessili["voci"]] == [("Opere", "AMCN", 1_200_000), ("Opere", None, 50_000)]
    assert len({v["id"] for m in r["macro"] for v in m["voci"]}) == 3
    assert r["budget_netto"] == 16_500_000


def test_macro_cancellata_si_vede_nel_diff(tmp_path):
    p = _progetto_tre_righe()
    p["livelli"]["macro"].append(_macro("m3", "Arredi", []))
    r = _formato(tmp_path, _giro(p, "r.splice(5, 1);"))
    assert [(d["tipo"], d["macro"]) for d in r["d"]] == [("sparisce", "Arredi")]


def test_import_in_una_macro_senza_voci_tiene_la_macro(tmp_path):
    p = _progetto_tre_righe()
    righe = [["Fornitore", "Area di intervento", "Totale netto €"], ["Da assegnare", "Opere", 0]]
    r = _formato(
        tmp_path,
        f"(() => {{ const p = {json.dumps(p)}; const r = {json.dumps(righe)}; const g = F.indovinaColonne(r);"
        " const L = F.livelliDaFoglio(r, g.colonne, {testa: g.testa, macro_scelta: 'Tessili', mese_default: '2027-02'});"
        " return JSON.stringify({d: F.diffLivelli({macro: [{...p.livelli.macro[0], budget_netto: null}]}, L.livelli),"
        " L: F.applicaLivelli(p, L.livelli, {macro_scelta: 'Tessili'}).livelli}); })()",
    )
    tessili = r["L"]["macro"][0]
    vecchia = p["livelli"]["macro"][0]
    assert tessili == {**vecchia, "voci": []}
    assert (tessili["budget_netto"], tessili["mesi_budget"]) == (4_000_000, {"2027-01": 1, "2027-03": 2})
    assert [(d["tipo"], d["sottovoce"]) for d in r["d"]] == [("sparisce", "tende")]


def test_quando_percentuali_che_non_fanno_cento(tmp_path):
    r = _formato(
        tmp_path,
        "JSON.stringify([F.quandoParse('mar 27 30% · giu 27 60%', 1000000),"
        " F.quandoParse('mar 27 33,33% · giu 27 33,33% · set 27 33,34%', 100),"
        " F.quandoParse('mar 27 33% · giu 27 33% · set 27 33%', 100)])",
    )
    assert r[0] is None
    assert r[1] == {"2027-03": 33, "2027-06": 33, "2027-09": 34}
    assert r[2] is None


def test_iva_solo_aliquote_valide_e_colonna_iva_importo(tmp_path):
    netto_iva_lordo = [["Fornitore", "Descrizione", "Netto", "IVA", "Lordo"], ["AMCN", "pitture", 1000, 220, 1220]]
    con_aliquota = [
        ["Fornitore", "Descrizione", "Totale netto €", "IVA %"],
        ["AMCN", "pitture", 1000, 22],
        ["STE", "impianti", 2000, 21],
        ["Flab", "lampade", 300, "10%"],
    ]
    r = _formato(
        tmp_path,
        f"(() => {{ const a = {json.dumps(netto_iva_lordo)}, b = {json.dumps(con_aliquota)};"
        " const ga = F.indovinaColonne(a), gb = F.indovinaColonne(b);"
        " const opz = {macro_scelta: 'Opere', mese_default: '2027-02', iva_default: 22};"
        " return JSON.stringify({ga: ga.colonne, gb: gb.colonne, A: F.livelliDaFoglio(a, ga.colonne, opz),"
        " B: F.livelliDaFoglio(b, gb.colonne, opz),"
        " intest: ['IVA %', 'iva%', 'Aliquota', 'IVA % applicata', 'IVA', 'Totale IVA'].map((h) =>"
        " F.indovinaColonne([['Fornitore', 'Voce', h]]).colonne.iva)}); })()",
    )
    assert r["ga"]["iva"] == -1 and r["ga"]["importo"] == 2
    assert r["A"]["livelli"]["macro"][0]["voci"][0]["aliquota_iva"] == 22  # iva_default, non 220
    assert r["gb"]["iva"] == 3
    voci = r["B"]["livelli"]["macro"][0]["voci"]
    assert [(v["fornitore_id"], v["aliquota_iva"]) for v in voci] == [("AMCN", 22), ("Flab", 10)]
    assert r["B"]["da_sistemare"] == [{"n": 3, "motivo": "IVA illeggibile"}]
    assert r["intest"] == [2, 2, 2, 2, -1, -1]


def test_budget_senza_quando_prende_il_mese_scelto(tmp_path):
    righe = [
        ["Macro", "Sottovoce", "Fornitore", "Totale netto €", "Quando"],
        ["budget progetto", "", "", 165000, ""],
        ["Tessili", "budget", "", 40000, ""],
    ]
    r = _formato(
        tmp_path,
        f"(() => {{ const r = {json.dumps(righe)}; const g = F.indovinaColonne(r);"
        " return JSON.stringify([F.livelliDaFoglio(r, g.colonne, {testa: g.testa, mese_default: '2027-01'}),"
        " F.livelliDaFoglio(r, g.colonne, {testa: g.testa})]); })()",
    )
    con, senza = r
    assert (con["livelli"]["budget_netto"], con["livelli"]["mesi_budget"]) == (16_500_000, {"2027-01": 16_500_000})
    assert con["livelli"]["macro"][0]["mesi_budget"] == {"2027-01": 4_000_000}
    assert con["da_sistemare"] == []
    assert senza["da_sistemare"] == [{"n": 2, "motivo": "budget senza mesi"}, {"n": 3, "motivo": "budget senza mesi"}]
    assert senza["livelli"]["budget_netto"] is None


def test_template_progetti_a_livelli():
    # Dentro il progetto una tabella a livelli: budget del progetto, macro, sottovoci; si aggiunge scrivendo
    # nell'ultima riga vuota. Ogni modifica rideriva i pagamenti (il calcolo legge solo quelli).
    html = render_html(build_payload(snapshot_sintetico(), []))
    for pezzo in ("function aggiornaProgetto(p)", "p.pagamenti = FORMATO.derivaPagamenti(p, D.mesi);", "data-nuova-macro", "data-nuova-voce",
                  "data-budget-progetto", "data-budget-macro", '"cdg-cassa-scenario/2"', "FORMATO.avvisiLivelli(p.livelli, D.mesi)",
                  'class="livelli"', "data-elimina-macro", "data-conferma-macro"):
        assert pezzo in html, pezzo
    # il vecchio «+ pagamento» sparisce: si scrive nella riga vuota
    assert "button[data-aggiungi-g]" not in html and "data-aggiungi-g" not in html
    # all'apertura ogni progetto ha i suoi livelli (un progetto /1 diventa una macro col suo nome)
    assert "FORMATO.livelliDaPagamenti(q)" in html
    # oltre budget: «oltre di X ⚠», mai un «da assegnare» negativo
    assert "oltre di ${fmt(b.oltre, false)} ⚠" in html
    # le aree di hpan26-soft
    assert '"Opere", "Fornitura e posa", "Da comprare"' in html


def test_js_leggi_documento_accetta_scenario_1_e_2(tmp_path):
    # Un file esportato prima dei livelli (/1) si apre ancora; uno di un altro tipo no.
    p = build_payload(snapshot_sintetico(), [])
    html = render_html(p)
    sc, _ = scenario_sintetico()
    doc = json.loads(scenario_to_json(sc, p["base"]))
    vecchio = dict(doc, schema="cdg-cassa-scenario/1")
    (tmp_path / "doc1.json").write_text(json.dumps(vecchio), encoding="utf-8")
    (tmp_path / "doc2.json").write_text(json.dumps(doc), encoding="utf-8")
    out = esegui_node_formato(
        tmp_path,
        html,
        "(() => { const fs = require('fs');"
        " const a = F.leggiDocumento(fs.readFileSync('./doc1.json', 'utf8'), 'cdg-cassa-scenario/2');"
        " const b = F.leggiDocumento(fs.readFileSync('./doc2.json', 'utf8'), 'cdg-cassa-scenario/2');"
        " const c = F.leggiDocumento(JSON.stringify({schema: 'cdg-cassa-scenario/3'}), 'cdg-cassa-scenario/2');"
        " return JSON.stringify([a.errore || null, b.errore || null, c.errore || null]); })()",
    )
    a, b, c = json.loads(out)
    assert a is None and b is None
    assert c and "cdg-cassa-scenario/3" in c


# Un progetto come il terzo piano scritto prima dei livelli: anticipo, 5 SAL e ritenuta AMCN una riga ciascuno,
# i patti da 482.000 e un altro fornitore. IVA 10% per vedere anche l'IVA.
PIANO3_JS = (
    "(() => { const m = D.mesi, r = (nome, mese, cent) => ({ nome, mesi: { [mese]: cent }, aliquota_iva: 10, stato: 'contratto', fornitore_id: 'AMCN' });"
    " return { id: 'P3', nome: 'Terzo piano', societa: 'INTUR', acceso: true, stato: 'contratto',"
    " pagamenti: [r('AMCN · anticipo 15%', m[0], 7230000), ...[1, 2, 3, 4, 5].map((k) => r(`AMCN · SAL ${k}/5`, m[k], 7230000)),"
    " r('AMCN · svincolo ritenuta 10%', m[7], 4820000),"
    " { nome: 'Impianti STE', mesi: { [m[2]]: 5000000 }, aliquota_iva: 22, stato: 'ipotesi', fornitore_id: 'STE' }],"
    " contratti: [{ fornitore: 'AMCN', totale: 48200000, aliquota_iva: 10, stato: 'contratto', modo: 'sal', anticipo_pct: 15, anticipo_mese: m[0],"
    " ritenuta_pct: 10, svincolo_mese: m[7], sal_modo: 'n', sal_n: 5, sal_ogni: 0, sal_da: m[1], sal_passo: 1, quote: [] }] }; })()"
)


def test_js_conversione_consolida_le_rate_dei_patti(tmp_path):
    # Alla conversione le 7 righe AMCN tornano una sottovoce legata ai patti: cassa identica al centesimo.
    # Se i totali non tornano, o due righe cadono nello stesso mese, non si tocca niente e i patti restano slegati.
    html = render_html(build_payload(snapshot_sintetico(), []))
    out = esegui_node_fn(
        tmp_path,
        html,
        "(() => { const F = require('./formato.js'); const P = " + PIANO3_JS + ";"
        " const conv = (p) => { const q = F.consolidaContratti({ ...p, livelli: F.livelliDaPagamenti(p) }); q.pagamenti = F.derivaPagamenti(q, D.mesi); return q; };"
        " const sc = (p) => ({ ...D.seme.scenario, progetti: [p] });"
        " const q = conv(P), a = M.calcola(D, sc(P)), b = M.calcola(D, sc(q));"
        " const storto = conv({ ...P, contratti: [{ ...P.contratti[0], totale: 48199999 }] });"
        " const doppio = conv({ ...P, pagamenti: P.pagamenti.map((g, i) => (i === 1 ? { ...g, mesi: { [D.mesi[2]]: 7230000 } } : g)) });"
        " return JSON.stringify({ voci: q.livelli.macro[0].voci.map((v) => [v.nome, v.fornitore_id, v.netto, Object.keys(v.mesi).length]),"
        " legata: q.contratti[0].voce_id, idVoce: q.livelli.macro[0].voci[0].id, uguali: JSON.stringify(a.righe) === JSON.stringify(b.righe),"
        " storto: [storto.livelli.macro[0].voci.length, storto.contratti[0].voce_id || null],"
        " doppio: [doppio.livelli.macro[0].voci.length, doppio.contratti[0].voce_id || null] }); })()",
    )
    r = json.loads(out)
    assert r["voci"] == [["AMCN", "AMCN", 48200000, 7], ["Impianti STE", "STE", 5000000, 1]]
    assert r["legata"] == r["idVoce"] and r["uguali"] is True
    assert r["storto"] == [8, None] and r["doppio"] == [8, None]


def test_js_genera_scrive_solo_la_sottovoce_dei_patti(tmp_path):
    # «Genera» con patti diversi ma stesso totale: cambiano solo i mesi della sottovoce legata, il totale del
    # progetto no; le altre sottovoci restano identiche. Mai unire: un fornitore con due sottovoci e patti
    # slegati dà un errore leggibile invece di scegliere.
    html = render_html(build_payload(snapshot_sintetico(), []))
    out = esegui_node_fn(
        tmp_path,
        html,
        "(() => { const F = require('./formato.js'); const P = " + PIANO3_JS + ";"
        " const q = F.consolidaContratti({ ...P, livelli: F.livelliDaPagamenti(P) }); q.pagamenti = F.derivaPagamenti(q, D.mesi);"
        " q.contratti[0] = { ...q.contratti[0], sal_n: 3, sal_passo: 2 };"
        " const r = F.generaPatti(q, 0, D.mesi), g = r.progetto; g.pagamenti = F.derivaPagamenti(g, D.mesi);"
        " const lordo = (p) => p.pagamenti.reduce((t, x) => t + Object.values(x.mesi).reduce((s, v) => s + M.iva(v, x.aliquota_iva), 0), 0);"
        " const v0 = q.livelli.macro[0].voci, v1 = g.livelli.macro[0].voci;"
        " const slegato = { ...P, livelli: F.livelliDaPagamenti(P) };"
        " return JSON.stringify({ voce: r.voce_id === v0[0].id, mesiPrima: Object.keys(v0[0].mesi).length, mesiDopo: Object.keys(v1[0].mesi).length,"
        " netto: [v0[0].netto, v1[0].netto], altra: JSON.stringify(v0[1]) === JSON.stringify(v1[1]), nVoci: v1.length,"
        " lordo: [lordo(q), lordo(g)], errore: F.generaPatti(slegato, 0, D.mesi).errore || null }); })()",
    )
    r = json.loads(out)
    assert r["voce"] and r["nVoci"] == 2 and r["altra"]
    assert r["mesiPrima"] == 7 and r["mesiDopo"] != 7 and r["netto"] == [48200000, 48200000]
    assert r["lordo"][0] == r["lordo"][1]
    assert r["errore"] and "7 sottovoci" in r["errore"]
