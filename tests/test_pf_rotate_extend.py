from datetime import date

import openpyxl
import pandas as pd
import pytest
from io import BytesIO
from openpyxl.utils import get_column_letter

from verticals.condges.pf_rotate.excel_model import MESI_IT, find_month_periods, periodo
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
        saldi={"MPS": 251897.54, "Intesa": 87439.92},
        fornitori_csv=fornitori_csv,
        out_dir=tmp_path / "out",
        unmapped_policy=UnmappedPolicy.FAIL,
    )

    assert result.failed is False
    assert result.n_controlli_err == 0
