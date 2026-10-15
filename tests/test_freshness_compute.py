"""compute/render_text/to_json con query finta (spec 2026-09-09 §6-7)."""

from datetime import date, datetime, timedelta, timezone

from core.freshness import compute, render_text, to_json, today_rome
from core.lineage.schemas import SourceDefinition
from core.lineage.source_resolver import SourceRegistry

NOW = datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc)


def _sd(name, **over):
    d = dict(
        source_name=name,
        system=name.split("_")[0],
        dataset="X",
        societa="ORTI",
        lifecycle="APPEND",
        canonical_table="f_banche_movimenti",
        parser_module="ingest.banca.ingest",
        loop_targets=["cash_control"],
        promotion_policy="AUTO",
        detector_category="banca",
        raw_storage={"backend": "gcs", "bucket": "hotelops-raw"},
        freshness={
            "tier": "E",
            "cadence": "monthly",
            "grain": "daily",
            "coverage_column": "data_operazione",
            "dims": ["banca_id"],
            "dim_filter": {"banca_id": ["MPS", "MPS_KROSS"]},
        },
        acquisition={
            "mode": "SEMI",
            "owner": "Stefano",
            "location": "Homebanking MPS",
            "report": "Lista movimenti",
            "filters": "mese pieno",
        },
    )
    d.update(over)
    return SourceDefinition(**d)


def _registry(*sds) -> SourceRegistry:
    return SourceRegistry({s.source_name: s for s in sds})


class FakeQuery:
    """Risponde per tabella: la SQL è ispezionata solo per capire quale query è."""

    def __init__(self, coverage=None, raw=None, jobs=None):
        self.coverage = coverage or {}  # canonical_table -> rows
        self.raw = raw or []
        self.jobs = jobs or []
        self.calls: list[str] = []

    def __call__(self, sql: str) -> list[dict]:
        self.calls.append(sql)
        if "f_raw_objects" in sql:
            return self.raw
        if "f_pipeline_runs" in sql:
            return self.jobs
        for table, rows in self.coverage.items():
            if f"hotelops.{table}" in sql:
                return rows
        return []


def test_today_rome_converte_da_utc():
    """Rome è UTC+2 a settembre: 22:30 UTC del 9 diventa 00:30 del 10 a Roma."""
    assert today_rome(datetime(2026, 9, 9, 22, 30, tzinfo=timezone.utc)) == date(
        2026, 9, 10
    )


def test_una_query_per_gruppo_tabella_e_tre_in_tutto_con_due_banche():
    mps = _sd("MPS_BANCA_ORTI_APPEND")
    sella = _sd(
        "SELLA_BANCA_INTUR_APPEND",
        societa="INTUR",
        freshness={**mps.freshness.model_dump(), "dim_filter": {"banca_id": ["SELLA"]}},
    )
    q = FakeQuery(
        coverage={
            "f_banche_movimenti": [
                {"societa_id": "ORTI", "banca_id": "MPS", "covered": date(2026, 8, 20)},
                {
                    "societa_id": "ORTI",
                    "banca_id": "MPS_KROSS",
                    "covered": date(2026, 8, 18),
                },
                {
                    "societa_id": "ORTI",
                    "banca_id": "INTESA",
                    "covered": date(2026, 6, 5),
                },
                {
                    "societa_id": "INTUR",
                    "banca_id": "SELLA",
                    "covered": date(2026, 8, 31),
                },
            ]
        }
    )
    items = compute(_registry(mps, sella), q, now=NOW)
    assert len(q.calls) == 3
    by = {i.source_name: i for i in items}
    assert by["MPS_BANCA_ORTI_APPEND"].covered_through == date(
        2026, 8, 18
    )  # la peggiore delle sue dims
    assert by["MPS_BANCA_ORTI_APPEND"].status == "DUE"
    assert by["MPS_BANCA_ORTI_APPEND"].per_dim == [
        ({"banca_id": "MPS"}, date(2026, 8, 20)),
        ({"banca_id": "MPS_KROSS"}, date(2026, 8, 18)),
    ]
    assert by["SELLA_BANCA_INTUR_APPEND"].status == "OK"
    # INTESA non appartiene a nessuna delle due: non compare
    assert all(
        d[0]["banca_id"] != "INTESA" for d in by["MPS_BANCA_ORTI_APPEND"].per_dim
    )


def test_basis_raw_usa_ultimo_intake():
    fatt = _sd(
        "ESOLVER_FATTUREACQUISTO_ORTI_APPEND",
        canonical_table="f_fatture_righe",
        freshness={
            "tier": "E",
            "cadence": "monthly",
            "grace_day": 20,
            "grain": "daily",
            "basis": "raw",
        },
        acquisition={
            "mode": "MANUAL",
            "owner": "Stefano",
            "location": "Esolver",
            "report": "Lista fatture acquisto",
        },
    )
    q = FakeQuery(
        raw=[
            {
                "source_name": "ESOLVER_FATTUREACQUISTO_ORTI_APPEND",
                "last_intake": date(2026, 7, 5),
            }
        ]
    )
    [it] = compute(_registry(fatt), q, now=NOW)
    assert it.covered_through == date(2026, 7, 5)
    assert it.status == "STALE"
    assert "dal " not in it.action
    assert len([c for c in q.calls if "MAX(" in c and "f_fatture_righe" in c]) == 0


def test_auto_job_ok_entro_36h_e_data_stuck():
    cop = _sd(
        "ORTI_COPERTI_ORTI_APPEND",
        canonical_table="f_coperti_giornalieri",
        freshness={
            "tier": "R",
            "cadence": "daily",
            "grain": "daily",
            "coverage_column": "data_servizio",
        },
        acquisition={
            "mode": "AUTO",
            "owner": "job",
            "job": "ingest_coperti",
            "location": "Google Sheet Scarico Coperti",
            "report": "form",
        },
    )
    q = FakeQuery(
        coverage={
            "f_coperti_giornalieri": [
                {"societa_id": "ORTI", "covered": date(2026, 8, 1)}
            ]
        },
        jobs=[{"pipeline_name": "ingest_coperti", "last_ok": NOW - timedelta(hours=2)}],
    )
    [it] = compute(_registry(cop), q, now=NOW)
    assert it.status == "DATA_STUCK"
    q.jobs = [{"pipeline_name": "ingest_coperti", "last_ok": NOW - timedelta(hours=40)}]
    [it] = compute(_registry(cop), q, now=NOW)
    assert it.status == "JOB_DOWN"
    # dati freschi, nessuna ricevuta: non è un job fermo
    q.coverage["f_coperti_giornalieri"] = [
        {"societa_id": "ORTI", "covered": date(2026, 9, 8)}
    ]
    q.jobs = []
    [it] = compute(_registry(cop), q, now=NOW)
    assert it.status == "NO_RECEIPT"
    assert "ricevuta" in it.action
    assert "! " in render_text([it], today_rome(NOW))


def test_societa_non_filtrabile_usa_solo_dim_filter():
    vigna = _sd(
        "PEC_MAILBOX_VIGNA_APPEND",
        system="PEC",
        societa="VIGNA",
        canonical_table="f_pec_messages",
        detector_category="pec_mbox",
        casella="vineyardamalficoast@pec.it",
        entity_id="VIGNA",
        freshness={"tier": "R", "cadence": "adhoc", "grain": "daily", "basis": "raw"},
        acquisition={
            "mode": "AUTO",
            "owner": "job",
            "job": "pec_fetch",
            "location": "PEC Aruba",
            "report": "IMAP",
        },
    )
    q = FakeQuery(
        raw=[
            {"source_name": "PEC_MAILBOX_VIGNA_APPEND", "last_intake": date(2026, 8, 3)}
        ],
        jobs=[{"pipeline_name": "pec_fetch", "last_ok": NOW - timedelta(hours=8)}],
    )
    [it] = compute(_registry(vigna), q, now=NOW)
    assert it.status == "OK"  # adhoc: la copertura non colora, il job sì
    assert it.covered_through == date(2026, 8, 3)


def test_senza_contratto_e_ordinamento():
    no = _sd(
        "HOTELCUBE_ACCODAMENTI_ORTI_APPEND",
        freshness=None,
        acquisition=None,
        loop_targets=["daily_reconciliation", "cash_control"],
    )
    dorm = _sd(
        "INTESA_BANCA_ORTI_APPEND",
        freshness={
            "tier": "E",
            "cadence": "monthly",
            "grain": "daily",
            "coverage_column": "data_operazione",
            "dims": ["banca_id"],
            "dim_filter": {"banca_id": ["INTESA"]},
            "dormant": "conto senza flussi",
        },
    )
    stale = _sd("MPS_BANCA_ORTI_APPEND", loop_targets=["cash_control", "monthly_close"])
    q = FakeQuery(
        coverage={
            "f_banche_movimenti": [
                {"societa_id": "ORTI", "banca_id": "MPS", "covered": date(2026, 6, 30)}
            ]
        }
    )
    items = compute(_registry(no, dorm, stale), q, now=NOW)
    assert [i.source_name for i in items] == [
        "MPS_BANCA_ORTI_APPEND",
        "INTESA_BANCA_ORTI_APPEND",
        "HOTELCUBE_ACCODAMENTI_ORTI_APPEND",
    ]
    assert items[1].status == "DORMANT" and items[2].status == "NO_CONTRACT"


def test_render_text_e_to_json():
    stale = _sd("MPS_BANCA_ORTI_APPEND", loop_targets=["cash_control", "monthly_close"])
    raw_only = _sd(
        "HOTELCUBE_STAMPACASSA_ORTI_APPEND",
        promotion_policy="RAW_ONLY",
        loop_targets=[],
        canonical_table="f_stampa_cassa",
        freshness={
            "tier": "M",
            "cadence": "adhoc",
            "grain": "snapshot",
            "basis": "raw",
        },
        acquisition={
            "mode": "MANUAL",
            "owner": "Stefano",
            "location": "HotelCube",
            "report": "Stampa Cassa",
        },
    )
    q = FakeQuery(
        coverage={
            "f_banche_movimenti": [
                {"societa_id": "ORTI", "banca_id": "MPS", "covered": date(2026, 6, 30)}
            ]
        },
        raw=[
            {
                "source_name": "HOTELCUBE_STAMPACASSA_ORTI_APPEND",
                "last_intake": date(2026, 7, 12),
            }
        ],
    )
    items = compute(_registry(stale, raw_only), q, now=NOW)

    txt = render_text(items, today=NOW.date())
    assert "SORGENTI — 2026-09-09" in txt
    assert "🔴 MPS_BANCA_ORTI_APPEND" in txt
    assert "coperto 30/06 · atteso 31/08 · 71gg" in txt
    assert "→ Homebanking MPS › Lista movimenti › mese pieno › dal 01/07" in txt
    assert "blocca: cash_control, monthly_close" in txt
    assert "STAMPACASSA" not in txt  # RAW_ONLY nascosta
    assert "STAMPACASSA" in render_text(items, today=NOW.date(), show_all=True)

    js = to_json(items)
    assert js[0]["source_name"] == "MPS_BANCA_ORTI_APPEND"
    assert js[0]["status"] == "STALE"
    assert js[0]["covered_through"] == "2026-06-30"
    assert js[0]["expected_through"] == "2026-08-31"
    assert js[0]["per_dim"] == [
        {"dims": {"banca_id": "MPS"}, "covered_through": "2026-06-30"}
    ]
    assert js[0]["basis"] == "canonical"
    assert js[0]["grace_day"] == 10
    assert js[0]["cadence"] == "monthly"


def test_render_show_all_mostra_le_dims_anche_se_una_sola():
    sella = _sd(
        "SELLA_BANCA_INTUR_APPEND",
        societa="INTUR",
        freshness={
            "tier": "E",
            "cadence": "monthly",
            "grain": "daily",
            "coverage_column": "data_operazione",
            "dims": ["banca_id"],
            "dim_filter": {"banca_id": ["SELLA"]},
        },
    )
    q = FakeQuery(
        coverage={
            "f_banche_movimenti": [
                {
                    "societa_id": "INTUR",
                    "banca_id": "SELLA",
                    "covered": date(2026, 8, 21),
                },
            ]
        }
    )
    [it] = compute(_registry(sella), q, now=NOW)
    assert "SELLA 21/08" not in render_text([it], today=NOW.date())
    assert "SELLA 21/08" in render_text([it], today=NOW.date(), show_all=True)


def test_render_show_all_mostra_le_raw_only():
    raw_only = _sd(
        "HOTELCUBE_STAMPACASSA_ORTI_APPEND",
        promotion_policy="RAW_ONLY",
        loop_targets=[],
        canonical_table="f_stampa_cassa",
        freshness={
            "tier": "M",
            "cadence": "adhoc",
            "grain": "snapshot",
            "basis": "raw",
        },
        acquisition={
            "mode": "MANUAL",
            "owner": "Stefano",
            "location": "HotelCube",
            "report": "Stampa Cassa",
        },
    )
    q = FakeQuery(
        raw=[
            {
                "source_name": "HOTELCUBE_STAMPACASSA_ORTI_APPEND",
                "last_intake": date(2026, 7, 12),
            }
        ]
    )
    [it] = compute(_registry(raw_only), q, now=NOW)
    assert "STAMPACASSA" not in render_text([it], today=NOW.date())
    assert "STAMPACASSA" in render_text([it], today=NOW.date(), show_all=True)


def test_render_adhoc_usa_il_punto():
    vigna = _sd(
        "PEC_MAILBOX_VIGNA_APPEND",
        system="PEC",
        societa="VIGNA",
        canonical_table="f_pec_messages",
        detector_category="pec_mbox",
        casella="vineyardamalficoast@pec.it",
        entity_id="VIGNA",
        freshness={"tier": "R", "cadence": "adhoc", "grain": "daily", "basis": "raw"},
        acquisition={
            "mode": "AUTO",
            "owner": "job",
            "job": "pec_fetch",
            "location": "PEC Aruba",
            "report": "IMAP",
        },
    )
    q = FakeQuery(
        raw=[
            {"source_name": "PEC_MAILBOX_VIGNA_APPEND", "last_intake": date(2026, 8, 3)}
        ],
        jobs=[{"pipeline_name": "pec_fetch", "last_ok": NOW - timedelta(hours=8)}],
    )
    [it] = compute(_registry(vigna), q, now=NOW)
    assert it.status == "OK"
    txt = render_text([it], today=NOW.date())
    assert "  ·  PEC_MAILBOX_VIGNA_APPEND" in txt
    assert "✓" not in txt


def test_dim_senza_data_rende_la_source_stale():
    mps = _sd("MPS_BANCA_ORTI_APPEND")
    q = FakeQuery(
        coverage={
            "f_banche_movimenti": [
                {"societa_id": "ORTI", "banca_id": "MPS", "covered": date(2026, 8, 31)},
                {"societa_id": "ORTI", "banca_id": "MPS_KROSS", "covered": None},
            ]
        }
    )
    [it] = compute(_registry(mps), q, now=NOW)
    assert it.covered_through is None
    assert it.status == "STALE"
    assert it.per_dim == [
        ({"banca_id": "MPS"}, date(2026, 8, 31)),
        ({"banca_id": "MPS_KROSS"}, None),
    ]


def test_render_auto_stampa_le_ore_del_job_rispetto_a_now():
    cop = _sd(
        "ORTI_COPERTI_ORTI_APPEND",
        canonical_table="f_coperti_giornalieri",
        freshness={
            "tier": "R",
            "cadence": "daily",
            "grain": "daily",
            "coverage_column": "data_servizio",
        },
        acquisition={
            "mode": "AUTO",
            "owner": "job",
            "job": "ingest_coperti",
            "location": "Google Sheet Scarico Coperti",
            "report": "form",
        },
    )
    q = FakeQuery(
        coverage={
            "f_coperti_giornalieri": [
                {"societa_id": "ORTI", "covered": date(2026, 9, 8)}
            ]
        },
        jobs=[{"pipeline_name": "ingest_coperti", "last_ok": NOW - timedelta(hours=5)}],
    )
    [it] = compute(_registry(cop), q, now=NOW)
    assert it.job_age_hours == 5
    txt = render_text([it], today=NOW.date())
    assert "job ingest_coperti OK 5h fa" in txt
    js = to_json([it])
    assert js[0]["job_age_hours"] == 5


def test_societa_non_filtrabile_su_canonical_usa_solo_dim_filter():
    vigna = _sd(
        "PEC_MAILBOX_VIGNA_APPEND",
        system="PEC",
        societa="VIGNA",
        canonical_table="f_pec_messages",
        detector_category="pec_mbox",
        casella="vineyardamalficoast@pec.it",
        entity_id="VIGNA",
        freshness={
            "tier": "R",
            "cadence": "daily",
            "grain": "daily",
            "coverage_column": "data_evento",
            "dims": ["entity_id"],
            "dim_filter": {"entity_id": ["VIGNA"]},
        },
        acquisition={
            "mode": "AUTO",
            "owner": "job",
            "job": "pec_fetch",
            "location": "PEC Aruba",
            "report": "IMAP",
        },
    )
    q = FakeQuery(
        coverage={
            "f_pec_messages": [
                {"societa_id": None, "entity_id": "VIGNA", "covered": date(2026, 9, 8)},
                {
                    "societa_id": "INTUR",
                    "entity_id": "INTUR",
                    "covered": date(2026, 9, 9),
                },
            ]
        },
        jobs=[{"pipeline_name": "pec_fetch", "last_ok": NOW - timedelta(hours=2)}],
    )
    [it] = compute(_registry(vigna), q, now=NOW)
    assert it.per_dim == [({"entity_id": "VIGNA"}, date(2026, 9, 8))]
    assert it.status == "OK"
