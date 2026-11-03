from datetime import date

import openpyxl
import pandas as pd
import pytest
from io import BytesIO
from openpyxl.utils import get_column_letter

from verticals.condges.pf_rotate.excel_model import (
    MESI_IT,
    find_month_periods,
    periodo,
    periodo_anno_mese,
)
from verticals.condges.pf_rotate.extend import extend_to, trim_before
from verticals.condges.pf_rotate.rotate import rotate
from verticals.condges.pf_rotate.step3_scadenzario import UnmappedPolicy

_MESI_ORDINATI = list(MESI_IT.keys())  # GENNAIO..DICEMBRE, ordine dict


def _wb(bytes_):
    return openpyxl.load_workbook(BytesIO(bytes_))


def _extend_and_reload(minimal_pf_orti_bytes, tmp_path, target=None):
    """extend_to + save + reload wb/wbv gemelli — pattern comune ai test trim.

    Il fixture è costruito puro-openpyxl (mai aperto in Excel): il gemello
    data_only=True torna None su OGNI formula (nessun valore in cache).
    Il chiamante deve iniettare a mano i cached value delle celle che
    trim_before congelerà, PRIMA di chiamare trim_before."""
    target = target or periodo(2027, 6)
    wb0 = _wb(minimal_pf_orti_bytes)
    extend_to(wb0, target)
    p = tmp_path / "extended.xlsx"
    wb0.save(p)
    wb = openpyxl.load_workbook(p)
    wbv = openpyxl.load_workbook(p, data_only=True)
    return wb, wbv


def _inject_cached_freeze_values(wbv, cols):
    """Inietta i valori cached richiesti dal freeze di trim_before(cutoff=2027-01)
    sul fixture esteso a 2027-06: r4 della prima superstite (GENNAIO 2027,
    cascata dal SALDO DI PERIODO del DICEMBRE 2026 eliminato) + TOTALI r12/r27
    (SUM che copre l'intero storico eliminato). Determinato empiricamente
    lanciando trim_before e osservando quali celle sollevano 'valore assente'."""
    pfv = wbv["Piano Finanziario"]
    pfv.cell(4, cols[periodo(2027, 1)]).value = 339337.46  # saldo iniziale (finto)
    pfv.cell(12, 18).value = 900.0  # TOTALI TOTALE ENTRATE (finto)
    pfv.cell(27, 18).value = 2700.0  # TOTALI TOTALE USCITE (finto)


def test_extend_aggiunge_colonne_fino_al_target(minimal_pf_orti_bytes):
    wb = _wb(minimal_pf_orti_bytes)
    extend_to(wb, periodo(2027, 6))
    pf = wb["Piano Finanziario"]
    cols = find_month_periods(pf)
    assert max(cols) == periodo(2027, 6)
    assert min(cols) == periodo(2026, 4)  # l'esistente non si tocca
    assert pf.cell(1, cols[periodo(2027, 1)]).value == 2027  # marker anno sul GENNAIO


def test_extend_traduce_la_cascata_saldo(minimal_pf_orti_bytes):
    from openpyxl.utils import get_column_letter

    wb = _wb(minimal_pf_orti_bytes)
    extend_to(wb, periodo(2027, 6))
    pf = wb["Piano Finanziario"]
    cols = find_month_periods(pf)
    c_gen = cols[periodo(2027, 1)]
    # r4 del nuovo mese = catena dal saldo proiettato del mese precedente
    assert pf.cell(4, c_gen).value == f"={get_column_letter(c_gen - 1)}37"


def test_extend_estende_anche_i_dettagli(minimal_pf_orti_bytes):
    wb = _wb(minimal_pf_orti_bytes)
    extend_to(wb, periodo(2027, 6))
    for name in ("Utenze", "Materie Prime-Consumo "):
        assert max(find_month_periods(wb[name])) == periodo(2027, 6)


def test_extend_idempotente(minimal_pf_orti_bytes):
    wb = _wb(minimal_pf_orti_bytes)
    assert extend_to(wb, periodo(2026, 12)) == []  # target già coperto: no-op


def test_extend_ripunta_le_formule_totali(minimal_pf_orti_bytes):
    """TOTALI (master) trasla insieme alla colonna: SUM esteso, singoli ref
    ripuntati al nuovo ultimo mese, e i riferimenti-incrociati fra righe TOTALI
    (es. Cash Flow TOTALI = TOTALE ENTRATE TOTALI - TOTALE USCITE TOTALI)
    seguono lo shift della colonna TOTALI stessa."""
    from openpyxl.utils import get_column_letter

    wb = _wb(minimal_pf_orti_bytes)
    changed = extend_to(wb, periodo(2027, 6))
    assert changed  # non è un no-op
    pf = wb["Piano Finanziario"]
    cols = find_month_periods(pf)
    last_month_col_l = get_column_letter(cols[periodo(2027, 6)])
    # TOTALI ora è 6 colonne più a destra della vecchia posizione (L=12 -> R=18)
    totali_col = 18
    assert pf.cell(2, totali_col).value == "TOTALI"
    assert pf.cell(12, totali_col).value == f"=SUM(C12:{last_month_col_l}12)"
    assert pf.cell(37, totali_col).value == f"={last_month_col_l}37"
    # Cash Flow TOTALI referenziava L12/L27 (la vecchia colonna TOTALI): deve
    # seguirla al nuovo indirizzo, non restare puntato alla colonna diventata
    # un mese qualsiasi dell'orizzonte esteso.
    assert pf.cell(29, totali_col).value == "=R12-R27"


def test_extend_salta_fogli_di_servizio_senza_anno(minimal_pf_orti_bytes):
    """DA MAPPARE/ESCLUSI (generati da pf_generator.template) hanno 12 colonne
    mese-nudo in riga 2 ma NESSUN anno in riga 1: non sono griglie PF da
    estendere, sono report. find_month_periods ci solleverebbe 'Anno non
    dichiarato' — extend_to deve saltarli per titolo, PRIMA di chiamare
    find_month_periods, non farli esplodere."""
    wb = _wb(minimal_pf_orti_bytes)
    da_mappare = wb.create_sheet("DA MAPPARE")
    da_mappare.cell(1, 1, "Fornitori NON mappati in d_fornitori.csv")
    da_mappare.cell(2, 1, "Cod")
    da_mappare.cell(2, 2, "Nome")
    for i, m in enumerate(_MESI_ORDINATI):
        da_mappare.cell(2, 3 + i, m)  # 12 colonne mese-nudo, nessun anno

    esclusi = wb.create_sheet("ESCLUSI1")
    esclusi.cell(1, 1, "Fornitori ESCLUSI dalla cassa")
    for i, m in enumerate(_MESI_ORDINATI):
        esclusi.cell(2, 3 + i, m)

    changed = extend_to(wb, periodo(2027, 6))  # non deve sollevare

    assert any("skip" in c and "DA MAPPARE" in c for c in changed)
    assert any("skip" in c and "ESCLUSI1" in c for c in changed)
    # fogli non toccati: 12 colonne mese, ancora senza anno dichiarato
    assert da_mappare.max_column == 14  # A,B + 12 mesi (C..N)
    with pytest.raises(ValueError, match="Anno non dichiarato"):
        find_month_periods(da_mappare)


def test_extend_altro_foglio_senza_anno_continua_a_esplodere(minimal_pf_orti_bytes):
    """Guardia anti-regressione: lo skip è per titolo (DA MAPPARE/ESCLUSI), non
    generico. Un vero foglio-mese senza anno deve continuare a fallire loud."""
    wb = _wb(minimal_pf_orti_bytes)
    rotto = wb.create_sheet("Un Foglio Qualunque")
    for i, m in enumerate(_MESI_ORDINATI):
        rotto.cell(2, 3 + i, m)  # mesi ma nessun anno in riga 1

    with pytest.raises(ValueError, match="Anno non dichiarato"):
        extend_to(wb, periodo(2027, 6))


def test_extend_salta_marker_anno_su_cella_merged(minimal_pf_orti_bytes):
    """ORTI ' Varie ed Eventuali': merge su riga 1 (es. I1:O1) copre la colonna
    dove andrebbe scritto il marker anno del nuovo GENNAIO. Scrivere lì
    solleverebbe AttributeError su MergedCell — extend_to deve rilevarlo,
    saltare SOLO il marker (decorativo) e loggare un warning, senza fermare
    l'estensione delle colonne."""
    wb = _wb(minimal_pf_orti_bytes)
    ve = wb.create_sheet(" Varie ed Eventuali")
    ve["D1"] = 2026
    ve["A2"] = "CODICE"
    mesi = _MESI_ORDINATI[3:12]  # APRILE..DICEMBRE
    for i, m in enumerate(mesi):
        ve.cell(2, 4 + i, m)
    ve["B3"] = "Voce"
    ve["C3"] = "=SUM(D3:L3)"
    for i in range(9):
        col = 4 + i
        cl = get_column_letter(col)
        ve.cell(3, col, f"=SUM({cl}4:{cl}50)")
    # Il nuovo GENNAIO 2027 finirebbe in col M (13): il merge lo copre, ma
    # NON è l'anchor (I=9) quindi è una MergedCell read-only.
    ve.merge_cells("I1:O1")

    changed = extend_to(wb, periodo(2027, 6))  # non deve sollevare

    cols = find_month_periods(ve)
    assert max(cols) == periodo(2027, 6)  # colonne comunque aggiunte
    assert ve.cell(1, cols[periodo(2027, 1)]).value is None  # marker NON scritto
    assert any(
        "warn" in c.lower() and "Varie ed Eventuali" in c and "merged" in c.lower()
        for c in changed
    )


def test_extend_ripunta_il_totale_di_riga_a_sinistra_nei_dettagli(minimal_pf_orti_bytes):
    """Difetto misurato il 03/11/2026 sul PF INTUR generato: i fogli di dettaglio hanno il
    totale di riga a SINISTRA dei mesi (C, mesi da D): `=SUM(D3:Y3)` restava a Y mentre il
    foglio arrivava a col 55, e trenta colonne nuove uscivano dal totale. Rosso prima della
    correzione. Le colonne nuove non vanno ripuntate due volte; i valori in C restano."""
    wb = _wb(minimal_pf_orti_bytes)
    ut = wb.create_sheet("Utenze dettaglio")
    ut["D1"] = 2026
    ut["A2"] = "CODICE"
    for i, m in enumerate(_MESI_ORDINATI[3:12]):  # APRILE..DICEMBRE in D..L
        ut.cell(2, 4 + i, m)
    ut["A3"] = 1078
    ut["B3"] = "Enel"
    ut["C3"] = "=SUM(D3:L3)"  # totale di riga a sinistra: deve seguire l'ultimo mese
    ut["A4"] = 1079
    ut["B4"] = "Acqua"
    ut["C4"] = 123.45  # un valore in C non si tocca
    ut["C5"] = "=SUM(D5:E5)"  # un range che NON arriva all'ultimo mese resta com'è
    for i in range(9):
        cl = get_column_letter(4 + i)
        ut.cell(3, 4 + i, f"=SUM({cl}6:{cl}50)")

    extend_to(wb, periodo(2027, 6))  # +6 mesi: L (12) -> R (18)

    assert max(find_month_periods(ut)) == periodo(2027, 6)
    assert ut["C3"].value == "=SUM(D3:R3)"
    assert ut["C4"].value == 123.45 and ut["C5"].value == "=SUM(D5:E5)"
    # colonne nuove: tradotte dal Translator UNA volta sola (M..R), non ripuntate di nuovo
    for col in range(13, 19):
        cl = get_column_letter(col)
        assert ut.cell(3, col).value == f"=SUM({cl}6:{cl}50)"
    # il master non regredisce: TOTALI a destra, esteso, e Cash Flow TOTALI ripuntato
    pf = wb["Piano Finanziario"]
    assert pf["R2"].value == "TOTALI" and pf["R12"].value == "=SUM(C12:Q12)"
    assert pf["R29"].value == "=R12-R27"


# ── trim_before ──────────────────────────────────────────────────────────


def test_trim_ri_ancora_la_prima_colonna(minimal_pf_orti_bytes, tmp_path):
    wb, wbv = _extend_and_reload(minimal_pf_orti_bytes, tmp_path)
    pf = wb["Piano Finanziario"]
    cols = find_month_periods(pf)
    _inject_cached_freeze_values(wbv, cols)

    trim_before(wb, wbv, periodo(2027, 1))

    cols = find_month_periods(pf)
    assert min(cols) == periodo(2027, 1)
    assert max(cols) == periodo(2027, 6)
    first = cols[periodo(2027, 1)]
    v = pf.cell(4, first).value  # saldo iniziale della prima superstite
    assert v == 339337.46  # il valore cached iniettato, non più una formula
    assert not (isinstance(v, str) and v.startswith("="))


def test_trim_zero_ref_rotti(minimal_pf_orti_bytes, tmp_path):
    wb, wbv = _extend_and_reload(minimal_pf_orti_bytes, tmp_path)
    pf = wb["Piano Finanziario"]
    cols = find_month_periods(pf)
    _inject_cached_freeze_values(wbv, cols)

    trim_before(wb, wbv, periodo(2027, 1))

    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                assert not (isinstance(cell.value, str) and "#REF!" in cell.value), (
                    f"{ws.title}!{cell.coordinate}: {cell.value}"
                )


def test_trim_cascata_e_totali_traslano_correttamente(minimal_pf_orti_bytes, tmp_path):
    """Verifica puntuale che delete_cols (che NON traduce le formule) sia stato
    compensato correttamente: la cascata r4 delle colonne superstiti dopo la
    prima punta alla colonna precedente REALE (non a un riferimento fantasma
    della vecchia posizione), e TOTALI (self-ref + ultimo mese) segue lo shift
    fisico."""
    wb, wbv = _extend_and_reload(minimal_pf_orti_bytes, tmp_path)
    pf = wb["Piano Finanziario"]
    cols = find_month_periods(pf)
    _inject_cached_freeze_values(wbv, cols)

    trim_before(wb, wbv, periodo(2027, 1))

    cols = find_month_periods(pf)
    c_feb = cols[periodo(2027, 2)]
    c_gen = cols[periodo(2027, 1)]
    assert pf.cell(4, c_feb).value == f"={get_column_letter(c_gen)}37"

    totali_col = 9  # TOTALI: era R(18) prima del trim, -9 colonne = I(9)
    assert pf.cell(2, totali_col).value == "TOTALI"
    c_giu = cols[periodo(2027, 6)]
    last_col_l = get_column_letter(c_giu)
    assert pf.cell(37, totali_col).value == f"={last_col_l}37"  # ultimo mese, shiftato
    assert pf.cell(29, totali_col).value == "=I12-I27"  # self-ref, shiftato


def test_trim_righe_15_16_cross_sheet_seguono_lo_shift(minimal_pf_orti_bytes, tmp_path):
    """Passata 4 (Translator post-delete) si applica anche ai riferimenti
    cross-sheet di riga 15/16 (Utenze!<col>3, 'Materie Prime-Consumo '!<col>3)
    — non solo alle formule same-sheet (r4/r12/r27/r29/r37, già coperte da
    test_trim_cascata_e_totali_traslano_correttamente). Verifica per PIU' di
    una colonna 2027 superstite, con la lettera attesa CALCOLATA (non
    hardcoded) dal mapping periodo->colonna del master dopo il trim.

    Nota sull'invariante scelta: extend_to costruisce questi riferimenti
    riusando la STESSA lettera della colonna master per il ref a Utenze (mai
    la colonna del periodo corrispondente nel foglio dettaglio) — verificato
    anche sul fixture NON esteso/NON trimmato: master APRILE (col C, prima
    colonna in assoluto) referenzia già "Utenze!C3", che in Utenze non è
    nemmeno un mese (è la colonna C='Utenze!C3'=SUM(D3:L3), il totale di
    riga — i mesi di Utenze iniziano a D, un offset di 1 colonna rispetto al
    master). È un artefatto di costruzione del fixture condiviso
    (`_build_minimal_pf_orti` in conftest.py, preesistente da prima di
    questo task, mai asserito da nessun test finora) — NON qualcosa che
    trim_before introduce o deve correggere: l'unica garanzia che
    extend_to offre (e che trim_before deve preservare) è "stessa lettera
    del master", non "stesso periodo nel foglio dettaglio". Per questo
    l'assert qui sotto confronta col mapping periodo->colonna del MASTER
    (non di Utenze/Materie Prime), calcolato dopo il trim."""
    wb, wbv = _extend_and_reload(minimal_pf_orti_bytes, tmp_path)
    pf = wb["Piano Finanziario"]
    cols = find_month_periods(pf)
    _inject_cached_freeze_values(wbv, cols)

    trim_before(wb, wbv, periodo(2027, 1))

    cols = find_month_periods(pf)
    for per in (periodo(2027, 1), periodo(2027, 3), periodo(2027, 6)):
        c = cols[per]
        cl = get_column_letter(c)
        assert pf.cell(15, c).value == f"=Utenze!{cl}3", periodo_anno_mese(per)
        assert pf.cell(16, c).value == f"='Materie Prime-Consumo '!{cl}3", (
            periodo_anno_mese(per)
        )


def test_trim_fail_loud_senza_valore_cached(minimal_pf_orti_bytes, tmp_path):
    """Se una formula da congelare non ha valore cached (file mai aperto/salvato
    in Excel dopo l'ultima modifica), trim_before deve esplodere con un
    messaggio chiaro — mai perdere silenziosamente una formula."""
    wb, wbv = _extend_and_reload(minimal_pf_orti_bytes, tmp_path)
    # NON iniettiamo alcun valore cached: wbv resta com'è (tutto None sulle formule).

    with pytest.raises(ValueError, match="apri e salva il file in Excel"):
        trim_before(wb, wbv, periodo(2027, 1))


def test_trim_no_op_se_nulla_da_eliminare(minimal_pf_orti_bytes, tmp_path):
    wb, wbv = _extend_and_reload(minimal_pf_orti_bytes, tmp_path)
    assert trim_before(wb, wbv, periodo(2026, 4)) == []  # cutoff = primo mese esistente


def test_trim_salta_fogli_di_servizio(minimal_pf_orti_bytes, tmp_path):
    """DA MAPPARE/ESCLUSI non hanno anno dichiarato: trim_before deve saltarli
    per titolo come extend_to, non farli esplodere su find_month_periods."""
    wb, wbv = _extend_and_reload(minimal_pf_orti_bytes, tmp_path)
    da_mappare = wb.create_sheet("DA MAPPARE")
    for i, m in enumerate(_MESI_ORDINATI):
        da_mappare.cell(2, 3 + i, m)

    pf = wb["Piano Finanziario"]
    cols = find_month_periods(pf)
    _inject_cached_freeze_values(wbv, cols)

    trim_before(wb, wbv, periodo(2027, 1))  # non deve sollevare
    assert da_mappare.max_column == 14  # non toccato


def test_trim_merge_riga1_non_trasla_ma_non_rompe(minimal_pf_orti_bytes, tmp_path):
    """openpyxl.delete_cols NON trasla i MergedCellRange (verificato empiricamente:
    resta al suo indirizzo assoluto, indipendentemente da quali colonne vengono
    fisicamente rimosse a sinistra). Questo test documenta il comportamento e
    verifica che trim_before non esploda in presenza di un merge sul foglio —
    replica il pattern ' Varie ed Eventuali' del Task 8 (merge decorativo I1:O1,
    ben a destra delle colonne che qui vengono eliminate)."""
    wb, wbv = _extend_and_reload(minimal_pf_orti_bytes, tmp_path)

    def _build_ve(target_wb):
        ve = target_wb.create_sheet(" Varie ed Eventuali")
        ve["D1"] = 2026
        mesi = _MESI_ORDINATI[3:12]  # APRILE..DICEMBRE
        for i, m in enumerate(mesi):
            ve.cell(2, 4 + i, m)
        ve["C3"] = "=SUM(D3:L3)"
        for i in range(9):
            col = 4 + i
            cl = get_column_letter(col)
            ve.cell(3, col, f"=SUM({cl}4:{cl}50)")
        ve.merge_cells("I1:O1")
        return ve

    ve = _build_ve(wb)
    _build_ve(wbv)  # wb_values è il gemello data_only=True DELLO STESSO file:
    # qui creato ad-hoc nel test, va tenuto in sync a mano su entrambi.

    pf = wb["Piano Finanziario"]
    cols = find_month_periods(pf)
    # cutoff = LUGLIO 2026: elimina APR-GIU (C,D,E,F -> qui APR..GIU su PF), la
    # cascata r4 della nuova prima superstite (LUGLIO) referenzia il GIUGNO
    # eliminato: congela anche questa (cutoff diverso dagli altri test ->
    # cella diversa da quella di _inject_cached_freeze_values).
    wbv["Piano Finanziario"].cell(4, cols[periodo(2026, 7)]).value = 100000.0
    wbv["Piano Finanziario"].cell(12, 18).value = 900.0  # TOTALI, stesso motivo
    wbv["Piano Finanziario"].cell(27, 18).value = 2700.0

    # Il nuovo target del marker (G, posizione 7) è FUORI dal merge I1:O1
    # (9-15): niente da congelare su questo foglio (nessuna cascata cross-
    # colonna su ' Varie ed Eventuali', solo SUM same-column), quindi il
    # marker si scrive normalmente.
    trim_before(
        wb, wbv, periodo(2026, 7)
    )  # non deve sollevare AttributeError su MergedCell

    cols_ve = find_month_periods(ve)
    assert min(cols_ve) == periodo(2026, 7)
    # il merge resta al suo indirizzo assoluto (I1:O1): openpyxl non lo trasla.
    assert "I1:O1" in {str(r) for r in ve.merged_cells.ranges}


def test_trim_poi_rotate_smoke(minimal_pf_orti_bytes, tmp_path):
    """Golden-smoke Step 4 del brief: dopo extend+trim, rotate() su un periodo
    chiuso nell'orizzonte superstite non solleva e i controlli danno ERR=0."""
    wb, wbv = _extend_and_reload(minimal_pf_orti_bytes, tmp_path)
    pf = wb["Piano Finanziario"]
    cols = find_month_periods(pf)
    _inject_cached_freeze_values(wbv, cols)
    trim_before(wb, wbv, periodo(2027, 1))
    pf_path = tmp_path / "trimmed.xlsx"
    wb.save(pf_path)

    P = lambda m: periodo(2027, m)  # noqa: E731
    fornitori_csv = tmp_path / "d_fornitori.csv"
    fornitori_csv.write_text(
        "codice_fornitore,nome_esolver,nome_pf,voce_id,is_intercompany,is_excluded,exclude_reason,societa_id\n"
        "570913,Energia elettrica,Energia elettrica,USCITE_UTENZE,False,False,,ORTI\n"
        "18,Acqua - Ausino,Acqua - Ausino,USCITE_UTENZE,False,False,,ORTI\n"
        "92,Amalfi sei esse,Amalfi sei esse,USCITE_MATERIE_PRIME,False,False,,ORTI\n"
    )
    scad_df = pd.DataFrame(
        [
            {
                "codice_fornitore": 18,
                "nome": "Acqua Ausino",
                "totale": -500.0,
                "scaduto": 0.0,
                f"mese_{P(2)}": -500.0,
                f"mese_{P(3)}": 0.0,
            },
        ]
    )

    result = rotate(
        pf_path=pf_path,
        scad_df=scad_df,
        bucket_periodi=[P(2), P(3)],
        societa="ORTI",
        periodo_chiuso=P(1),
        data_saldo=date(2027, 1, 31),
        saldi={"MPS": 251897.54, "Intesa": 87439.92, "MPS_KROSS": 0.0, "UNICREDIT": 0.0},  # Kross+Unicredit obbligatori dal 2026-10-26
        fornitori_csv=fornitori_csv,
        out_dir=tmp_path / "out",
        unmapped_policy=UnmappedPolicy.FAIL,
    )

    assert result.failed is False
    assert result.n_controlli_err == 0


# ── Controlli: l'allungamento deve riscrivere i check ancorati all'orizzonte ──
#
# Caso reale (ORTI_PF_2026-10 allungato a 2029-12, 2026-11-03): i controlli dei
# blocchi 9/10 restavano ancorati a R (vecchia TOTALI) e C:Q → 5 ERRORE su 25;
# gli altri 20 guardavano solo fino a Q. insert_cols non tocca le formule di
# un altro foglio, quindi le riscrive extend_to.


def _wb_con_controlli() -> openpyxl.Workbook:
    """Master minimo: mesi C..Q (apr 2026 – giu 2027), TOTALI in R, mese chiuso
    SETTEMBRE (H), dettaglio Utenze con mesi D..R. Controlli nello stile del
    foglio reale (esplicito per cella + matriciali + colonna totali)."""
    from openpyxl.worksheet.formula import ArrayFormula

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    pf = wb.create_sheet("Piano Finanziario")
    pf["C1"], pf["L1"] = 2026, 2027
    mesi = _MESI_ORDINATI[3:] + _MESI_ORDINATI[:6]  # APRILE..DICEMBRE, GENNAIO..GIUGNO
    for i, m in enumerate(mesi):
        pf.cell(2, 3 + i, m)
    pf["R2"] = "TOTALI"
    for c in range(3, 18):  # C..Q
        L = get_column_letter(c)
        pf.cell(4, c, 100.0 if c <= 8 else f"={get_column_letter(c - 1)}37")
        pf.cell(6, c, 10.0)
        pf.cell(12, c, f"=SUM({L}6:{L}11)")
        pf.cell(29, c, f"={L}12-{L}27")
        pf.cell(37, c, f"={L}4+{L}29")
    pf["R12"], pf["R37"] = "=SUM(C12:Q12)", "=Q37"

    ut = wb.create_sheet("Utenze")
    ut["D1"], ut["M1"] = 2026, 2027
    for i, m in enumerate(mesi):
        ut.cell(2, 4 + i, m)
    for c in range(4, 19):
        L = get_column_letter(c)
        ut.cell(3, c, f"=SUM({L}4:{L}10)")

    P = "'Piano Finanziario'!"
    ct = wb.create_sheet("Controlli")
    ct["A4"] = "C4:H4 = saldi iniziali hardcoded (mesi chiusi), I4:Q4 = formula (mesi aperti)?"
    ct["B4"] = (
        "=IF(AND("
        + ",".join(f"NOT(_xlfn.ISFORMULA({P}{get_column_letter(c)}4))" for c in range(3, 9))
        + ","
        + ",".join(f"_xlfn.ISFORMULA({P}{get_column_letter(c)}4)" for c in range(9, 18))
        + '),"OK","ERRORE")'
    )
    ct["A5"] = "I4 = H37 (ottobre parte da saldo reale settembre)?"
    ct["B5"] = f'=IF({P}I4={P}H37,"OK","ERRORE")'
    ct["A6"] = "Catena I4:Q4 = mese prec riga 37?"
    ct["B6"] = (
        "=IF(AND("
        + ",".join(
            f"{P}{get_column_letter(c)}4={P}{get_column_letter(c - 1)}37" for c in range(9, 18)
        )
        + '),"OK","ERRORE")'
    )
    ct["A7"], ct["B7"] = "Primo mese proiettato:", f"={P}H2"
    ct["A10"] = "Riga 12 = SUM(6:11) per mesi C:Q?"
    ct["B10"] = ArrayFormula(
        "B10", f'=IF(SUMPRODUCT(--(ROUND({P}C12:Q12-{P}C6:Q6,2)<>0))=0,"OK","ERRORE")'
    )
    ct["A22"] = "Riga 15 — Utenze"
    ct["B22"] = ArrayFormula(
        "B22", f'=IF(SUMPRODUCT(--(ROUND({P}C15:Q15-Utenze!D3:R3,2)<>0))=0,"OK","ERRORE")'
    )
    ct["A39"] = "9. COLONNA TOTALI (R)"
    ct["A40"] = "R12 Totale Entrate = SUM(C12:Q12)?"
    ct["B40"] = f'=IF(ROUND({P}R12-SUM({P}C12:Q12),2)=0,"OK","ERRORE")'
    ct["A45"] = "R6:R11 Entrate per voce = SUM(C:Q)?"
    ct["B45"] = ArrayFormula(
        "B45",
        f'=IF(SUMPRODUCT(--(ROUND({P}R6:R11-MMULT(0+{P}C6:Q11,ROW({P}C1:C15)^0),2)<>0))=0,"OK","ERRORE")',
    )
    ct["A47"] = "R37 = Q37 e R45 = Q45 (saldo finale = ultimo mese)?"
    ct["B47"] = f'=IF(AND(ROUND({P}R37-{P}Q37,2)=0,ROUND({P}R45-{P}Q45,2)=0),"OK","ERRORE")'
    ct["B49"] = '=IF(COUNTIF(B4:B47,"ERRORE")=0,"OK","ERRORI")'
    return wb


def _t(v):
    return getattr(v, "text", v)


def test_extend_riscrive_i_controlli_sull_orizzonte_intero():
    wb = _wb_con_controlli()
    extend_to(wb, periodo(2027, 12))  # +6 mesi: ultimo mese W, TOTALI X, 21 mesi
    ct = wb["Controlli"]
    P = "'Piano Finanziario'!"
    # blocchi 2-8: gli intervalli PF arrivano all'ultimo mese, i dettagli a X (D..X)
    assert f"{P}C12:W12-{P}C6:W6" in _t(ct["B10"].value)
    assert f"{P}C15:W15-Utenze!D3:X3" in _t(ct["B22"].value)
    # blocco 9/10: la colonna totali segue lo spostamento, i range coprono C:W
    assert _t(ct["B40"].value) == f'=IF(ROUND({P}X12-SUM({P}C12:W12),2)=0,"OK","ERRORE")'
    b45 = _t(ct["B45"].value)
    assert f"{P}X6:X11-MMULT(0+{P}C6:W11,ROW({P}C1:C21)^0)" in b45
    assert _t(ct["B47"].value) == (
        f'=IF(AND(ROUND({P}X37-{P}W37,2)=0,ROUND({P}X45-{P}W45,2)=0),"OK","ERRORE")'
    )
    # blocco 1: catena fino all'ultimo mese, primo mese proiettato = ottobre (I)
    assert _t(ct["B6"].value).endswith(f'{P}W4={P}V37),"OK","ERRORE")')
    assert f"_xlfn.ISFORMULA({P}W4)" in _t(ct["B4"].value)
    assert _t(ct["B7"].value) == f"={P}I2"
    # riferimenti al foglio Controlli stesso: intatti
    assert _t(ct["B49"].value) == '=IF(COUNTIF(B4:B47,"ERRORE")=0,"OK","ERRORI")'
    # etichette in colonna A seguono le colonne
    assert ct["A10"].value == "Riga 12 = SUM(6:11) per mesi C:W?"
    assert ct["A39"].value == "9. COLONNA TOTALI (X)"
    assert ct["A47"].value.startswith("X37 = W37 e X45 = W45")
    # le formule-array restano array
    from openpyxl.worksheet.formula import ArrayFormula

    assert isinstance(ct["B10"].value, ArrayFormula)
    assert isinstance(ct["B45"].value, ArrayFormula)


def test_extend_controlli_idempotente():
    wb = _wb_con_controlli()
    extend_to(wb, periodo(2027, 12))
    prima = {c.coordinate: _t(c.value) for row in wb["Controlli"].iter_rows() for c in row}
    extend_to(wb, periodo(2027, 12))
    dopo = {c.coordinate: _t(c.value) for row in wb["Controlli"].iter_rows() for c in row}
    assert prima == dopo


def test_extend_senza_foglio_controlli_non_cambia_nulla():
    wb = _wb_con_controlli()
    wb.remove(wb["Controlli"])
    changed = extend_to(wb, periodo(2027, 12))
    assert "Controlli" not in wb.sheetnames
    assert not any("Controlli" in c for c in changed)


def test_extend_controlli_gia_stantii_vengono_riallineati():
    """Caso reale: un file già allungato in passato SENZA aggiornare i controlli
    (pf-rotate con il motore vecchio): i mesi arrivano a T e TOTALI è in U, ma i
    check citano ancora Q/R. L'orizzonte dei check si legge dalle formule, non
    da uno stato "prima": il riallineamento deve avvenire lo stesso."""
    from verticals.condges.pf_rotate.controlli_sheet import widen_controlli
    from verticals.condges.pf_rotate.extend import _extend_sheet

    wb = _wb_con_controlli()
    for name in wb.sheetnames:  # allunga i fogli senza passare da extend_to
        if name != "Controlli":
            _extend_sheet(wb[name], periodo(2027, 9))
    P = "'Piano Finanziario'!"
    assert f"{P}R12-SUM({P}C12:Q12)" in _t(wb["Controlli"]["B40"].value)  # stantio
    widen_controlli(wb)
    assert _t(wb["Controlli"]["B40"].value) == (
        f'=IF(ROUND({P}U12-SUM({P}C12:T12),2)=0,"OK","ERRORE")'
    )
    assert f"{P}C15:T15-Utenze!D3:U3" in _t(wb["Controlli"]["B22"].value)
    assert f"ROW({P}C1:C18)^0" in _t(wb["Controlli"]["B45"].value)


def test_extend_controlli_senza_colonna_totali_non_tocca():
    wb = _wb_con_controlli()
    pf = wb["Piano Finanziario"]
    pf["R2"], pf["R12"], pf["R37"] = None, None, None
    b40 = _t(wb["Controlli"]["B40"].value)
    extend_to(wb, periodo(2027, 12))
    assert _t(wb["Controlli"]["B40"].value) == b40
