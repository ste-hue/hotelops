import copy
import json
from datetime import date

import pytest

from verticals.condges.cassa_motore import (
    Ancora,
    Flusso,
    Input,
    Riga,
    Scenario,
    calcola,
    distribuisci,
    iva,
    to_cent,
    to_dict,
)

MESI = ["2026-10", "2026-11", "2026-12"]


def eur(x):
    return to_cent(x)


def inp_base(
    intercompany=None,
    mesi_ipotetici=(),
    soglia=0,
    progetti=None,
    fatti=None,
    canone=None,
    pf_extra=None,
    finanziamenti=None,
    manuali=None,
):
    pf = [Riga("ORTI", "ricavi", "2026-10", eur(50_000), "E", "pf")]
    for m in MESI:
        pf.append(Riga("ORTI", "costi", m, eur(20_000), "U", "pf"))
        pf.append(Riga("INTUR", "costi", m, eur(10_000), "U", "pf"))
    pf += pf_extra or []
    return Input(
        mesi=list(MESI),
        mesi_ipotetici=frozenset(mesi_ipotetici),
        ancore={
            "INTUR": Ancora("INTUR", date(2026, 9, 30), eur(100_000), True, {}),
            "ORTI": Ancora("ORTI", date(2026, 9, 30), eur(500_000), True, {}),
        },
        pf=pf,
        intercompany=intercompany or [],
        fatti=fatti or [],
        scenario=Scenario(
            nome="base",
            progetti=progetti or [],
            finanziamenti=finanziamenti or [],
            canone=canone,
            manuali=manuali or [],
            soglia=soglia,
        ),
    )


def test_to_cent_half_up():
    assert (
        to_cent(10.005) == 1001
        and to_cent("0.1") + to_cent("0.2") == 30
        and to_cent(1579384.97) == 157_938_497
    )


def test_iva_half_up():
    assert iva(1001, 22) == 1221 and iva(1000, 0) == 1000 and iva(5, 10) == 6


def test_distribuisci_ultima_rata_assorbe_i_centesimi():
    assert distribuisci(10_000_000, "2026-10", 3, MESI) == {
        "2026-10": 3_333_333,
        "2026-11": 3_333_333,
        "2026-12": 3_333_334,
    }


def test_distribuisci_oltre_orizzonte():
    with pytest.raises(ValueError, match="oltre l'orizzonte"):
        distribuisci(1_000_000, "2026-12", 2, MESI)


def test_saldo_finale_e_ancora_piu_entrate_meno_uscite():
    ris = calcola(inp_base())
    orti = [r for r in ris.righe if r.societa == "ORTI"]
    assert (orti[0].ini, orti[0].fin, orti[-1].fin) == (
        eur(500_000),
        eur(530_000),
        eur(490_000),
    )
    assert ris.minimi["ORTI"].mese == "2026-12" and ris.minimi["ORTI"].saldo == eur(
        490_000
    )


def test_intercompany_stesso_mese_si_annulla_nel_consolidato():
    ris = calcola(
        inp_base(
            intercompany=[
                Flusso("canone", "ORTI", "INTUR", "2026-11", eur(24_400), "pf")
            ]
        )
    )
    nov = next(c for c in ris.consolidato if c.mese == "2026-11")
    assert nov.intercompany_nettato == eur(24_400) and nov.residuo == 0
    assert nov.saldo == sum(r.fin for r in ris.righe if r.mese == "2026-11")


def test_verso_terzi_non_e_intercompany():
    ott = next(
        c
        for c in calcola(
            inp_base(
                intercompany=[
                    Flusso("fitto CVM", "ORTI", "TERZI", "2026-10", eur(50_000), "pf")
                ]
            )
        ).consolidato
        if c.mese == "2026-10"
    )
    assert ott.intercompany_nettato == 0 and ott.residuo == 0


def test_gamba_sola_resta_residuo_e_non_inventa_la_contropartita():
    ris = calcola(
        inp_base(
            intercompany=[
                Flusso("canone", "ORTI", "INTUR", "2026-10", eur(50_000), "una_gamba")
            ]
        )
    )
    ott = next(c for c in ris.consolidato if c.mese == "2026-10")
    intur_ott = next(
        r for r in ris.righe if r.societa == "INTUR" and r.mese == "2026-10"
    )
    orti_ott = next(r for r in ris.righe if r.societa == "ORTI" and r.mese == "2026-10")
    assert orti_ott.uscite["canone"] == eur(50_000) and intur_ott.entrate["canone"] == 0
    assert ott.intercompany_nettato == 0 and ott.residuo == eur(50_000)


def test_minimo_coda_separato_dal_minimo_pf():
    m = calcola(inp_base(mesi_ipotetici={"2026-12"})).minimi["ORTI"]
    assert m.mese == "2026-11" and m.coda_mese == "2026-12"


def test_sotto_soglia_elenca_i_mesi():
    assert calcola(inp_base(soglia=eur(495_000))).minimi["ORTI"].sotto_soglia == (
        "2026-12",
    )


def test_calcola_non_muta_l_input_e_to_dict_e_json():
    inp = inp_base(
        intercompany=[Flusso("canone", "ORTI", "INTUR", "2026-11", 100, "pf")]
    )
    prima = copy.deepcopy(inp)
    ris = calcola(inp)
    assert inp == prima
    json.dumps(to_dict(ris))
