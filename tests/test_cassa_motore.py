import copy
import json
from datetime import date

import pytest

from verticals.condges.cassa_motore import (
    Ancora,
    Fatto,
    Finanziamento,
    Flusso,
    Input,
    Pagamento,
    Progetto,
    Riga,
    ScalettaCanone,
    Scenario,
    calcola,
    distribuisci,
    flussi_canone,
    iva,
    to_cent,
    to_dict,
)

MESI = ["2026-10", "2026-11", "2026-12"]
MESI_9 = [
    "2026-10", "2026-11", "2026-12", "2027-01", "2027-02",
    "2027-03", "2027-04", "2027-05", "2027-06",
]  # fmt: skip


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
    mesi=None,
):
    mesi = mesi or MESI
    pf = [Riga("ORTI", "ricavi", "2026-10", eur(50_000), "E", "pf")]
    for m in mesi:
        pf.append(Riga("ORTI", "costi", m, eur(20_000), "U", "pf"))
        pf.append(Riga("INTUR", "costi", m, eur(10_000), "U", "pf"))
    pf += pf_extra or []
    return Input(
        mesi=list(mesi),
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


def inp9(**kw):
    return inp_base(mesi=MESI_9, **kw)


def _riga(ris, soc, mese):
    return next(r for r in ris.righe if r.societa == soc and r.mese == mese)


def test_flussi_canone_lordi_quattro_rate():
    fl = flussi_canone(ScalettaCanone({2027: eur(800_000)}, 4, "2027-03"), MESI_9)
    assert [f.mese for f in fl] == ["2027-03", "2027-04", "2027-05", "2027-06"]
    assert all(
        f.importo == eur(244_000)
        and f.da == "ORTI"
        and f.a == "INTUR"
        and f.nome == "Fitto Hotel (canone)"
        and f.stato == "scenario"
        for f in fl
    )


def test_canone_rate_non_divisibili_quadrano_al_centesimo():
    fl = flussi_canone(ScalettaCanone({2027: eur(100_000)}, 3, "2027-03"), MESI_9)
    assert sum(f.importo for f in fl) == eur(122_000)
    assert [f.importo for f in fl] == [4_066_666, 4_066_666, 4_066_668]


def test_calendario_libero_vince_sulle_rate():
    s = ScalettaCanone(
        {2027: eur(800_000)}, 4, "2027-03", calendario={"2027-06": eur(800_000)}
    )
    assert [(f.mese, f.importo) for f in flussi_canone(s, MESI_9)] == [
        ("2027-06", eur(976_000))
    ]


def test_scaletta_sostituisce_il_canone_pf_solo_negli_anni_coperti():
    inp = inp9(
        intercompany=[
            Flusso(
                "Fitto Hotel (canone)", "ORTI", "INTUR", "2026-11", eur(244_000), "pf"
            ),
            Flusso(
                "Fitto Hotel (canone)", "ORTI", "INTUR", "2027-06", eur(244_000), "pf"
            ),
        ],
        canone=ScalettaCanone({2027: eur(800_000)}, 4, "2027-03"),
    )
    intur = {
        r.mese: r.entrate["canone"] for r in calcola(inp).righe if r.societa == "INTUR"
    }
    assert intur["2026-11"] == eur(244_000)
    assert intur["2027-03"] == eur(244_000)
    assert intur["2027-06"] == eur(244_000)


def test_progetto_120k_in_sei_rate_muove_sei_mesi():
    p = Progetto(
        "x", "X", "INTUR", True, "ipotesi",
        [Pagamento("unica", distribuisci(eur(120_000), "2026-10", 6, MESI_9), 0)],
    )  # fmt: skip
    usc = [
        r.uscite["progetto"]
        for r in calcola(inp9(progetti=[p])).righe
        if r.societa == "INTUR"
    ]
    assert usc[:6] == [eur(20_000)] * 6 and usc[6:] == [0, 0, 0]


def test_iva_per_aliquota_e_reverse_charge():
    p = Progetto(
        "x", "X", "INTUR", True, "ipotesi",
        [Pagamento("arredi", {"2026-10": 1001}, 22), Pagamento("amcn", {"2026-10": 1000}, 0)],
    )  # fmt: skip
    ott = _riga(calcola(inp9(progetti=[p])), "INTUR", "2026-10")
    assert ott.uscite["progetto"] == 1221 + 1000


def test_progetto_spento_non_conta():
    p = Progetto(
        "x", "X", "INTUR", False, "ipotesi", [Pagamento("a", {"2026-10": 1000}, 0)]
    )
    assert all(r.uscite["progetto"] == 0 for r in calcola(inp9(progetti=[p])).righe)


def _p3():
    return Progetto(
        "p3", "P3", "INTUR", True, "ipotesi",
        [
            Pagamento("anticipo AMCN", {"2026-10": eur(72_300)}, 0, fornitore_id="AMCN"),
            Pagamento("SAL 1 AMCN", {"2026-12": eur(60_000)}, 0, fornitore_id="AMCN"),
            Pagamento("arredi", {"2026-10": eur(10_000)}, 0, fornitore_id="ARREDI"),
        ],
    )  # fmt: skip


def test_fatto_parziale_riduce_solo_il_suo_pagamento():
    inp = inp9(
        progetti=[_p3()],
        fatti=[Fatto("INTUR", "p3", "AMCN", "2026-10", eur(70_000), "ev1")],
    )
    ris = calcola(inp)
    ott = _riga(ris, "INTUR", "2026-10")
    dic = _riga(ris, "INTUR", "2026-12")
    assert ott.uscite["fatto"] == eur(70_000)
    assert ott.uscite["progetto"] == eur(2_300) + eur(10_000)
    assert dic.uscite["progetto"] == eur(60_000) and ris.non_riconciliati == []


def test_fatto_oltre_il_previsto_scala_sul_pagamento_successivo():
    p = Progetto(
        "p3", "P3", "INTUR", True, "ipotesi",
        [
            Pagamento("anticipo", {"2026-10": eur(72_300)}, 0, fornitore_id="AMCN"),
            Pagamento("SAL 1", {"2026-12": eur(60_000)}, 0, fornitore_id="AMCN"),
        ],
    )  # fmt: skip
    ris = calcola(
        inp9(
            progetti=[p],
            fatti=[Fatto("INTUR", "p3", "AMCN", "2026-10", eur(80_000), "ev1")],
        )
    )
    assert _riga(ris, "INTUR", "2026-12").uscite["progetto"] == eur(52_300)


def test_fatto_senza_pagamento_resta_non_riconciliato():
    p = Progetto(
        "p3", "P3", "INTUR", True, "ipotesi",
        [Pagamento("anticipo", {"2026-10": eur(72_300)}, 0, fornitore_id="AMCN")],
    )  # fmt: skip
    f = Fatto("INTUR", "p3", "SCONOSCIUTO", "2026-10", eur(5_000), "ev2")
    ris = calcola(inp9(progetti=[p], fatti=[f]))
    ott = _riga(ris, "INTUR", "2026-10")
    assert ris.non_riconciliati == [f]
    assert ott.uscite["fatto"] == eur(5_000) and ott.uscite["progetto"] == eur(72_300)


def test_erogazioni_scenario_sostituiscono_le_righe_pf_di_finanziamento():
    inp = inp9(
        pf_extra=[
            Riga(
                "INTUR",
                "ENTRATE_FINANZIAMENTI",
                "2026-11",
                eur(550_000),
                "E",
                "finanziamento",
            )
        ],
        finanziamenti=[
            Finanziamento(
                "mcc", "MCC", "INTUR", {"2026-12": eur(550_000)}, {}, "da verificare"
            )
        ],
    )
    intur = {
        r.mese: r.entrate["finanziamento"]
        for r in calcola(inp).righe
        if r.societa == "INTUR"
    }
    assert intur["2026-11"] == 0 and intur["2026-12"] == eur(550_000)


def test_erogazioni_pf_restano_senza_finanziamenti_dello_scenario():
    inp = inp9(
        pf_extra=[
            Riga(
                "INTUR",
                "ENTRATE_FINANZIAMENTI",
                "2026-11",
                eur(550_000),
                "E",
                "finanziamento",
            )
        ]
    )
    assert _riga(calcola(inp), "INTUR", "2026-11").entrate["finanziamento"] == eur(
        550_000
    )


def test_una_gamba_da_terzi_conta_solo_dal_lato_a():
    ris = calcola(
        inp_base(
            intercompany=[
                Flusso(
                    "Fitto Hotel (canone)",
                    "TERZI",
                    "INTUR",
                    "2026-10",
                    eur(50_000),
                    "una_gamba",
                )
            ]
        )
    )
    assert _riga(ris, "INTUR", "2026-10").entrate["canone"] == eur(50_000)
    assert _riga(ris, "ORTI", "2026-10").uscite["canone"] == 0
    ott = next(c for c in ris.consolidato if c.mese == "2026-10")
    assert ott.residuo == eur(50_000) and ott.intercompany_nettato == 0


def test_distribuisci_n_minore_di_uno_solleva():
    with pytest.raises(ValueError):
        distribuisci(1_000, "2026-10", 0, MESI)


def test_tutti_i_mesi_ipotetici_non_solleva():
    # Nessun mese PF: il minimo e' preso dal minimo della coda.
    ris = calcola(inp_base(mesi_ipotetici=set(MESI)))
    m = ris.minimi["ORTI"]
    assert m.mese == "2026-12" and m.saldo == eur(490_000) and m.coda_mese == "2026-12"


def test_non_muta_input_con_fatti_e_canone():
    inp = inp9(
        progetti=[_p3()],
        fatti=[Fatto("INTUR", "p3", "AMCN", "2026-10", eur(80_000), "ev1")],
        canone=ScalettaCanone({2027: eur(800_000)}, 4, "2027-03"),
        intercompany=[
            Flusso("Fitto Hotel (canone)", "ORTI", "INTUR", "2027-06", 1, "pf")
        ],
    )
    prima = copy.deepcopy(inp)
    calcola(inp)
    assert inp == prima
