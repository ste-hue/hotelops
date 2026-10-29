import json
import re
import shutil
import subprocess
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest

from tests.test_cassa_scenario import scenario_sintetico
from verticals.condges.build_cassa_artifact import (
    KV_DATA_KEY,
    KV_KEY,
    PUSH_ENV_VARS,
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


def test_limiti_dicono_ipotetici_e_fatti_non_riconciliati():
    testo = " ".join(build_payload(snapshot_sintetico(), [])["limiti"]).lower()
    assert "ipotetic" in testo and "2027-04" in testo
    assert (
        "senza mese omologo nel pf, quindi a zero movimenti: 2027-04, 2027-05, 2027-06"
        in testo
    )
    assert "non riconciliat" in testo and "iva" in testo


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
    assert "rate dei nuovi finanziamenti assenti: mcc 550.000" in testo
    assert "finanziamenti da verificare: mcc 550.000" in testo
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
    assert "Esporta scenario" in html and "prefers-color-scheme" in html
    assert "non conta finché il progetto è spento" in html
    assert "attestato" in html and "dichiarato" in html


# ── parità JS/Python: interi, nessun round ──


def test_js_uguale_a_python(tmp_path):
    snap = snapshot_sintetico()
    p = build_payload(snap, [])
    sc, _ = _scenario_base()
    out = esegui_node(tmp_path, render_html(p), p, scenario_to_json(sc, p["base"]))
    assert out == to_dict(calcola(input_da_snapshot(snap, sc)))


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
