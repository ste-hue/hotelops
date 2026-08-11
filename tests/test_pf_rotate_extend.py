import openpyxl
import pytest
from io import BytesIO
from openpyxl.utils import get_column_letter

from verticals.condges.pf_rotate.excel_model import MESI_IT, find_month_periods, periodo
from verticals.condges.pf_rotate.extend import extend_to

_MESI_ORDINATI = list(MESI_IT.keys())  # GENNAIO..DICEMBRE, ordine dict


def _wb(bytes_):
    return openpyxl.load_workbook(BytesIO(bytes_))


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
