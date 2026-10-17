"""Funzioni pure del freshness contract (spec 2026-09-09 §4-5)."""

from datetime import date

import pytest

from core.freshness import action_for, coverage_status, expected_through, status_for
from core.lineage.schemas import (
    AcquisitionContract,
    FreshnessContract,
    SourceDefinition,
)


def fc(**over) -> FreshnessContract:
    d = dict(tier="E", cadence="monthly", grain="daily", coverage_column="data")
    d.update(over)
    return FreshnessContract(**d)


def ac(**over) -> AcquisitionContract:
    d = dict(
        mode="SEMI",
        owner="Stefano",
        location="Homebanking MPS",
        report="Lista movimenti",
        filters="mese pieno",
    )
    d.update(over)
    return AcquisitionContract(**d)


def sd(**over) -> SourceDefinition:
    d = dict(
        source_name="MPS_BANCA_ORTI_APPEND",
        system="MPS",
        dataset="BANCA",
        societa="ORTI",
        lifecycle="APPEND",
        canonical_table="f_banche_movimenti",
        parser_module="ingest.banca.ingest",
        loop_targets=["cash_control"],
        promotion_policy="AUTO",
        detector_category="banca",
        raw_storage={"backend": "gcs", "bucket": "hotelops-raw"},
        freshness=fc(),
        acquisition=ac(),
    )
    d.update(over)
    return SourceDefinition(**d)


# ── expected_through ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "cadence,today,atteso",
    [
        ("daily", date(2026, 9, 9), date(2026, 9, 7)),
        ("weekly", date(2026, 9, 9), date(2026, 8, 30)),
        ("monthly", date(2026, 9, 9), date(2026, 8, 31)),
        ("monthly", date(2026, 1, 3), date(2025, 12, 31)),
        ("quarterly", date(2026, 9, 9), date(2026, 6, 30)),
        ("quarterly", date(2026, 1, 15), date(2025, 12, 31)),
        ("adhoc", date(2026, 9, 9), None),
    ],
)
def test_expected_through(cadence, today, atteso):
    assert expected_through(cadence, today) == atteso


# ── coverage_status: mensile di calendario con grazia ───────────────────────


def test_mensile_coperto_ok():
    assert coverage_status(fc(), date(2026, 8, 31), date(2026, 9, 9)) == "OK"


def test_mensile_in_grazia_e_due():
    # 9/9, grazia 10, coperto fino al 20/8 (≥ 31/7): in scadenza
    assert coverage_status(fc(), date(2026, 8, 20), date(2026, 9, 9)) == "DUE"


def test_mensile_giorno_di_grazia_incluso():
    assert (
        coverage_status(fc(grace_day=10), date(2026, 8, 20), date(2026, 9, 10)) == "DUE"
    )


def test_mensile_oltre_grazia_e_stale():
    assert (
        coverage_status(fc(grace_day=10), date(2026, 8, 20), date(2026, 9, 11))
        == "STALE"
    )


def test_mensile_grazia_20_esolver():
    assert (
        coverage_status(fc(grace_day=20), date(2026, 8, 14), date(2026, 9, 19)) == "DUE"
    )
    assert (
        coverage_status(fc(grace_day=20), date(2026, 8, 14), date(2026, 9, 21))
        == "STALE"
    )


def test_mensile_in_grazia_ma_manca_anche_il_mese_prima_e_stale():
    # 9/9, coperto solo fino al 30/6: manca luglio intero → rosso anche in grazia
    assert coverage_status(fc(), date(2026, 6, 30), date(2026, 9, 9)) == "STALE"


def test_mensile_senza_dati_e_stale():
    assert coverage_status(fc(), None, date(2026, 9, 9)) == "STALE"


def test_daily_weekly_eta_semplice():
    assert (
        coverage_status(fc(cadence="daily"), date(2026, 9, 7), date(2026, 9, 9)) == "OK"
    )
    assert (
        coverage_status(fc(cadence="daily"), date(2026, 9, 6), date(2026, 9, 9))
        == "STALE"
    )
    assert (
        coverage_status(fc(cadence="weekly"), date(2026, 8, 30), date(2026, 9, 9))
        == "OK"
    )
    assert (
        coverage_status(fc(cadence="weekly"), date(2026, 8, 29), date(2026, 9, 9))
        == "STALE"
    )


def test_quarterly_grazia_30_giorni():
    q = fc(cadence="quarterly", basis="raw", coverage_column=None)
    assert coverage_status(q, date(2026, 6, 30), date(2026, 7, 20)) == "OK"
    assert coverage_status(q, date(2026, 3, 31), date(2026, 7, 20)) == "DUE"
    assert coverage_status(q, date(2026, 3, 31), date(2026, 8, 5)) == "STALE"


def test_adhoc_mai_colorato():
    assert coverage_status(fc(cadence="adhoc"), None, date(2026, 9, 9)) == "OK"


# ── status_for ──────────────────────────────────────────────────────────────


def test_no_contract():
    assert status_for(None, None, None, date(2026, 9, 9), None) == "NO_CONTRACT"
    assert status_for(fc(), None, None, date(2026, 9, 9), None) == "NO_CONTRACT"


def test_dormant_vince_su_tutto():
    assert (
        status_for(fc(dormant="conto senza flussi"), ac(), None, date(2026, 9, 9), None)
        == "DORMANT"
    )


def test_auto_job_down():
    a = ac(mode="AUTO", owner="job", job="ingest_coperti")
    assert (
        status_for(fc(cadence="daily"), a, date(2026, 9, 1), date(2026, 9, 9), False)
        == "JOB_DOWN"
    )
    assert (
        status_for(fc(cadence="daily"), a, date(2026, 9, 1), date(2026, 9, 9), None)
        == "JOB_DOWN"
    )


def test_auto_dati_in_regola_senza_ricevuta():
    """Canonical fresca ma nessun run in f_pipeline_runs: il job gira, manca la ricevuta."""
    a = ac(mode="AUTO", owner="job", job="drive_fetch:RT")
    assert (
        status_for(fc(cadence="daily"), a, date(2026, 9, 8), date(2026, 9, 9), False)
        == "NO_RECEIPT"
    )
    assert (
        status_for(fc(cadence="monthly"), a, date(2026, 8, 31), date(2026, 9, 9), None)
        == "NO_RECEIPT"
    )


def test_auto_adhoc_senza_ricevuta_decide_il_dato_recente():
    """Per adhoc la copertura è OK per definizione: conta solo un dato nella finestra del job."""
    a = ac(mode="AUTO", owner="job", job="pec_fetch")
    assert (
        status_for(fc(cadence="adhoc"), a, None, date(2026, 9, 9), False) == "JOB_DOWN"
    )
    assert (
        status_for(fc(cadence="adhoc"), a, date(2026, 9, 3), date(2026, 9, 9), False)
        == "JOB_DOWN"
    )
    assert (
        status_for(fc(cadence="adhoc"), a, date(2026, 9, 8), date(2026, 9, 9), False)
        == "NO_RECEIPT"
    )


def test_auto_dati_fermi_senza_ricevuta_resta_job_down():
    a = ac(mode="AUTO", owner="job", job="ingest_coperti")
    assert (
        status_for(fc(cadence="daily"), a, date(2026, 8, 1), date(2026, 9, 9), False)
        == "JOB_DOWN"
    )


def test_auto_job_verde_dati_fermi():
    a = ac(mode="AUTO", owner="job", job="ingest_coperti")
    assert (
        status_for(fc(cadence="daily"), a, date(2026, 8, 1), date(2026, 9, 9), True)
        == "DATA_STUCK"
    )


def test_auto_tutto_verde():
    a = ac(mode="AUTO", owner="job", job="ingest_coperti")
    assert (
        status_for(fc(cadence="daily"), a, date(2026, 9, 8), date(2026, 9, 9), True)
        == "OK"
    )


def test_semi_ignora_job_ok():
    assert status_for(fc(), ac(), date(2026, 8, 31), date(2026, 9, 9), False) == "OK"


# ── action_for ──────────────────────────────────────────────────────────────


def test_nessuna_azione_se_ok_dormant_no_contract():
    for st in ("OK", "DORMANT", "NO_CONTRACT"):
        assert action_for(sd(), st, date(2026, 8, 31)) is None


def test_azione_semi_append_con_dal_e_capture():
    txt = action_for(sd(), "DUE", date(2026, 8, 20))
    assert txt.startswith(
        "→ Homebanking MPS › Lista movimenti › mese pieno › dal 21/08 (sovrapporre"
    )
    assert txt.endswith("› Stefano\n  poi: hotelops capture <file>")


def test_azione_manual_snapshot_intake_promote():
    s = sd(
        source_name="POWERBI_PRODUZIONE_ORTI_SNAPSHOT",
        lifecycle="SNAPSHOT",
        acquisition=ac(
            mode="MANUAL",
            location="Power BI PanoramaGroup",
            report="Daily Production Report",
            filters=None,
        ),
    )
    txt = action_for(s, "STALE", date(2026, 8, 15))
    assert "dal 16/08 (fotografia a oggi, sostituisce la precedente)" in txt
    assert txt.endswith(
        "poi: hotelops intake <file> --source-name POWERBI_PRODUZIONE_ORTI_SNAPSHOT"
        " && hotelops promote --raw-object-id <id>"
    )


def test_azione_basis_raw_senza_dal():
    s = sd(freshness=fc(basis="raw", coverage_column=None))
    txt = action_for(s, "STALE", date(2026, 7, 5))
    assert "dal " not in txt


def test_azione_auto():
    s = sd(
        acquisition=ac(
            mode="AUTO",
            owner="job",
            job="ingest_coperti",
            location="Google Sheet Scarico Coperti",
            report="form",
        )
    )
    assert action_for(s, "JOB_DOWN", None) == "→ controlla il job ingest_coperti"
    assert action_for(s, "DATA_STUCK", None) == (
        "→ job ingest_coperti verde, dati fermi: controlla la fonte Google Sheet Scarico Coperti"
    )
    assert action_for(s, "NO_RECEIPT", None) == (
        "→ dati in regola, nessun run di ingest_coperti in f_pipeline_runs: "
        "l'immagine del job scrive la ricevuta?"
    )
    assert action_for(s, "OK", None) is None
