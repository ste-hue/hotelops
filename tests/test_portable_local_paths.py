from pathlib import Path

from core.local_paths import (
    resolve_artifacts_root,
    resolve_datahub_root,
    resolve_drive_sa_key_path,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_local_path_resolvers_honor_env(monkeypatch):
    monkeypatch.setenv("HOTELOPS_DATAHUB_ROOT", "/tmp/custom-datahub")
    monkeypatch.setenv("HOTELOPS_ARTIFACTS_ROOT", "/tmp/custom-artifacts")
    monkeypatch.setenv("HOTELOPS_DRIVE_SA_KEY", "/tmp/custom-drive-key.json")

    assert resolve_datahub_root() == Path("/tmp/custom-datahub")
    assert resolve_artifacts_root() == Path("/tmp/custom-artifacts")
    assert resolve_drive_sa_key_path() == Path("/tmp/custom-drive-key.json")


def test_portability_pass_removed_user_specific_paths():
    changed_files = [
        ".devcontainer/devcontainer.json",
        "core/datahub_sync.py",
        "core/bq/load/load_budget_costi.py",
        "core/bq/load/load_categorie.py",
        "core/bq/load/load_piano_conti.py",
        "core/bq/SCHEMA_CONTEXT.md",
        "ingest/drive_fetch.py",
        "ingest/flussi/ingest_gasparotto.py",
        "verticals/hub/README.md",
        "workspace/projects/HPAN25PIANO1/update_v5_amounts.py",
    ]

    for relative_path in changed_files:
        content = (REPO_ROOT / relative_path).read_text()
        assert "/Users/stefanodellapietra" not in content, relative_path


def test_devcontainer_points_to_live_app():
    content = (REPO_ROOT / ".devcontainer" / "devcontainer.json").read_text()
    assert "verticals/hub/app.py" in content
    assert "app_scadenzario.py" not in content
