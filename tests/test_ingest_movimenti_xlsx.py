"""Tests for XLSX movimenti contabili parser."""

import openpyxl
import pytest
from pathlib import Path


def _make_xlsx(tmp_path: Path, rows: list[list]) -> Path:
    """Create a minimal XLSX file with the Esolver report layout."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Foglio1"
    for row in rows:
        ws.append(row)
    path = tmp_path / "movimenticontabili.xlsx"
    wb.save(path)
    return path


SAMPLE_ROWS = [
    [
        "S:\\ESOLVER\\PROG32\\LOGO.bmp", "ORTI S.R.L.", "Data 30/03/26 - 11.55",
        None, "Op. STEFANO", "2026-02-26", "PNC 1", None,
        "702 - Pagamenti fornitori", "330301", 1152, "ROVIELLO S.R.L.",
        "Pagamento con Bonifico SEPA FT 678", 452.74, 0,
        0, 0, None, 452.74, 0, None, 452.74, 0, 452.74, 0, None,
    ],
    [
        "S:\\ESOLVER\\PROG32\\LOGO.bmp", "ORTI S.R.L.", "Data 30/03/26 - 11.55",
        None, "Op. STEFANO", "2026-02-26", "PNC 1", None,
        "702 - Pagamenti fornitori", "750191", 0,
        "Costo per bonifici verso altre banche",
        "Pagamento con Bonifico SEPA FT 678", 1.75, 0,
        0, 0, None, 454.49, 0, None, 454.49, 0, 454.49, 0, None,
    ],
    [
        "S:\\ESOLVER\\PROG32\\LOGO.bmp", "ORTI S.R.L.", "Data 30/03/26 - 11.55",
        None, "Op. STEFANO", "2026-02-26", "PNC 1", None,
        "702 - Pagamenti fornitori", "190101", 2,
        "Banca c/c - MONTE DEI PASCHI DI SIENA S.P.A.",
        "Pagamento con Bonifico SEPA FT 678", 0, 454.49,
        0, 0, None, 454.49, 454.49, None, 454.49, 454.49, 454.49, 454.49, None,
    ],
    [
        "S:\\ESOLVER\\PROG32\\LOGO.bmp", "ORTI S.R.L.", "Data 30/03/26 - 11.55",
        None, "Op. STEFANO", "2026-03-02", "PNC 1", None,
        "701 - DARE/AVERE", "390521", 0, "CAPARRA",
        "CAPARRA_HOTEL FELICITALIA", 0, 916.0,
        0, 0, None, 916.0, 916.0, None, 916.0, 916.0, 916.0, 916.0, None,
    ],
]


class TestParseFileXlsx:
    def test_basic_parsing(self, tmp_path):
        from ingest.flussi.ingest_movimenti_contabili import parse_file_xlsx
        import logging

        path = _make_xlsx(tmp_path, SAMPLE_ROWS)
        logger = logging.getLogger("test")
        rows = parse_file_xlsx(path, "ORTI", logger)

        assert len(rows) == 4

    def test_field_mapping(self, tmp_path):
        from ingest.flussi.ingest_movimenti_contabili import parse_file_xlsx
        import logging

        path = _make_xlsx(tmp_path, SAMPLE_ROWS)
        logger = logging.getLogger("test")
        rows = parse_file_xlsx(path, "ORTI", logger)

        r0 = rows[0]
        assert r0["societa_id"] == "ORTI"
        assert r0["cod_conto"] == "330301"
        assert r0["cod_partitario"] == "1152"
        assert r0["rag_sociale"] == "ROVIELLO S.R.L."
        assert r0["causale_contabile"] == "Pagamento con Bonifico SEPA FT 678"
        assert r0["imp_dare"] == 452.74
        assert r0["imp_avere"] == 0.0
        assert r0["anno"] == 2026
        assert r0["mese"] == 2
        assert r0["data_registrazione"] == "2026-02-26"
        assert r0["sigla_doc"] == "PNC"
        assert r0["tipo_documento"] == "702 - Pagamenti fornitori"

    def test_hash_uniqueness(self, tmp_path):
        from ingest.flussi.ingest_movimenti_contabili import parse_file_xlsx
        import logging

        path = _make_xlsx(tmp_path, SAMPLE_ROWS)
        logger = logging.getLogger("test")
        rows = parse_file_xlsx(path, "ORTI", logger)

        hashes = [r["hash_riga"] for r in rows]
        assert len(hashes) == len(set(hashes)), "Hashes must be unique"

    def test_idempotent_hashes(self, tmp_path):
        """Same file parsed twice produces identical hashes."""
        from ingest.flussi.ingest_movimenti_contabili import parse_file_xlsx
        import logging

        path = _make_xlsx(tmp_path, SAMPLE_ROWS)
        logger = logging.getLogger("test")
        rows1 = parse_file_xlsx(path, "ORTI", logger)
        rows2 = parse_file_xlsx(path, "ORTI", logger)

        assert [r["hash_riga"] for r in rows1] == [r["hash_riga"] for r in rows2]

    def test_all_required_fields_present(self, tmp_path):
        from ingest.flussi.ingest_movimenti_contabili import parse_file_xlsx, FACT_HEADER
        import logging

        path = _make_xlsx(tmp_path, SAMPLE_ROWS)
        logger = logging.getLogger("test")
        rows = parse_file_xlsx(path, "ORTI", logger)

        for row in rows:
            for field in FACT_HEADER:
                assert field in row, f"Missing field: {field}"

    def test_march_data(self, tmp_path):
        """Row 3 is March — verify date extraction from datetime col."""
        from ingest.flussi.ingest_movimenti_contabili import parse_file_xlsx
        import logging

        path = _make_xlsx(tmp_path, SAMPLE_ROWS)
        logger = logging.getLogger("test")
        rows = parse_file_xlsx(path, "ORTI", logger)

        r3 = rows[3]
        assert r3["anno"] == 2026
        assert r3["mese"] == 3
        assert r3["data_registrazione"] == "2026-03-02"
        assert r3["imp_avere"] == 916.0

    def test_id_documento_and_progr_riga(self, tmp_path):
        """XLSX report does not expose Esolver document id, so id_documento is NULL.

        num_progr_riga is 1-based to align with legacy XLS parser output.
        """
        from ingest.flussi.ingest_movimenti_contabili import parse_file_xlsx
        import logging

        path = _make_xlsx(tmp_path, SAMPLE_ROWS)
        logger = logging.getLogger("test")
        rows = parse_file_xlsx(path, "ORTI", logger)

        assert rows[0]["id_documento"] is None
        assert rows[0]["num_progr_riga"] == 1  # first row within this PNC+date group
        assert rows[1]["num_progr_riga"] == 2  # second row

    def test_hash_content_based(self, tmp_path):
        """Same content → same hash. PNC/idx do not influence the hash.

        Regression: this contract is what allows dedup against legacy data and
        across re-extractions with different report layouts.
        """
        from ingest.flussi.ingest_movimenti_contabili import (
            make_hash_content,
            parse_file_xlsx,
        )
        import logging

        path = _make_xlsx(tmp_path, SAMPLE_ROWS)
        logger = logging.getLogger("test")
        rows = parse_file_xlsx(path, "ORTI", logger)

        r0 = rows[0]
        expected = make_hash_content(
            "ORTI",
            "2026-02-26",
            "330301",
            452.74,
            0.0,
            "Pagamento con Bonifico SEPA FT 678",
        )
        assert r0["hash_riga"] == expected
