def test_banca_movimento_row_accepts_raw_object_id():
    from core.schemas import BancaMovimentoRow
    from datetime import date

    row = BancaMovimentoRow(
        hash_riga="abc",
        societa_id="ORTI",
        banca_id="MPS",
        data_operazione=date(2026, 5, 1),
        importo_netto=100.0,
        file_sorgente="test.csv",
        raw_object_id="raw-uuid-1",
    )
    assert row.raw_object_id == "raw-uuid-1"


def test_banca_movimento_row_raw_object_id_optional():
    from core.schemas import BancaMovimentoRow
    from datetime import date

    row = BancaMovimentoRow(
        hash_riga="abc",
        societa_id="ORTI",
        banca_id="MPS",
        data_operazione=date(2026, 5, 1),
        importo_netto=100.0,
        file_sorgente="test.csv",
    )
    assert row.raw_object_id is None
