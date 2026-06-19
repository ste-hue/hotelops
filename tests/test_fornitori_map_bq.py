"""BQ-backed d_fornitori: read (SELECT) + upsert (MERGE). Client mockato."""

from unittest.mock import MagicMock, patch

import pytest

from verticals.condges.pf_rotate import fornitori_map


def test_upsert_fornitore_bq_emits_merge():
    fake = MagicMock()
    with patch.object(fornitori_map, "_bq", return_value=fake):
        fornitori_map.upsert_fornitore_bq(
            codice_fornitore=264,
            nome_esolver="PANORAMA COMPANY S.R.L.",
            nome_pf="Fitto Ramo d' Azienda",
            voce_id="USCITE_CANONE_PASSIVO",
            societa_id="ORTI",
            is_intercompany=True,
        )
    fake.query.assert_called_once()
    sql = fake.query.call_args[0][0]
    assert "MERGE" in sql and "d_fornitori" in sql
    assert "WHEN MATCHED THEN UPDATE" in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    params = {
        p.name: p.value
        for p in fake.query.call_args[1]["job_config"].query_parameters
    }
    assert params["cod"] == 264
    assert params["soc"] == "ORTI"
    assert params["v"] == "USCITE_CANONE_PASSIVO"
    assert params["ic"] is True


def test_upsert_fornitore_bq_rejects_bad_codice():
    fake = MagicMock()
    with patch.object(fornitori_map, "_bq", return_value=fake):
        with pytest.raises(Exception):
            fornitori_map.upsert_fornitore_bq(
                codice_fornitore="non-int",
                nome_esolver="X",
                nome_pf="X",
                voce_id="USCITE_UTENZE",
                societa_id="ORTI",
            )
        fake.query.assert_not_called()  # fallisce alla validazione Pydantic, prima di BQ


def test_load_fornitori_bq_parses_and_filters():
    fake = MagicMock()
    row = MagicMock()
    row.codice_fornitore = 1
    row.nome_esolver = "LE CROISSANT SRL"
    row.nome_pf = "Le Croissant srl"
    row.voce_id = "USCITE_MATERIE_PRIME"
    row.is_intercompany = False
    row.is_excluded = False
    row.exclude_reason = None
    row.societa_id = "ORTI"
    fake.query.return_value.result.return_value = [row]
    with patch.object(fornitori_map, "_bq", return_value=fake):
        out = fornitori_map.load_fornitori_bq("ORTI")
    assert set(out) == {1}
    assert out[1].voce_id == "USCITE_MATERIE_PRIME"
    assert out[1].exclude_reason == ""  # None → ""
    sql = fake.query.call_args[0][0]
    assert "d_fornitori" in sql and "WHERE societa_id" in sql
