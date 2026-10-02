"""Simulatore canone ORTI → INTUR: motore, scenari, fonti, montaggio nel hub.

Fixture SINTETICA (numeri tondi inventati): i dati reali del BP restano fuori da git.
Il test di replica sull'Excel gira solo se il file locale esiste.
"""

import inspect
import json
from datetime import date, datetime

import pytest

from verticals.condges import canone_fonti as cf
from verticals.condges import canone_sim as cs


def _anno(y, ricavi, rate_i):
    return {
        "year": y,
        "orti": {"revenue": ricavi, "operatingCostRate": 0.6, "angelinaRent": 100_000,
                 "depreciation": 100_000, "interest": 50_000, "debtService": 400_000,
                 "revenueBreakdown": {"rooms": ricavi * 0.6, "otherHotel": ricavi * 0.4}},
        "intur": {"beachRevenue": 100_000, "otherRentRevenue": 150_000 if y <= 2028 else 50_000,
                  "operatingCosts": 500_000, "depreciation": 300_000, "interest": 60_000,
                  "reserveReleasePayment": 0, "debtService": rate_i,
                  "debtServiceBreakdown": {"existing": rate_i - 100_000, "sal": 60_000, "mcc": 40_000},
                  "cashBridge": {"newLoanDrawdowns": 0, "investmentSpend": 0,
                                 "investmentVATPaid": 0, "investmentVATRecovered": 0}},
    }


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("CANONE_SIM_HOME", str(tmp_path))
    doc = {
        "source": "sintetico.xlsx", "sourceSHA256": "abc123",
        "common": {"taxRate": 0.25, "maintenanceRate": 0.01, "workingCapitalRate": 0.05,
                   "targetDSCR": 1.2, "bandPosition": 0.5, "roundingEUR": 1000},
        "prior2025": {"ortiRevenue": 3_800_000, "inturRevenue": 1_000_000, "inturClosingCash": 100_000},
        "prior2026": {"ortiRevenue": 4_000_000, "inturRevenue": 1_050_000,
                      "inturClosingCash": 200_000, "appliedRent": 800_000},
        "years": {str(y): _anno(y, 4_000_000 * 1.05 ** (y - 2026), 300_000) for y in range(2026, 2032)},
        "sourceCells": {"common": "Assunzioni!B1:B4"},
        "contractDraft": {"2027": 800_000, "2028": 850_000, "2029": 900_000, "2030": 900_000, "2031": 900_000},
    }
    # coerenza della base: cassa/ricavi INTUR 2026 = quelli che il motore calcola
    grezzo = cs.load_inputs(json.dumps(doc).encode())
    r26 = cs.riga_2026(grezzo)
    doc["prior2026"]["inturRevenue"] = r26["ricavi_i"]
    doc["prior2026"]["inturClosingCash"] = r26["cassa_i"]
    return cs.load_inputs(json.dumps(doc).encode())


def test_base_usa_la_bozza_e_le_crescite_del_bp(inputs):
    base = cs.scenario_base(inputs)
    assert [base["anni"][y]["canone"] for y in cs.anni(inputs)] == [800_000, 850_000, 900_000, 900_000, 900_000]
    assert base["anni"][2027]["crescita"] == pytest.approx(0.05)
    assert cs.modifiche(inputs, base) == []


def test_canone_fermo_quando_cambiano_ricavi_e_costi(inputs):
    s = cs.scenario_base(inputs)
    prima = cs.calculate(inputs, s)
    s["anni"][2028]["crescita"] = -0.10
    s["anni"][2029]["costi"] = 0.70
    dopo = cs.calculate(inputs, s)
    assert [r["canone"] for r in dopo] == [r["canone"] for r in prima]
    assert dopo[1]["dscr_o"] < prima[1]["dscr_o"]
    assert dopo[2]["cfads_o"] < prima[2]["cfads_o"]


def test_ricavi_e_crescita_sono_la_stessa_leva(inputs):
    s = cs.scenario_base(inputs)
    cs.imposta_ricavi(inputs, s, 2028, 5_000_000)
    r = {x["anno"]: x for x in cs.calculate(inputs, s)}
    assert r[2028]["ricavi_o"] == pytest.approx(5_000_000)
    assert s["anni"][2028]["crescita"] == pytest.approx(5_000_000 / r[2027]["ricavi_o"] - 1)
    # gli anni dopo tengono la loro crescita %
    assert r[2029]["ricavi_o"] == pytest.approx(5_000_000 * 1.05)


def test_scaletta_decrescente_rifiutata(inputs):
    s = cs.scenario_base(inputs)
    assert cs.errori_scaletta(inputs, s) == []
    s["anni"][2029]["canone"] = 840_000
    assert any("2029" in e for e in cs.errori_scaletta(inputs, s))
    s = cs.scenario_base(inputs)
    s["anni"][2027]["canone"] = 700_000  # sotto il 2026
    assert any("2027" in e for e in cs.errori_scaletta(inputs, s))


def test_gruppo_e_somma_cfads_su_somma_rate(inputs):
    for r in cs.calculate(inputs, cs.scenario_base(inputs)):
        atteso = (r["cfads_o"] + r["cfads_i"]) / (r["rate_o"] + r["rate_i"])
        assert r["dscr_g"] == pytest.approx(atteso)
        assert r["dscr_g"] != pytest.approx((r["dscr_o"] + r["dscr_i"]) / 2)


def test_anni_in_sequenza_il_canone_di_un_anno_tocca_il_successivo(inputs):
    s = cs.scenario_base(inputs)
    prima = cs.calculate(inputs, s)
    s["anni"][2027]["canone"] = 850_000
    dopo = cs.calculate(inputs, s)
    assert dopo[1]["canone"] == prima[1]["canone"]
    assert dopo[1]["ccn_i"] != pytest.approx(prima[1]["ccn_i"])  # circolante INTUR 2028
    assert dopo[1]["cassa_i"] > prima[1]["cassa_i"]  # la cassa 2027 si riporta


def test_dettaglio_orti_e_intur_chiudono_sul_cfads(inputs):
    r = cs.calculate(inputs, cs.scenario_base(inputs))[0]
    orti = r["ricavi_o"] - r["costi_o"] - r["canone"] - r["angelina_o"] - r["tax_o"] - r["man_o"] - r["ccn_o"]
    assert orti == pytest.approx(r["cfads_o"])
    intur = (r["altri_ricavi_i"] + r["canone"] - r["costi_i"] - r["tax_i"] - r["man_i"]
             - r["ccn_i"] - r["affr_i"])
    assert intur == pytest.approx(r["cfads_i"])


def test_canone_di_equilibrio_pareggia_i_dscr_senza_toccare_la_scaletta(inputs):
    s = cs.scenario_base(inputs)
    prima = cs.copia(s)
    eq = cs.canone_equilibrio(inputs, s, 2028)
    assert s == prima  # diagnostica: non riscrive nulla
    s["anni"][2028]["canone"] = eq
    r = cs.calculate(inputs, s)[1]
    assert r["dscr_o"] == pytest.approx(r["dscr_i"], abs=1e-6)


def test_angelina_a_terzi_toglie_ricavi_a_intur_solo_2027_28(inputs):
    s = cs.scenario_base(inputs)
    base = cs.calculate(inputs, s)
    s["angelina"] = cs.ANGELINA_TERZI
    terzi = cs.calculate(inputs, s)
    assert terzi[0]["altri_ricavi_i"] == base[0]["altri_ricavi_i"] - 100_000
    assert terzi[0]["angelina_a_intur"] == 0
    assert terzi[2]["altri_ricavi_i"] == base[2]["altri_ricavi_i"]
    assert [r["canone"] for r in terzi] == [r["canone"] for r in base]


def test_scenario_salva_riapri_ed_esporta(inputs):
    s = cs.scenario_base(inputs)
    s["nome"] = "Prova crescente"
    s["anni"][2031]["canone"] = 950_000
    path = cs.salva_scenario(inputs, s)
    doc = json.loads(path.read_text())
    assert doc["nome"] == "Prova crescente" and doc["salvato_il"] and doc["fonte"]["sha256_fonte"] == "abc123"
    riaperto = cs.scenari_salvati(inputs)["Prova crescente"]
    assert riaperto["anni"] == s["anni"]
    assert cs.modifiche(inputs, riaperto) == [{"anno": 2031, "campo": "canone", "base": 900_000, "valore": 950_000}]
    # lo snapshot dei dati di base viene archiviato accanto allo scenario
    assert (cs.home() / "inputs" / f"{inputs['_sha256'][:12]}.json").exists()


def test_import_avvisa_se_i_dati_di_base_sono_cambiati(inputs):
    testo = cs.scenario_to_json(inputs, cs.scenario_base(inputs))
    _, avvisi = cs.scenario_from_json(inputs, testo)
    assert avvisi == []
    altro = dict(inputs, _sha256="diverso")
    _, avvisi = cs.scenario_from_json(altro, testo)
    assert len(avvisi) == 1


def test_inputs_path_spostabile_da_env(monkeypatch):
    monkeypatch.setenv("CANONE_SIM_INPUTS", "/secrets/canone/model-inputs.json")
    assert str(cs.inputs_path()) == "/secrets/canone/model-inputs.json"


def test_import_rifiuta_file_estranei_e_scalette_decrescenti(inputs):
    with pytest.raises(ValueError):
        cs.scenario_from_json(inputs, json.dumps({"schema": "altro"}))
    doc = json.loads(cs.scenario_to_json(inputs, cs.scenario_base(inputs)))
    doc["anni"]["2030"]["canone"] = 100
    with pytest.raises(ValueError):
        cs.scenario_from_json(inputs, json.dumps(doc))


# ── fonti ─────────────────────────────────────────────────────────────────────


def _finta_query(sql):
    if "f_produzione_pms" in sql:
        riga = {"dal": date(2026, 4, 1), "al": date(2026, 9, 1), "caricato": datetime(2026, 9, 2)}
        return [
            {"business_unit_id": "HOTEL", "classe": "01ROOM", "importo": 1000, **riga},
            {"business_unit_id": "HOTEL", "classe": "02FB", "importo": 200, **riga},
            {"business_unit_id": "HOTEL", "classe": "80AFFITT", "importo": 50, **riga},
            {"business_unit_id": "RESIDENCE", "classe": "01ROOM", "importo": 300, **riga},
            {"business_unit_id": "RESIDENCE", "classe": "04BEALL", "importo": 10, **riga},
        ]
    if "f_bilancino" in sql:
        return [{"societa_id": "ORTI", "mese": "2026-09", "ricavi": 900.0, "costi": 500.0,
                 "canone": 100.0, "caricato": "2026-09-25"}]
    raise PermissionError("accesso negato")


def test_adapter_classificano_e_una_fonte_che_fallisce_risulta_bloccata(inputs):
    snap = cf.salva_osservati(cf.aggiorna(query=_finta_query, adesso=datetime(2026, 10, 1, 12)))
    v = snap["fonti"]["pms"]["dati"]["valori"]
    assert (v["hotel_camere"], v["hotel_altri"], v["affitti"], v["residence"], v["spiaggia_ospiti"]) == (1000, 200, 50, 300, 10)
    assert snap["fonti"]["bilancino"]["dati"]["ORTI"]["parziale"] is True
    assert snap["fonti"]["saldi"]["stato"] == cf.BLOCCATA and "dati" not in snap["fonti"]["saldi"]
    stato = {r["fonte"]: r for r in cf.stato_fonti(inputs, snap)}
    assert stato["Banche · saldi di fine mese"]["stato"].startswith("BLOCCATA")
    assert {r["tipo"] for r in stato.values()} == {cf.OSSERVATO, cf.IMPEGNO, cf.IPOTESI}


def test_fonte_bloccata_conserva_l_ultimo_dato_buono_con_la_sua_data(inputs):
    cf.salva_osservati(cf.aggiorna(query=_finta_query, adesso=datetime(2026, 10, 1, 12)))

    def tutto_giu(sql):
        raise ConnectionError("rete assente")

    snap = cf.salva_osservati(cf.aggiorna(query=tutto_giu, adesso=datetime(2026, 10, 2, 9)))
    pms = cf.carica_osservati()["fonti"]["pms"]
    assert pms["stato"] == cf.BLOCCATA
    assert pms["dati"]["valori"]["hotel_camere"] == 1000
    assert pms["dati_del"].startswith("2026-10-01")  # non si spaccia per aggiornato
    assert snap["acquisito_il"].startswith("2026-10-02")


# ── hub ───────────────────────────────────────────────────────────────────────


def test_registry_ha_canone_sensibile_e_admin_lo_vede():
    from verticals.hub.pages_ import canone
    from verticals.hub.registry import APPS
    from verticals.hub.roles import FINANZA, _resolve

    app = {a.id: a for a in APPS}["canone"]
    assert app.kind == "page" and app.group == "Finanza" and app.sensitive is True
    assert "canone" not in FINANZA  # dati riservati: non si eredita dal gruppo (S1)
    assert "canone" in _resolve("stefano@panoramagroup.it", allow_all=False)
    assert "set_page_config" not in inspect.getsource(canone.render)
    assert canone.CANONE_URL == "https://canone.panorama-host.com/"


# ── replica dell'Excel (solo in locale, con i dati reali fuori da git) ─────────

_REALI = cs.inputs_path()


@pytest.mark.skipif(not _REALI.exists(), reason="dati reali del BP non presenti (fuori da git)")
def test_replica_del_bp_con_canone_automatico():
    inputs = cs.load_inputs(_REALI.read_bytes())
    righe = [cs.riga_2026(inputs), *cs.calculate(inputs, cs.scenario_base(inputs), canone_automatico=True)]
    for r in righe:
        e = inputs["years"][str(r["anno"])]["expected"]
        assert r["canone"] == pytest.approx(e["appliedRent"], abs=1e-6)
        assert r["cfads_o"] == pytest.approx(e["ortiCFADS"], abs=1e-6)
        assert r["cfads_i"] == pytest.approx(e["inturCFADS"], abs=1e-6)
        assert r["dscr_o"] == pytest.approx(e["ortiDSCR"], abs=1e-9)
        assert r["dscr_i"] == pytest.approx(e["inturDSCR"], abs=1e-9)


# ── cruscotto HTML: il motore nel browser deve dare gli stessi numeri di Python ──


def test_cruscotto_html_calcola_come_python(inputs, tmp_path):
    import re
    import shutil
    import subprocess

    from verticals.condges import build_canone_artifact as build

    html = build.render_html(build.build_payload(inputs, None, datetime(2026, 10, 1, 12)))
    assert "__DATA__" not in html and "expected" not in html
    if shutil.which("node") is None:
        pytest.skip("node non installato")
    dati = re.search(r'<script type="application/json" id="dati">(.*?)</script>', html, re.S).group(1)
    motore = re.search(r'<script id="motore">(.*?)</script>', html, re.S).group(1)
    (tmp_path / "motore.js").write_text(motore, encoding="utf-8")
    (tmp_path / "dati.json").write_text(dati.replace("<\\/", "</"), encoding="utf-8")
    (tmp_path / "run.js").write_text(
        "const M=require('./motore.js'),D=require('./dati.json');"
        "const sc=M.copia(D.base);sc.anni[2028].crescita=-0.03;sc.anni[2029].costi=0.66;sc.angelina='terzi';"
        "console.log(JSON.stringify({base:M.calcola(D,D.base),mod:M.calcola(D,sc),"
        "r26:M.riga2026(D),eq:M.equilibrio(D,D.base,2028),lim:M.limiti(D,D.base,2029)}));",
        encoding="utf-8",
    )
    out = json.loads(subprocess.run(["node", "run.js"], cwd=tmp_path, capture_output=True, text=True, check=True).stdout)

    s = cs.scenario_base(inputs)
    mod = cs.copia(s)
    mod["anni"][2028]["crescita"], mod["anni"][2029]["costi"], mod["angelina"] = -0.03, 0.66, cs.ANGELINA_TERZI
    chiavi = ("canone", "ricavi_o", "cfads_o", "cfads_i", "dscr_o", "dscr_i", "dscr_g", "cassa_i",
              "canone_min_intur", "canone_max_orti", "manca_i", "tax_o", "ccn_i")
    for js, py in ((out["base"], cs.calculate(inputs, s)), (out["mod"], cs.calculate(inputs, mod)),
                   ([out["r26"]], [cs.riga_2026(inputs)])):
        assert len(js) == len(py)
        for a, b in zip(js, py):
            for k in chiavi:
                assert a[k] == pytest.approx(b[k], rel=1e-12, abs=1e-6), (b["anno"], k)
    assert out["eq"] == pytest.approx(cs.canone_equilibrio(inputs, s, 2028), abs=1e-3)
    assert out["lim"] == [s["anni"][2028]["canone"], s["anni"][2030]["canone"]]


def test_push_cruscotto_scrive_solo_la_chiave_html(monkeypatch):
    import requests

    from verticals.condges import build_canone_artifact as build

    for k in build.PUSH_ENV_VARS:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError):
        build.load_push_env()

    chiamate = []

    class _Risposta:
        ok, status_code, text = True, 200, ""

        def json(self):
            return {"success": True}

    def finta_put(url, json, headers, timeout):
        chiamate.append((url, json, headers))
        return _Risposta()

    monkeypatch.setattr(requests, "put", finta_put)
    build.push_to_kv("<html>x</html>", {"CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "acc"})
    url, corpo, headers = chiamate[0]
    assert url.endswith(f"/accounts/acc/storage/kv/namespaces/{build.KV_NAMESPACE_ID}/bulk")
    assert corpo == [{"key": "html", "value": "<html>x</html>"}]
    assert headers == {"Authorization": "Bearer t"}
