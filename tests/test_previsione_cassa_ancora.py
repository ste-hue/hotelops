"""L'ancora di v_previsione_cassa usa gli stessi conti obbligatori del registry (D3)."""

import re
from pathlib import Path

from verticals.condges.pf_rotate.saldi_registry import SALDI_REGISTRY, banche_richieste

VIEW = Path(__file__).resolve().parents[1] / "core/bq/views/v_previsione_cassa.sql"


def test_conti_richiesti_della_vista_coincidono_col_registry():
    sql = VIEW.read_text()
    blocco = sql.split("conti_richiesti AS (", 1)[1].split("\n),\n", 1)[0]
    coppie = set(re.findall(r"\('(\w+)'(?: AS societa_id)?, '(\w+)'", blocco))
    attese = {(s, b) for s in SALDI_REGISTRY for b in banche_richieste(s)}
    assert coppie == attese


def test_ancora_legge_estratto_conto_non_esolver():
    sql = VIEW.read_text().split("CREATE OR REPLACE VIEW", 1)[1]
    assert "f_saldi_banca_chiusura_mensile" in sql
    assert "f_saldi_banca_snapshot" not in sql
