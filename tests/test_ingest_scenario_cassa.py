import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from core.config import P_PROGETTI_PAGAMENTI, P_SCENARI, P_SCENARIO_FLUSSI
from core.lineage.source_resolver import load_registry
from ingest.flussi import ingest_scenario_cassa as mod
from ingest.flussi.ingest_scenario_cassa import ingest
from tests.test_cassa_scenario import _con_livelli, scenario_sintetico
from verticals.condges.cassa_scenario import scenario_to_json


class ClientFinto:
    def __init__(self, colonne):
        self.colonne = colonne
        self.tabelle = []

    def get_table(self, ref):
        self.tabelle.append(ref)
        return SimpleNamespace(schema=[SimpleNamespace(name=c) for c in self.colonne])


COLONNE_PAGAMENTI = ["scenario_id", "progetto_id", "pagamento", "fornitore_id"]


@pytest.fixture(autouse=True)
def schema_con_livelli(monkeypatch):
    client = ClientFinto([*COLONNE_PAGAMENTI, "macro", "area"])
    monkeypatch.setattr(mod, "get_client", lambda: client)
    return client


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


def file_scenario_v2(tmp_path):
    sc, base = scenario_sintetico()
    p = tmp_path / "scenario_v2.json"
    p.write_text(scenario_to_json(_con_livelli(sc), base, nome="t"), encoding="utf-8")
    assert json.loads(p.read_text())["schema"] == "cdg-cassa-scenario/2"
    return p


def test_v2_senza_colonne_livelli_si_ferma_senza_scrivere(monkeypatch, tmp_path):
    chiamate = []
    monkeypatch.setattr(mod, "bq_write_validated", lambda *a, **k: chiamate.append(a))
    client = ClientFinto(COLONNE_PAGAMENTI)
    monkeypatch.setattr(mod, "get_client", lambda: client)
    with pytest.raises(RuntimeError, match="create_previsioni_tables"):
        ingest(file_scenario_v2(tmp_path), "rid", dry_run=False, autore="t")
    assert chiamate == []
    assert client.tabelle == [P_PROGETTI_PAGAMENTI]


def test_v2_con_colonne_livelli_scrive_tre_tabelle_con_macro_area(
    monkeypatch, tmp_path, schema_con_livelli
):
    chiamate = []
    monkeypatch.setattr(
        mod, "bq_write_validated", lambda t, rows, **k: chiamate.append((t, rows))
    )
    ingest(file_scenario_v2(tmp_path), "rid", dry_run=False, autore="t")
    assert [t for t, _ in chiamate] == [
        P_SCENARI,
        P_SCENARIO_FLUSSI,
        P_PROGETTI_PAGAMENTI,
    ]
    pagamenti = chiamate[2][1]
    assert any(r.macro == "Tessili" and r.area == "Fornitura e posa" for r in pagamenti)
    assert any(
        r.stato == "da_assegnare" and r.macro == "Tessili" and r.area is None
        for r in pagamenti
    )
    assert schema_con_livelli.tabelle == [P_PROGETTI_PAGAMENTI]


def test_dry_run_non_legge_lo_schema(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "get_client", lambda: pytest.fail("BQ in dry-run"))
    ingest(file_scenario_v2(tmp_path), "rid", dry_run=True, autore="t")


def test_ddl_porta_macro_area_e_alter_idempotente():
    from core.bq.load import create_previsioni_tables as ddl

    assert "macro               STRING" in ddl.DDL_PAGAMENTI
    assert "area                STRING" in ddl.DDL_PAGAMENTI
    alter = ddl.STATEMENTS[-1]
    assert alter.startswith(f"ALTER TABLE `{P_PROGETTI_PAGAMENTI}`")
    assert "ADD COLUMN IF NOT EXISTS macro STRING" in alter
    assert "ADD COLUMN IF NOT EXISTS area STRING" in alter
