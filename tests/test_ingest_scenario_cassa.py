import subprocess
import sys

import pytest

from core.config import P_PROGETTI_PAGAMENTI, P_SCENARI, P_SCENARIO_FLUSSI
from core.lineage.source_resolver import load_registry
from ingest.flussi import ingest_scenario_cassa as mod
from ingest.flussi.ingest_scenario_cassa import ingest
from tests.test_cassa_scenario import scenario_sintetico
from verticals.condges.cassa_scenario import scenario_to_json


def file_scenario(tmp_path):
    sc, base = scenario_sintetico()
    p = tmp_path / "scenario.json"
    p.write_text(scenario_to_json(sc, base, nome="t"), encoding="utf-8")
    return p


def test_dry_run_non_scrive(monkeypatch, tmp_path):
    chiamate = []
    monkeypatch.setattr(mod, "bq_write_validated", lambda *a, **k: chiamate.append(a))
    out = ingest(file_scenario(tmp_path), "rid", dry_run=True, autore="t")
    assert chiamate == [] and out["righe"]["p_scenari"] == 1


def test_scrive_tre_tabelle_in_append_con_fk(monkeypatch, tmp_path):
    chiamate = []
    monkeypatch.setattr(
        mod,
        "bq_write_validated",
        lambda t, rows, mode="append", **k: chiamate.append((t, mode, rows)),
    )
    ingest(file_scenario(tmp_path), "rid", dry_run=False, autore="t")
    assert [c[0] for c in chiamate] == [
        P_SCENARI,
        P_SCENARIO_FLUSSI,
        P_PROGETTI_PAGAMENTI,
    ]
    assert all(c[1] == "append" for c in chiamate)
    assert all(r.raw_object_id == "rid" for _, _, rows in chiamate for r in rows)


def test_societa_diversa_da_group_rifiutata(tmp_path):
    rc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ingest.flussi.ingest_scenario_cassa",
            "--file",
            str(file_scenario(tmp_path)),
            "--societa",
            "ORTI",
            "--raw-object-id",
            "r",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 2 and "GROUP" in rc.stderr


def test_source_nel_registry():
    d = load_registry().sources["CDG_SCENARIOCASSA_GROUP_APPEND"]
    assert d.canonical_table == "hotelops_previsioni.p_scenari"
    assert d.loop_targets == ["cdg_cassa"]


def test_validazione_prima_di_scrivere(monkeypatch, tmp_path):
    chiamate = []
    monkeypatch.setattr(mod, "bq_write_validated", lambda *a, **k: chiamate.append(a))
    vera = mod.righe_p

    def righe_rotte(*a, **k):
        scenari, flussi, pagamenti = vera(*a, **k)
        pagamenti[-1] = {**pagamenti[-1], "aliquota_iva": 4}
        return scenari, flussi, pagamenti

    monkeypatch.setattr(mod, "righe_p", righe_rotte)
    with pytest.raises(ValueError):
        ingest(file_scenario(tmp_path), "rid", dry_run=False, autore="t")
    assert chiamate == []
