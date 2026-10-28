# tests/test_registry_freshness_contracts.py
"""Il registry reale rispetta il freshness contract (spec 2026-09-09 §3, §9)."""

from collections import defaultdict
from datetime import UTC, date, datetime

import pytest

from core import freshness
from core.lineage.source_resolver import load_registry


def _reg():
    return load_registry()


def test_ogni_sorgente_promuovibile_ha_il_contratto():
    mancanti = [
        sd.source_name
        for sd in _reg().sources.values()
        if sd.promotion_policy != "RAW_ONLY"
        and (sd.freshness is None or sd.acquisition is None)
    ]
    assert mancanti == [], f"senza freshness/acquisition: {mancanti}"


def test_le_raw_only_hanno_contratto_su_base_raw():
    for sd in _reg().sources.values():
        if sd.promotion_policy == "RAW_ONLY":
            assert sd.freshness is not None and sd.freshness.basis == "raw", (
                sd.source_name
            )
            assert sd.acquisition is not None and sd.acquisition.mode == "MANUAL", (
                sd.source_name
            )


def test_esolver_ha_grazia_20_partite_1_tutti_gli_altri_mensili_10():
    """ESOLVER 20; le PARTITE 1 (rito del giorno 1, Stefano 2026-10-26: al 1° di M+1 serve la
    foto al 30 di M — docs/procedures/cashflow_mensile.md); ogni altra mensile 10."""
    for sd in _reg().sources.values():
        if sd.freshness is None or sd.freshness.cadence != "monthly":
            continue
        atteso = (
            (1 if sd.dataset == "PARTITE" else 20) if sd.system == "ESOLVER" else 10
        )
        assert sd.freshness.grace_day == atteso, sd.source_name


def test_auto_solo_dove_esiste_un_job():
    attesi = {
        "ORTI_COPERTI_ORTI_APPEND": "ingest_coperti",
        "RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT": "drive_fetch:RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT",
        "PEC_MAILBOX_INTUR_APPEND": "pec_fetch",
        "PEC_MAILBOX_ORTI_APPEND": "pec_fetch",
        "PEC_MAILBOX_VIGNA_APPEND": "pec_fetch",
        "DRIVE_INVENTORY_GROUP_SNAPSHOT": "drive_inventory",
    }
    auto = {
        sd.source_name: sd.acquisition.job
        for sd in _reg().sources.values()
        if sd.acquisition and sd.acquisition.mode == "AUTO"
    }
    assert auto == attesi


def test_sorgenti_che_condividono_tabella_e_societa_si_distinguono_con_dim_filter():
    gruppi = defaultdict(list)
    for sd in _reg().sources.values():
        fc = sd.freshness
        if fc is None or fc.basis != "canonical":
            continue
        societa = sd.societa if sd.societa in ("ORTI", "INTUR") else "*"
        gruppi[(sd.canonical_table, societa)].append(sd)
    for key, sds in gruppi.items():
        if len(sds) > 1:
            for sd in sds:
                assert sd.freshness.dim_filter, (
                    f"{sd.source_name} condivide {key} senza dim_filter"
                )


def test_dormienti_dichiarate():
    reg = _reg()
    for name in ("INTESA_BANCA_ORTI_APPEND", "INTESA_BANCA_INTUR_APPEND"):
        assert reg.get(name).freshness.dormant, name


def test_dims_banca_id_hanno_sempre_dim_filter():
    """I conti dormienti (es. INTESA) non devono pinnare la copertura di una
    sorgente che li condivide con conti vivi (ruling controller 2026-09-10)."""
    for sd in _reg().sources.values():
        fc = sd.freshness
        if fc is None or "banca_id" not in fc.dims:
            continue
        assert fc.dim_filter.get("banca_id"), (
            f"{sd.source_name}: dims include banca_id senza dim_filter"
        )


@pytest.mark.parametrize("last_intake", [None, date(2026, 10, 20)])
def test_inventory_raw_freshness_does_not_query_its_canonical_table(last_intake):
    """Actual registry + query builder; no inventory table or societa_id required."""
    inventory = "DRIVE_INVENTORY_GROUP_SNAPSHOT"
    now = datetime(2026, 10, 20, 10, tzinfo=UTC)
    covered = date(2026, 10, 18)
    calls = []

    def query(sql):
        calls.append(sql)
        if "hotelops.f_drive_inventory" in sql:
            raise RuntimeError("inventory table/societa_id unavailable: " + sql)
        if sql == freshness.RAW_SQL:
            return (
                [{"source_name": inventory, "last_intake": last_intake}]
                if last_intake
                else []
            )
        if sql == freshness.JOBS_SQL:
            return [
                {"pipeline_name": "ingest_coperti", "last_ok": now},
                {
                    "pipeline_name": "drive_fetch:RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT",
                    "last_ok": now,
                },
            ]
        if "FROM hotelops.f_spiaggia_corrispettivi " in sql:
            return [{"societa_id": "INTUR", "covered": covered}]
        if "FROM hotelops.f_coperti_giornalieri " in sql:
            return [{"societa_id": "ORTI", "covered": covered}]
        return []

    items = {i.source_name: i for i in freshness.compute(_reg(), query, now=now)}
    item = items[inventory]
    assert item.basis == "raw" and item.covered_through == last_intake
    assert item.last_raw_at == last_intake and item.per_dim == []
    assert item.status == ("NO_RECEIPT" if last_intake else "JOB_DOWN")
    assert not any("hotelops.f_drive_inventory" in sql for sql in calls)
    assert (
        "SELECT societa_id, MAX(data) AS covered FROM hotelops.f_spiaggia_corrispettivi GROUP BY 1"
        in calls
    )
    assert (
        "SELECT societa_id, MAX(data_servizio) AS covered FROM hotelops.f_coperti_giornalieri GROUP BY 1"
        in calls
    )
    for name in ("RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT", "ORTI_COPERTI_ORTI_APPEND"):
        assert items[name].basis == "canonical"
        assert items[name].covered_through == covered
        assert items[name].status == "OK"
