"""Golden test per v_piano_finanziario_mensile (issue #122).

Query BQ live (@pytest.mark.bq, skip con HOTELOPS_SKIP_BQ=1).
Golden = rate mutui INTUR validate a mano il 2026-08-10 (audit chiave dedup):
Intesa 8.500,00 + MPS 1.2M 3.210,53 + MPS 75k 1.388,48 = 13.099,01/mese.
La vista deve sommare TUTTE le righe della fonte vincente, non tenerne una.
"""

from __future__ import annotations

import pytest

VIEW = "`hotelops-suite.hotelops.v_piano_finanziario_mensile`"

MUTUI_INTUR_MESE_2026 = 13099.01


def _rows(bq_client, sql):
    return [dict(r) for r in bq_client.query(sql).result()]


@pytest.mark.bq
def test_uscite_mutui_intur_2026(bq_client):
    """Ogni mese 2026 in finestra mostra la somma dei 3 mutui, non uno solo."""
    rows = _rows(
        bq_client,
        f"""
        SELECT mese, importo_budget
        FROM {VIEW}
        WHERE societa_id = 'INTUR' AND voce_id = 'USCITE_MUTUI' AND anno = 2026
        ORDER BY mese
    """,
    )
    assert rows, "nessuna riga USCITE_MUTUI INTUR 2026 in finestra"
    sbagliati = [r for r in rows if float(r["importo_budget"]) != MUTUI_INTUR_MESE_2026]
    assert not sbagliati, (
        f"mesi con importo diverso da {MUTUI_INTUR_MESE_2026}: {sbagliati}"
    )
