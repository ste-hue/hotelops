from datetime import date, datetime
from decimal import Decimal

import pytest

from tests.test_cassa_scenario import scenario_sintetico
from verticals.condges.cassa_fonti import (
    BaselineNonUnica,
    carica_snapshot,
    coda_flussi,
    coda_ripetuta,
    leggi_ancore,
    leggi_baseline,
    leggi_fatti,
    leggi_scenari,
    mesi_ipotetici,
    salva_snapshot,
)
from verticals.condges.cassa_motore import Fatto, Flusso, Riga
from verticals.condges.cassa_scenario import righe_p, scenario_to_json


def eur(x) -> int:
    return round(x * 100)


def finta(per_tabella: dict):
    """query finta: risponde per sottostringa del nome tabella nella SQL."""

    def query(sql: str):
        for nome, righe in per_tabella.items():
            if nome in sql:
                return righe
        raise AssertionError(f"SQL inattesa: {sql}")

    return query


def saldi(societa="ORTI", **conti):
    return [
        {"societa_id": societa, "banca_id": b, "data_riferimento": d, "saldo_eur": s}
        for b, per_data in conti.items()
        for d, s in per_data.items()
    ]


def movimenti(societa="ORTI", fino=None, **conti):
    righe = [
        {"societa_id": societa, "banca_id": b, "data_operazione": d, "importo_netto": x}
        for b, mov in conti.items()
        for d, x in mov
    ]
    if fino:  # riga a importo zero che fissa fin dove arrivano i movimenti
        righe += [
            {
                "societa_id": societa,
                "banca_id": b,
                "data_operazione": fino,
                "importo_netto": 0.0,
            }
            for b in conti
        ]
    return righe


FILE = {"ORTI": "orti.xlsx", "INTUR": "intur.xlsx"}


def righe_pf(voci=None, file=None):
    """voci: {(societa, voce): {mese: importo}}; file: {societa: [file,...]}"""
    out = []
    for (soc, voce), per_mese in (voci or {}).items():
        for mese, imp in per_mese.items():
            anno, m = (int(x) for x in mese.split("-"))
            out.append(_riga_pf(soc, voce, anno, m, imp, FILE[soc]))
    for soc, files in (file or {}).items():
        for i, f in enumerate(files):
            out.append(_riga_pf(soc, "USCITE_ALTRO", 2026, 10, 1.0 + i, f))
    return out


def _riga_pf(soc, voce, anno, m, imp, f):
    return {
        "societa_id": soc,
        "voce_id": voce,
        "anno": anno,
        "mese": m,
        "importo": imp,
        "file_sorgente": f,
        "raw_object_id": f"raw-{f}",
        "data_caricamento": "2026-10-01 10:00:00+00:00",
    }


CHIUSURE_SETT = saldi("ORTI", MPS={"2026-09-30": 1000.0}) + saldi(
    "INTUR", SELLA={"2026-09-30": 10.0}
)


def finta_pf(canone_orti, canone_intur, extra=None):
    voci = {
        ("ORTI", "USCITE_CANONE_PASSIVO"): canone_orti,
        ("INTUR", "ENTRATE_AFFITTI_INTUR"): canone_intur,
    }
    voci.update(extra or {})
    voci = {k: v for k, v in voci.items() if v}
    return finta(
        {
            "f_saldi_banca_chiusura_mensile": CHIUSURE_SETT,
            "f_piano_finanziario_input": righe_pf(voci),
        }
    )


def finta_pf_settembre():
    return finta_pf(
        {"2026-11": 244_000.0},
        {"2026-11": 244_000.0},
        extra={
            ("ORTI", "USCITE_GODIMENTO_BENI"): {"2026-10": 50_000.0},
            ("ORTI", "USCITE_SALARI"): {"2026-09": 9.0, "2026-10": 100.5},
            ("INTUR", "ENTRATE_FINANZIAMENTI"): {"2026-11": 1000.0},
        },
    )


def evento(progetto, data, importo, fornitore, tipo="PAGAMENTO"):
    return {
        "evento_id": f"ev-{progetto}-{data}",
        "progetto_id": progetto,
        "tipo_evento": tipo,
        "data_evento": data,
        "importo_eur": Decimal(importo),
        "fornitore_id": fornitore,
    }


# ── baseline ──


def test_baseline_rifiuta_due_file_per_societa():
    q = finta(
        {
            "f_saldi_banca_chiusura_mensile": CHIUSURE_SETT,
            "f_piano_finanziario_input": righe_pf(file={"ORTI": ["a.xlsx", "b.xlsx"]}),
        }
    )
    with pytest.raises(BaselineNonUnica, match="ORTI.*a.xlsx.*b.xlsx"):
        leggi_baseline(q)


def test_baseline_esclude_il_mese_chiuso_e_isola_il_canone():
    righe, flussi, base, mesi = leggi_baseline(finta_pf_settembre())
    assert mesi == ["2026-10", "2026-11"] and all(r.mese != "2026-09" for r in righe)
    assert not any(
        r.voce_id
        in ("USCITE_CANONE_PASSIVO", "ENTRATE_AFFITTI_INTUR", "USCITE_GODIMENTO_BENI")
        for r in righe
    )
    assert (
        Flusso("Fitto Hotel (canone)", "ORTI", "INTUR", "2026-11", eur(244_000), "pf")
        in flussi
    )
    assert (
        Flusso("Godimento beni di terzi", "ORTI", "TERZI", "2026-10", eur(50_000), "pf")
        in flussi
    )
    assert all(isinstance(r.importo, int) for r in righe)
    assert Riga("ORTI", "USCITE_SALARI", "2026-10", 10050, "U", "pf") in righe
    assert (
        Riga("INTUR", "ENTRATE_FINANZIAMENTI", "2026-11", 100000, "E", "finanziamento")
        in righe
    )
    assert base["ORTI"] == {
        "file_sorgente": "orti.xlsx",
        "raw_object_id": "raw-orti.xlsx",
        "data_caricamento": "2026-10-01 10:00:00+00:00",
    }


def test_gamba_sola_marcata_e_non_completata():
    _, flussi, _, _ = leggi_baseline(
        finta_pf(canone_orti={"2026-10": 50_000.0}, canone_intur={})
    )
    assert flussi == [
        Flusso(
            "Fitto Hotel (canone)", "ORTI", "INTUR", "2026-10", eur(50_000), "una_gamba"
        )
    ]


def test_gamba_solo_intur_viene_da_terzi():
    _, flussi, _, _ = leggi_baseline(
        finta_pf(canone_orti={}, canone_intur={"2026-10": 7_000.0})
    )
    assert flussi == [
        Flusso(
            "Fitto Hotel (canone)", "TERZI", "INTUR", "2026-10", eur(7_000), "una_gamba"
        )
    ]


def test_gambe_diverse_danno_pf_piu_residuo():
    _, flussi, _, _ = leggi_baseline(
        finta_pf(
            canone_orti={"2026-11": 379_000.0}, canone_intur={"2026-11": 244_000.0}
        )
    )
    assert sorted(f.stato for f in flussi) == ["pf", "una_gamba"]
    assert {f.importo for f in flussi} == {eur(244_000), eur(135_000)}


def test_gamba_intur_maggiore_residuo_da_terzi():
    _, flussi, _, _ = leggi_baseline(
        finta_pf(canone_orti={"2026-11": 100.0}, canone_intur={"2026-11": 130.0})
    )
    assert (
        Flusso("Fitto Hotel (canone)", "ORTI", "INTUR", "2026-11", eur(100), "pf")
        in flussi
    )
    assert (
        Flusso(
            "Fitto Hotel (canone)", "TERZI", "INTUR", "2026-11", eur(30), "una_gamba"
        )
        in flussi
    )


# ── ancore ──


def test_ancora_attestata_solo_se_quadra_per_conto():
    q = finta(
        {
            "f_saldi_banca_chiusura_mensile": saldi(
                MPS={"2026-08-31": 900.0, "2026-09-30": 1000.0},
                INTESA={"2026-09-30": 500.0},
            ),
            "f_banche_movimenti": movimenti(
                MPS=[("2026-09-10", 100.0)], fino="2026-10-02"
            ),
        }
    )
    a = leggi_ancore(q)["ORTI"]
    assert a.saldo == eur(1500) and a.data == date(2026, 9, 30)
    assert a.conti["MPS"].attestato is True and a.conti["INTESA"].attestato is False
    assert a.attestato is False
    assert "nessuna chiusura precedente" in a.conti["INTESA"].motivo
    assert a.conti["MPS"].motivo == "quadra con movimenti dal 2026-08-31"


def test_societa_attestata_se_tutti_i_conti_quadrano():
    q = finta(
        {
            "f_saldi_banca_chiusura_mensile": saldi(
                MPS={"2026-08-31": 900.0, "2026-09-30": 1000.0}
            ),
            "f_banche_movimenti": movimenti(
                MPS=[("2026-09-10", 100.0)], fino="2026-09-30"
            ),
        }
    )
    assert leggi_ancore(q)["ORTI"].attestato is True


def test_movimenti_che_non_coprono_la_data_non_attestano():
    q = finta(
        {
            "f_saldi_banca_chiusura_mensile": saldi(
                MPS={"2026-08-31": 900.0, "2026-09-30": 1000.0}
            ),
            "f_banche_movimenti": movimenti(
                MPS=[("2026-09-10", 100.0)], fino="2026-09-10"
            ),
        }
    )
    c = leggi_ancore(q)["ORTI"].conti["MPS"]
    assert c.attestato is False and c.motivo == "movimenti fino al 2026-09-10"


def test_scostamento_di_un_centesimo_non_attesta():
    q = finta(
        {
            "f_saldi_banca_chiusura_mensile": saldi(
                MPS={"2026-08-31": 900.0, "2026-09-30": 1000.0}
            ),
            "f_banche_movimenti": movimenti(
                MPS=[("2026-09-10", 99.99)], fino="2026-10-02"
            ),
        }
    )
    c = leggi_ancore(q)["ORTI"].conti["MPS"]
    assert c.attestato is False and c.motivo == "scostamento 0,01"


def test_scostamento_in_euro_con_segno():
    from verticals.condges.cassa_fonti import _eur

    assert _eur(154923) == "1.549,23" and _eur(-154923) == "-1.549,23"
    assert _eur(5) == "0,05" and _eur(0) == "0,00" and _eur(100000000) == "1.000.000,00"


def test_movimenti_fuori_dal_periodo_o_di_altro_conto_non_contano():
    q = finta(
        {
            "f_saldi_banca_chiusura_mensile": saldi(
                MPS={"2026-08-31": 900.0, "2026-09-30": 1000.0}
            ),
            "f_banche_movimenti": movimenti(
                MPS=[("2026-08-31", 50.0), ("2026-09-10", 100.0), ("2026-10-01", 7.0)],
                fino="2026-10-02",
            )
            + movimenti(societa="INTUR", MPS=[("2026-09-12", 5.0)]),
        }
    )
    assert leggi_ancore(q)["ORTI"].conti["MPS"].attestato is True


def test_ancore_accetta_date_vere_come_da_bigquery():
    q = finta(
        {
            "f_saldi_banca_chiusura_mensile": saldi(
                MPS={date(2026, 8, 31): 900.0, date(2026, 9, 30): 1000.0}
            ),
            "f_banche_movimenti": movimenti(
                MPS=[(date(2026, 9, 10), 100.0)], fino=date(2026, 9, 30)
            ),
        }
    )
    assert leggi_ancore(q)["ORTI"].attestato is True


# ── fatti ──


def test_fatti_in_centesimi_con_societa_del_progetto():
    (f,) = leggi_fatti(
        finta(
            {
                "f_progetto_eventi": [
                    evento("HPAN26PIANO3", "2026-10-27", "72300.00", "AMCN")
                ]
            }
        )
    )
    assert f == Fatto(
        "INTUR", "HPAN26PIANO3", "AMCN", "2026-10", eur(72_300), f.evento_id
    )


def test_fatti_progetto_sconosciuto_esplode():
    with pytest.raises(ValueError, match="XYZ"):
        leggi_fatti(
            finta({"f_progetto_eventi": [evento("XYZ", "2026-10-27", "1.00", None)]})
        )


def test_fatti_solo_pagamenti():
    q = finta(
        {
            "f_progetto_eventi": [
                evento("HPAN26PIANO3", "2026-10-27", "1.00", None, tipo="IMPEGNO")
            ]
        }
    )
    assert leggi_fatti(q) == []


# ── scenari ──


def _copia(righe, rid, ts):
    return [{**r, "raw_object_id": rid, "data_caricamento": ts} for r in righe]


def test_scenari_dedup_per_scenario_id_tiene_il_piu_recente():
    sc, base = scenario_sintetico()
    s, f, p = righe_p(
        scenario_to_json(sc, base, "t"), "vecchio", datetime(2026, 10, 1), "s"
    )
    s2, f2, p2 = (_copia(x, "nuovo", "2026-10-29 09:00:00") for x in (s, f, p))
    s, f, p = (_copia(x, "vecchio", "2026-10-01 09:00:00") for x in (s, f, p))
    # il vecchio ha un mese di pagamento in più e un importo diverso su un flusso
    p = p + [{**p[0], "mese": "2031-12", "importo_netto_cent": 999}]
    f = [{**f[0], "importo_cent": f[0]["importo_cent"] + 1}] + f[1:]
    q = finta(
        {
            "p_scenario_flussi": f + f2,
            "p_progetti_pagamenti": p + p2,
            "p_scenari": s + s2,
        }
    )
    ((sc_out, base_out, meta),) = leggi_scenari(q)
    assert sc_out == sc and base_out == base and meta["nome"] == "t"


def test_scenari_ultimo_padre_senza_figli_vince_e_resta_vuoto():
    # "latest wins": il padre più recente comanda anche se non ha righe figlie
    sc, base = scenario_sintetico()
    s, f, p = righe_p(
        scenario_to_json(sc, base, "t"), "vecchio", datetime(2026, 10, 1), "s"
    )
    s, f, p = (_copia(x, "vecchio", "2026-10-01 09:00:00") for x in (s, f, p))
    s2 = _copia(s, "nuovo", "2026-10-29 09:00:00")
    q = finta({"p_scenario_flussi": f, "p_progetti_pagamenti": p, "p_scenari": s + s2})
    ((sc_out, _, _),) = leggi_scenari(q)
    assert all(pr.pagamenti == [] for pr in sc_out.progetti)
    assert sc_out.manuali == []


def test_coda_flussi_ripete_i_flussi_omologhi_con_stato():
    fl = [
        Flusso("Fitto Hotel (canone)", "ORTI", "INTUR", "2026-11", 100, "pf"),
        Flusso("Fitto Hotel (canone)", "TERZI", "INTUR", "2026-11", 30, "una_gamba"),
        Flusso("Godimento beni di terzi", "ORTI", "TERZI", "2026-10", 5, "pf"),
    ]
    assert coda_flussi(fl, ["2027-11"]) == [
        Flusso("Fitto Hotel (canone)", "ORTI", "INTUR", "2027-11", 100, "pf"),
        Flusso("Fitto Hotel (canone)", "TERZI", "INTUR", "2027-11", 30, "una_gamba"),
    ]
    assert coda_flussi(fl, ["2027-12"]) == []


def test_conto_senza_chiusura_all_ultima_data_resta_nell_ancora():
    q = finta(
        {
            "f_saldi_banca_chiusura_mensile": saldi(
                MPS={"2026-08-31": 900.0, "2026-09-30": 1000.0},
                INTESA={"2026-08-31": 500.0},
            ),
            "f_banche_movimenti": movimenti(
                MPS=[("2026-09-10", 100.0)], fino="2026-09-30"
            ),
        }
    )
    a = leggi_ancore(q)["ORTI"]
    assert a.conti["MPS"].attestato is True
    assert a.attestato is False and "INTESA" in a.conti
    assert a.saldo == eur(1500)
    assert (
        a.conti["INTESA"].motivo == "nessuna chiusura al 2026-09-30 (ultima 2026-08-31)"
    )


def test_conto_senza_movimenti_dopo_la_chiusura_precedente():
    q = finta(
        {
            "f_saldi_banca_chiusura_mensile": saldi(
                MPS={"2026-08-31": 900.0, "2026-09-30": 1000.0}
            ),
            "f_banche_movimenti": [],
        }
    )
    c = leggi_ancore(q)["ORTI"].conti["MPS"]
    assert c.attestato is False and c.motivo == "nessun movimento dopo il 2026-08-31"


# ── orizzonte e snapshot ──


def test_mesi_ipotetici_aggiunge_la_coda():
    mesi, ipotetici = mesi_ipotetici(["2026-11", "2026-12"], coda=3)
    assert mesi == ["2026-11", "2026-12", "2027-01", "2027-02", "2027-03"]
    assert ipotetici == frozenset({"2027-01", "2027-02", "2027-03"})
    assert len(mesi_ipotetici(["2026-11"])[0]) == 7


def test_coda_ripete_il_mese_omologo():
    assert coda_ripetuta(
        [Riga("ORTI", "USCITE_SALARI", "2026-10", 1000, "U", "pf")], ["2027-10"]
    ) == [Riga("ORTI", "USCITE_SALARI", "2027-10", 1000, "U", "pf")]


def test_coda_non_ripete_i_finanziamenti():
    pf = [Riga("INTUR", "ENTRATE_FINANZIAMENTI", "2026-10", 1000, "E", "finanziamento")]
    assert coda_ripetuta(pf, ["2027-10"]) == []


def test_snapshot_latest(tmp_path):
    home = tmp_path / "stato"
    p = salva_snapshot({"a": 1}, home)
    assert carica_snapshot(home) == {"a": 1}
    assert p.name.startswith("snapshot_") and p.suffix == ".json" and p.exists()
    assert (home / "latest.json").exists()
