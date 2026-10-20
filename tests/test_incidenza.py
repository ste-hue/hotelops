"""Test della base di calcolo dell'incidenza costi (issue #157, PR #158 §6).

Due famiglie:
- offline (sempre): composizione del rapporto per perimetro/natura/periodo e confronto con il limite
  versionato, senza default e senza arrotondamenti;
- @pytest.mark.bq: il SQL di v_incidenza_costi_componenti eseguito DAVVERO su BigQuery contro una
  fixture inline (UNNEST di STRUCT) che sostituisce f_bilancino e d_categorie_conti — prova il
  comportamento della vista sui casi del contratto senza deployarla e senza toccare tabelle — più uno
  smoke sul dato reale (ORTI 2026-09) che deve riprodurre i totali del ponte dei conti.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from verticals.condges.incidenza import (
    Componenti,
    Limite,
    Natura,
    Perimetro,
    Periodo,
    numeratore,
    rapporto,
    valuta,
)

VIEW_SQL = (
    Path(__file__).resolve().parents[1]
    / "core"
    / "bq"
    / "views"
    / "v_incidenza_costi_componenti.sql"
)

LIMITE_65 = Limite(
    valore=0.65,
    verso="max",
    versione="2026-10-18",
    fonte="hotelops#157 commento 6247553610",
)

# Totali del ponte dei conti ORTI al 30/09/2026 (docs/reports/2026-10-18-cdg-ponte-conti-65.md).
ORTI_SET = Componenti(
    ricavi_totali=4_322_454.0,
    costi_55_71=2_954_318.0,
    canone_651101=600_000.0,
    angelina_65010591=60_000.0,
    cvm_65010590=100_000.0,
    servizi_bancari_75=82_142.0,
    oneri_finanziari_75=86_212.0,
)


# ───────────────────────── offline: composizione e limite ─────────────────────────


@pytest.mark.parametrize(
    "perimetro, natura, atteso",
    [
        (Perimetro.Q1_PIANO, Natura.CLASSE, 0.531),
        (Perimetro.Q2_INTERCOMPANY, Natura.NATURA, 0.550),
        (Perimetro.Q3_FITTI_GRUPPO, Natura.CLASSE, 0.508),
        (Perimetro.Q4_FITTI_GRUPPO_NATURA, Natura.NATURA, 0.527),
        (Perimetro.Q5_SOLO_CANONE, Natura.NATURA, 0.564),
        (Perimetro.R0_STANDALONE_PIENO, Natura.NATURA, 0.702),
    ],
)
def test_varianti_del_ponte_riprodotte(perimetro, natura, atteso):
    r = rapporto(ORTI_SET, perimetro, natura, Periodo.YTD)
    assert r is not None
    assert round(r, 3) == atteso


def test_nessun_default():
    with pytest.raises(ValueError):
        numeratore(ORTI_SET, None, Natura.CLASSE)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        rapporto(ORTI_SET, Perimetro.Q1_PIANO, Natura.CLASSE, None)  # type: ignore[arg-type]


def test_ricavi_zero_o_assenti_non_determinabile():
    zero = Componenti(0.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    assente = Componenti(None, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    assert rapporto(zero, Perimetro.Q5_SOLO_CANONE, Natura.CLASSE, Periodo.YTD) is None
    assert (
        rapporto(assente, Perimetro.Q5_SOLO_CANONE, Natura.CLASSE, Periodo.YTD) is None
    )
    assert valuta(None, LIMITE_65) == "non_valutabile"


def test_mese_non_derivabile_propaga_none():
    c = Componenti(1000.0, None, None, None, None, None, None)
    assert rapporto(c, Perimetro.Q1_PIANO, Natura.CLASSE, Periodo.MESE) is None


def test_componente_escluso_mancante_non_imputato_a_zero():
    c = Componenti(
        1000.0,
        800.0,
        canone_651101=None,
        angelina_65010591=0.0,
        cvm_65010590=0.0,
        servizi_bancari_75=0.0,
        oneri_finanziari_75=0.0,
    )
    assert numeratore(c, Perimetro.Q5_SOLO_CANONE, Natura.CLASSE) is None
    assert numeratore(c, Perimetro.R0_STANDALONE_PIENO, Natura.CLASSE) == 800.0


def test_rapporto_non_limitato_a_uno():
    gennaio = Componenti(26_561.0, 56_603.0, 0.0, 0.0, 0.0, 0.0, 603.0)
    r = rapporto(gennaio, Perimetro.Q5_SOLO_CANONE, Natura.CLASSE, Periodo.YTD)
    assert r is not None and r > 2.0
    assert valuta(r, LIMITE_65) == "oltre"


@pytest.mark.parametrize(
    "r, esito",
    [
        (0.65, "al_limite"),
        (0.6500000001, "oltre"),
        (0.651, "oltre"),
        (0.66, "oltre"),
        (0.6499999999, "entro"),
        (0.5, "entro"),
    ],
)
def test_limite_non_arrotondato(r, esito):
    assert valuta(r, LIMITE_65) == esito


def test_limite_solo_verso_max():
    with pytest.raises(ValueError):
        Limite(0.65, "min", "x", "y")


@pytest.mark.parametrize("v", [float("nan"), float("inf"), float("-inf")])
def test_limite_non_finito_rifiutato(v):
    with pytest.raises(ValueError):
        Limite(v, "max", "x", "y")


@pytest.mark.parametrize("r", [float("nan"), float("inf"), float("-inf"), None])
def test_rapporto_non_finito_mai_entro(r):
    assert valuta(r, LIMITE_65) == "non_valutabile"


def test_componenti_non_finiti_non_determinabili():
    nan = float("nan")
    q5, cl, yt = Perimetro.Q5_SOLO_CANONE, Natura.CLASSE, Periodo.YTD
    assert rapporto(Componenti(nan, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0), q5, cl, yt) is None
    assert (
        rapporto(Componenti(1000.0, nan, 0.0, 0.0, 0.0, 0.0, 0.0), q5, cl, yt) is None
    )
    assert (
        rapporto(Componenti(1000.0, 800.0, nan, 0.0, 0.0, 0.0, 0.0), q5, cl, yt) is None
    )
    inf = Componenti(1000.0, 800.0, 0.0, 0.0, 0.0, float("inf"), 0.0)
    assert rapporto(inf, q5, Natura.NATURA, yt) is None
    assert rapporto(inf, q5, cl, yt) == 0.8


# ───────────────────────── SQL della vista: eseguito su BigQuery con fixture inline ─────────────────────────


def _body_senza_create() -> str:
    sql = VIEW_SQL.read_text(encoding="utf-8")
    sql = re.sub(r"--[^\n]*", "", sql)
    m = re.search(r"CREATE OR REPLACE VIEW\s+`[^`]+`\s+AS\s+", sql)
    assert m, "intestazione CREATE OR REPLACE VIEW non trovata"
    return sql[m.end() :].strip()


def _riga(soc, mese, conto, sezione, saldo, letto="2026-12-31", dare=None, avere=None):
    dare = saldo if (dare is None and saldo >= 0) else (dare or 0.0)
    avere = -saldo if (avere is None and saldo < 0) else (avere or 0.0)
    return (
        f"STRUCT('{soc}' AS societa_id, '{mese}' AS mese, '{conto}' AS codice_conto, 'CE' AS tipo_conto, "
        f"'{sezione}' AS sezione, {float(dare)} AS dare, {float(avere)} AS avere, {float(saldo)} AS saldo, "
        f"'{letto}' AS data_ingresso)"
    )


FIXTURE_BILANCINO = [
    # T1 primo snapshot tardivo: solo giugno
    _riga("T1", "2026-06", "47.91.01", "Ricavi", -1000),
    _riga("T1", "2026-06", "67.01.01.01", "Costi", 600),
    # T2 salto mese: luglio e settembre, stessi conti
    _riga("T2", "2026-07", "47.91.01", "Ricavi", -700),
    _riga("T2", "2026-07", "57.09.13.01", "Costi", 300),
    _riga("T2", "2026-09", "47.91.01", "Ricavi", -900),
    _riga("T2", "2026-09", "57.09.13.01", "Costi", 500),
    # T3 cambio anno: dicembre 2026 e gennaio 2027
    _riga("T3", "2026-12", "47.91.01", "Ricavi", -5000),
    _riga("T3", "2026-12", "55.01.01", "Costi", 4000),
    _riga("T3", "2027-01", "47.91.01", "Ricavi", -100),
    _riga("T3", "2027-01", "55.01.01", "Costi", 250),
    # T4 ricavo non mappato in d_categorie_conti
    _riga("T4", "2026-01", "47.99.99", "Ricavi", -300),
    _riga("T4", "2026-01", "55.01.01", "Costi", 100),
    # T5 ricavi assenti (solo costi)
    _riga("T5", "2026-01", "55.01.01", "Costi", 100),
    # T6 esclusioni e nature
    _riga("T6", "2026-01", "47.91.01", "Ricavi", -10000),
    _riga("T6", "2026-01", "67.01.01.01", "Costi", 3000),
    _riga("T6", "2026-01", "65.11.01", "Costi", 1000),
    _riga("T6", "2026-01", "65.01.05.91", "Costi", 120),
    _riga("T6", "2026-01", "65.01.05.90", "Costi", 150),
    _riga("T6", "2026-01", "75.90.02", "Costi", 80),
    _riga("T6", "2026-01", "75.01.98", "Costi", 5),
    _riga("T6", "2026-01", "75.03.05", "Costi", 200),
    _riga("T6", "2026-01", "73.01.01", "Costi", 50),
    # T7 conto nuovo nel mese (gennaio A,B; febbraio A,B,C)
    _riga("T7", "2026-01", "47.91.01", "Ricavi", -100),
    _riga("T7", "2026-01", "55.01.01", "Costi", 50),
    _riga("T7", "2026-02", "47.91.01", "Ricavi", -220),
    _riga("T7", "2026-02", "55.01.01", "Costi", 90),
    _riga("T7", "2026-02", "57.09.13.01", "Costi", 30),
    # T8 conto presente solo nel mese precedente (gennaio A,B,C; febbraio A,B) — NON imputato a zero
    _riga("T8", "2026-01", "47.91.01", "Ricavi", -100),
    _riga("T8", "2026-01", "55.01.01", "Costi", 50),
    _riga("T8", "2026-01", "67.01.05.01", "Costi", 40),
    _riga("T8", "2026-02", "47.91.01", "Ricavi", -220),
    _riga("T8", "2026-02", "55.01.01", "Costi", 90),
    # T9 due snapshot adiacenti sullo stesso dominio: derivabile
    _riga("T9", "2026-01", "47.91.01", "Ricavi", -100),
    _riga("T9", "2026-01", "55.01.01", "Costi", 50),
    _riga("T9", "2026-02", "47.91.01", "Ricavi", -220),
    _riga("T9", "2026-02", "55.01.01", "Costi", 90),
    # T11 conto escluso PRESENTE con saldo zero (movimentato dare=avere): vale 0, non NULL
    _riga("T11", "2026-01", "47.91.01", "Ricavi", -1000),
    _riga("T11", "2026-01", "55.01.01", "Costi", 400),
    _riga("T11", "2026-01", "65.11.01", "Costi", 0, dare=500, avere=500),
    # T12 conto escluso ASSENTE dallo snapshot: NULL, non zero
    _riga("T12", "2026-01", "47.91.01", "Ricavi", -1000),
    _riga("T12", "2026-01", "55.01.01", "Costi", 400),
    # T10 snapshot parziale (caricato prima della fine del mese)
    _riga("T10", "2026-09", "47.91.01", "Ricavi", -100, letto="2026-09-25"),
    _riga("T10", "2026-09", "55.01.01", "Costi", 50, letto="2026-09-25"),
]

FIXTURE_CATEGORIE = [
    "47.91.01",
    "55.01.01",
    "57.09.13.01",
    "65.11.01",
    "65.01.05.91",
    "65.01.05.90",
    "67.01.01.01",
    "67.01.05.01",
    "75.90.02",
    "75.03.05",
    "73.01.01",
]


def _sql_fixture() -> str:
    body = _body_senza_create()
    body = body.replace("`hotelops-suite.hotelops.f_bilancino`", "fixture_bilancino")
    body = body.replace(
        "`hotelops-suite.hotelops.d_categorie_conti`", "fixture_categorie"
    )
    assert body.upper().startswith("WITH ")
    fx = (
        "WITH fixture_bilancino AS (SELECT * FROM UNNEST(["
        + ",\n".join(FIXTURE_BILANCINO)
        + "])),\n"
        "fixture_categorie AS (SELECT codice_conto FROM UNNEST(["
        + ", ".join(f"'{c}'" for c in FIXTURE_CATEGORIE)
        + "]) AS codice_conto),\n"
    )
    return fx + body[len("WITH ") :]


@pytest.fixture(scope="module")
def righe_fixture(bq_client):
    sql = _sql_fixture()
    rows = list(bq_client.query(sql).result())
    return {(r.societa_id, r.mese_str): dict(r.items()) for r in rows}


@pytest.mark.bq
def test_t1_primo_snapshot_tardivo(righe_fixture):
    r = righe_fixture[("T1", "2026-06")]
    assert r["ricavi_totali_ytd"] == 1000 and r["costi_55_71_ytd"] == 600
    assert (
        r["mese_derivabile"] is False
        and r["delta_costi_55_71"] is None
        and r["delta_ricavi_totali"] is None
    )
    assert r["mese_prec_adiacente"] is False


@pytest.mark.bq
def test_t2_salto_mese_non_derivabile(righe_fixture):
    r9 = righe_fixture[("T2", "2026-09")]
    assert r9["costi_55_71_ytd"] == 500
    assert r9["mese_derivabile"] is False and r9["delta_costi_55_71"] is None
    assert r9["mese_prec_adiacente"] is False
    assert (
        "T2",
        "2026-08",
    ) not in righe_fixture  # un mese senza bilancino non produce riga


@pytest.mark.bq
def test_t3_cambio_anno(righe_fixture):
    gen = righe_fixture[("T3", "2027-01")]
    assert gen["mese_derivabile"] is True
    assert (
        gen["delta_costi_55_71"] == 250 and gen["delta_ricavi_totali"] == 100
    )  # = YTD, nessun delta cross-anno
    dic = righe_fixture[("T3", "2026-12")]
    assert dic["mese_derivabile"] is False  # dicembre isolato: niente novembre


@pytest.mark.bq
def test_t4_ricavo_non_mappato_resta_nel_denominatore(righe_fixture):
    r = righe_fixture[("T4", "2026-01")]
    assert (
        r["ricavi_totali_ytd"] == 300
        and r["n_ricavi_da_definire"] == 1
        and r["n_conti_da_definire"] == 1
    )


@pytest.mark.bq
def test_t5_ricavi_assenti(righe_fixture):
    r = righe_fixture[("T5", "2026-01")]
    assert r["ricavi_totali_ytd"] == 0
    c = Componenti.da_riga(r, Periodo.YTD)
    assert rapporto(c, Perimetro.Q5_SOLO_CANONE, Natura.CLASSE, Periodo.YTD) is None


@pytest.mark.bq
def test_t6_esclusioni_e_nature(righe_fixture):
    r = righe_fixture[("T6", "2026-01")]
    assert r["costi_55_71_ytd"] == 3000 + 1000 + 120 + 150
    assert (
        r["canone_651101_ytd"] == 1000
        and r["angelina_65010591_ytd"] == 120
        and r["cvm_65010590_ytd"] == 150
    )
    assert r["servizi_bancari_75_ytd"] == 85 and r["oneri_finanziari_75_ytd"] == 200
    flags = (
        "canone_651101_presente",
        "angelina_65010591_presente",
        "cvm_65010590_presente",
        "servizi_bancari_75_presente",
        "oneri_finanziari_75_presente",
    )
    assert all(r[k] is True for k in flags)
    assert r["amm_imposte_73_77_ytd"] == 50
    assert r["costi_totali_ce_ytd"] == 4270 + 85 + 200 + 50
    c = Componenti.da_riga(r, Periodo.YTD)
    assert numeratore(c, Perimetro.Q1_PIANO, Natura.CLASSE) == 3150
    assert numeratore(c, Perimetro.Q4_FITTI_GRUPPO_NATURA, Natura.NATURA) == 3000 + 85
    assert numeratore(c, Perimetro.R0_STANDALONE_PIENO, Natura.NATURA) == 4270 + 85


@pytest.mark.bq
def test_t7_conto_nuovo_nel_mese_non_derivabile(righe_fixture):
    feb = righe_fixture[("T7", "2026-02")]
    assert feb["n_conti_solo_corr"] == 1 and feb["n_conti_solo_prec"] == 0
    assert feb["mese_derivabile"] is False and feb["delta_costi_55_71"] is None
    assert feb["costi_55_71_ytd"] == 120  # lo YTD resta usabile


@pytest.mark.bq
def test_t8_conto_solo_nel_mese_precedente_non_imputato_a_zero(righe_fixture):
    feb = righe_fixture[("T8", "2026-02")]
    assert feb["n_conti_solo_prec"] == 1 and feb["n_conti_solo_corr"] == 0
    assert feb["mese_derivabile"] is False and feb["delta_costi_55_71"] is None
    assert feb["costi_55_71_ytd"] == 90


@pytest.mark.bq
def test_t9_adiacenti_stesso_dominio_derivabile(righe_fixture):
    feb = righe_fixture[("T9", "2026-02")]
    assert feb["mese_derivabile"] is True
    assert feb["delta_ricavi_totali"] == 120 and feb["delta_costi_55_71"] == 40
    gen = righe_fixture[("T9", "2026-01")]
    assert gen["mese_derivabile"] is True and gen["delta_costi_55_71"] == 50
    assert (
        gen["canone_651101_ytd"] is None and gen["delta_canone_651101"] is None
    )  # assente: NULL, non 0


@pytest.mark.bq
def test_t10_acquisito_prima_di_fine_mese(righe_fixture):
    r = righe_fixture[("T10", "2026-09")]
    assert r["acquisito_prima_di_fine_mese"] is True
    assert righe_fixture[("T9", "2026-02")]["acquisito_prima_di_fine_mese"] is False


@pytest.mark.bq
def test_t11_conto_escluso_presente_con_saldo_zero(righe_fixture):
    r = righe_fixture[("T11", "2026-01")]
    assert r["canone_651101_presente"] is True and r["canone_651101_ytd"] == 0
    c = Componenti.da_riga(r, Periodo.YTD)
    assert numeratore(c, Perimetro.Q5_SOLO_CANONE, Natura.CLASSE) == 400
    assert rapporto(c, Perimetro.Q5_SOLO_CANONE, Natura.CLASSE, Periodo.YTD) == 0.4


@pytest.mark.bq
def test_t12_conto_escluso_assente_non_vale_zero(righe_fixture):
    """SQL -> da_riga -> rapporto: il canone assente arriva come NULL; i perimetri che lo escludono non sono
    valutabili; R0 (nessuna esclusione) resta calcolabile."""
    r = righe_fixture[("T12", "2026-01")]
    assert r["canone_651101_presente"] is False and r["canone_651101_ytd"] is None
    assert r["angelina_65010591_ytd"] is None and r["servizi_bancari_75_ytd"] is None
    c = Componenti.da_riga(r, Periodo.YTD)
    assert c.canone_651101 is None
    q5 = rapporto(c, Perimetro.Q5_SOLO_CANONE, Natura.CLASSE, Periodo.YTD)
    assert q5 is None and valuta(q5, LIMITE_65) == "non_valutabile"
    assert rapporto(c, Perimetro.R0_STANDALONE_PIENO, Natura.CLASSE, Periodo.YTD) == 0.4
    assert (
        rapporto(c, Perimetro.R0_STANDALONE_PIENO, Natura.NATURA, Periodo.YTD) is None
    )  # servizi 75 assenti


@pytest.mark.bq
def test_smoke_dato_reale_orti_set_2026(bq_client):
    """Il SQL della vista (non deployata) sul dato reale riproduce i totali del ponte dei conti."""
    sql = _body_senza_create()
    rows = list(
        bq_client.query(
            f"SELECT * FROM ({sql}) WHERE societa_id = 'ORTI' AND mese_str = '2026-09'"
        ).result()
    )
    assert len(rows) == 1
    r = dict(rows[0].items())
    # I totali del ponte sono somme di righe arrotondate all'euro: tolleranza di 2 euro sul dato esatto
    # (es. ricavi_totali_ytd reale = 4.322.453,08 contro 4.322.454 pubblicato).
    attesi = {
        "ricavi_totali_ytd": 4_322_454,
        "costi_55_71_ytd": 2_954_318,
        "canone_651101_ytd": 600_000,
        "angelina_65010591_ytd": 60_000,
        "cvm_65010590_ytd": 100_000,
        "servizi_bancari_75_ytd": 82_142,
        "oneri_finanziari_75_ytd": 86_212,
    }
    for k, v in attesi.items():
        assert abs(r[k] - v) <= 2, (k, r[k], v)
    assert r["n_conti_ce"] == 106 and r["n_conti_da_definire"] == 30
    assert all(
        r[k] is True
        for k in (
            "canone_651101_presente",
            "angelina_65010591_presente",
            "cvm_65010590_presente",
            "servizi_bancari_75_presente",
        )
    )
    # agosto → settembre: 7 conti spariti e 4 nuovi → il mese di settembre NON è derivabile
    assert r["n_conti_solo_prec"] == 7 and r["n_conti_solo_corr"] == 4
    assert r["mese_derivabile"] is False and r["delta_costi_55_71"] is None
    c = Componenti.da_riga(r, Periodo.YTD)
    assert (
        round(rapporto(c, Perimetro.Q1_PIANO, Natura.CLASSE, Periodo.YTD), 3) == 0.531
    )
    assert (
        round(rapporto(c, Perimetro.R0_STANDALONE_PIENO, Natura.NATURA, Periodo.YTD), 3)
        == 0.702
    )
