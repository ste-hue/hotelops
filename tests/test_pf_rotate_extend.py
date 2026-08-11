import openpyxl
from io import BytesIO

from verticals.condges.pf_rotate.excel_model import find_month_periods, periodo
from verticals.condges.pf_rotate.extend import extend_to


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
