"""Vault Loop incremental reconciliation — validation matrix (Part 10 of the brief).

Simulated repos in tmp_path; the real-vault run is a separate, manual verification.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from scripts.vault_loop import reconcile as vl

TODAY = date(2026, 10, 11)


def git(path: Path, *args: str) -> str:
    cmd = [
        "git",
        "-C",
        str(path),
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        *args,
    ]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")


def commit_all(path: Path, msg: str) -> str:
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", msg)
    return git(path, "rev-parse", "HEAD").strip()


INVARIANTS = "# Invariants\n\n" + "\n\n".join(
    f"### I{i}. Rule {i}\n\nbody" for i in range(1, 11)
)


@pytest.fixture()
def world(tmp_path):
    """hotelops + mgmt-os + vault, all clean and mutually consistent."""
    hotelops = tmp_path / "hotelops"
    init_repo(hotelops)
    (hotelops / "docs" / "architecture").mkdir(parents=True)
    (hotelops / "docs" / "architecture" / "INVARIANTS.md").write_text(INVARIANTS)
    (hotelops / "docs" / "procedures").mkdir()
    (hotelops / "core").mkdir()
    (hotelops / "core" / "config.py").write_text("X = 1\n")
    (hotelops / "meta" / "vault-loop").mkdir(parents=True)
    commit_all(hotelops, "Merge pull request #1 from x/init")

    mgmt = tmp_path / "mgmt_os"
    init_repo(mgmt)
    (mgmt / "docs").mkdir()
    (mgmt / "docs" / "README.md").write_text("regia\n")
    commit_all(mgmt, "Merge pull request #1 from y/init")

    vault_root = tmp_path / "Vault"
    v = vault_root / "HotelOps"
    for d in ("decisions", "_archive", "sessions", "concepts"):
        (v / d).mkdir(parents=True)
    (v / "INDEX.md").write_text(
        "# Index\n\nInvariants I1–I10 live in `docs/architecture/INVARIANTS.md`.\n[[concepts/ALPHA]]\n"
    )
    (v / "concepts" / "ALPHA.md").write_text("alpha, see `core/config.py`\n")
    (v / "decisions" / "2026-01-10_Old_Decision.md").write_text("old\n")
    (v / "decisions" / "2026-10-09_Fresh_Decision.md").write_text("fresh\n")
    (v / "_archive" / "DEAD_PROTOCOL.md").write_text("archived\n")
    (v / "sessions" / "2026-01-01_x.md").write_text(
        "[[NOWHERE]] `docs/gone.md` I1–I8 (history, skipped)\n"
    )
    (v / "log.md").write_text(
        "## [2026-10-09] update | INVARIANTS.md synced; hotelops PR #1 init; mgmt_os PR #1 init\n"
    )
    init_repo(vault_root)
    commit_all(vault_root, "vault init")

    cfg = hotelops / "meta" / "vault-loop" / "sources.yaml"
    cfg.write_text(
        f"""
first_run_window_days: 3650
decision_age_days: 30
sources:
  hotelops:
    path: .
    authority: repo docs
    watch_paths: [docs/architecture/, core/config.py]
  mgmt-os:
    path: {mgmt}
    authority: management engine
    watch_paths: [docs/]
  vault:
    path: {vault_root}
    subdir: HotelOps
    authority: reasoning memory
    skip_dirs: [sessions, _archive]
    archive_dirs: [_archive]
    note_dirs: [decisions, concepts]
    note_files: [log.md, INDEX.md]
"""
    )
    commit_all(hotelops, "chore: vault-loop config")
    state = tmp_path / "state"
    return {
        "hotelops": hotelops,
        "mgmt": mgmt,
        "vault_root": vault_root,
        "vault": v,
        "cfg": cfg,
        "state": state,
    }


def run(w, **kw):
    return vl.run_reconcile(w["cfg"], w["state"], today=TODAY, **kw)


def open_findings(r, check=None):
    return [
        f
        for f in r["findings"].values()
        if f["state"] == "open" and (check is None or f["check"].startswith(check))
    ]


def tree_hash(root: Path) -> str:
    h = hashlib.sha1()
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".git" not in p.parts:
            h.update(p.relative_to(root).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


# 1. a correct document produces no false discrepancy
def test_consistent_world_is_current(world):
    r = run(world)
    assert r["overall"] == vl.CURRENT, r["report"]
    assert open_findings(r) == []
    assert all(s["checkpoint_advanced"] for s in r["sources"])


# 2. an obsolete architectural claim produces a traceable finding
def test_obsolete_invariant_count_is_traced(world):
    (world["vault"] / "INDEX.md").write_text("Costituzione tecnica (I1–I8).\n")
    commit_all(world["vault_root"], "stale claim")
    r = run(world)
    f = open_findings(r, "invariant-range-claims")
    assert len(f) == 1
    assert f[0]["path"] == "INDEX.md" and "I1–I10" in f[0]["claim"]
    assert f[0]["authority"].startswith("repo docs/architecture/INVARIANTS.md")
    assert r["overall"] == vl.DRIFT_DETECTED
    # the historical session note with the same claim is NOT reported
    assert all(x["path"] != "sessions/2026-01-01_x.md" for x in open_findings(r))


# 3. a code change without a required documentation update is detected
def test_architecture_change_without_vault_note_requires_review(world):
    run(world)  # checkpoint at HEAD
    (world["hotelops"] / "docs" / "architecture" / "NEW_RULES.md").write_text("new\n")
    commit_all(world["hotelops"], "Merge pull request #77 from x/new-rules")
    r = run(world)
    f = open_findings(r, "arch-changes-unreflected")
    assert len(f) == 1 and f[0]["source"] == "hotelops" and "PR#77" in f[0]["claim"]
    assert f[0]["status"] == vl.REVIEW_REQUIRED and f[0]["approval"] is True
    # once the vault cites the PR, the finding resolves
    with (world["vault"] / "log.md").open("a") as fh:
        fh.write("## [2026-10-11] update | hotelops PR #77 new rules captured\n")
    commit_all(world["vault_root"], "note")
    r2 = run(world)
    assert open_findings(r2, "arch-changes-unreflected") == []
    assert r2["findings"][f[0]["id"]]["state"] == "resolved"


# 4. an archived decision is not silently rewritten (and the tool itself never writes)
def test_archived_edit_is_flagged_and_tool_never_writes(world):
    before = tree_hash(world["vault_root"])
    run(world)
    assert tree_hash(world["vault_root"]) == before
    (world["vault"] / "_archive" / "DEAD_PROTOCOL.md").write_text("rewritten history\n")
    (world["vault"] / "decisions" / "2026-01-10_Old_Decision.md").write_text(
        "old, amended\n"
    )
    (world["vault"] / "decisions" / "2026-10-09_Fresh_Decision.md").write_text(
        "fresh, edited\n"
    )
    commit_all(world["vault_root"], "edits")
    r = run(world)
    paths = sorted(f["path"] for f in open_findings(r, "archived-content-modified"))
    assert paths == [
        "_archive/DEAD_PROTOCOL.md",
        "decisions/2026-01-10_Old_Decision.md",
    ]
    assert all(
        f["status"] == vl.REVIEW_REQUIRED and f["severity"] == "HIGH"
        for f in open_findings(r, "archived-content-modified")
    )
    assert (
        world["vault"] / "_archive" / "DEAD_PROTOCOL.md"
    ).read_text() == "rewritten history\n"


# 5. unavailable sources cause an incomplete status, not false success
def test_unavailable_source_is_not_success(world, monkeypatch):
    monkeypatch.setenv("VAULT_LOOP_PATH_MGMT_OS", str(world["mgmt"].parent / "missing"))
    r = run(world)
    assert r["overall"] == vl.SOURCE_UNAVAILABLE
    rows = {s["name"]: s for s in r["sources"]}
    assert (
        rows["mgmt-os"]["status"] == vl.SOURCE_UNAVAILABLE
        and not rows["mgmt-os"]["checkpoint_advanced"]
    )
    assert (
        rows["hotelops"]["checkpoint_advanced"] and rows["vault"]["checkpoint_advanced"]
    )
    cp = json.loads((world["state"] / "checkpoint.json").read_text())
    assert "mgmt-os" not in cp["sources"] and set(cp["sources"]) == {
        "hotelops",
        "vault",
    }


# 6. repeated runs are idempotent
def test_repeated_runs_are_idempotent(world):
    (world["vault"] / "INDEX.md").write_text("I1–I8 and [[GHOST]]\n")
    commit_all(world["vault_root"], "drift")
    r1 = run(world)
    cp1 = json.loads((world["state"] / "checkpoint.json").read_text())
    r2 = run(world)
    cp2 = json.loads((world["state"] / "checkpoint.json").read_text())
    ids1 = {k: v["state"] for k, v in r1["findings"].items()}
    ids2 = {k: v["state"] for k, v in r2["findings"].items()}
    assert ids1 == ids2 and len(ids1) == 2
    assert {k: v["sha"] for k, v in cp1["sources"].items()} == {
        k: v["sha"] for k, v in cp2["sources"].items()
    }
    assert cp1["vault_hashes"] == cp2["vault_hashes"]
    assert all(
        v["first_seen"] == r1["findings"][k]["first_seen"]
        for k, v in r2["findings"].items()
    )


# 7. checkpoints stay consistent after a failure; findings are not auto-resolved
def test_failed_check_holds_checkpoint_and_keeps_findings(world, monkeypatch):
    (world["vault"] / "INDEX.md").write_text("I1–I8\n")
    commit_all(world["vault_root"], "drift")
    r1 = run(world)
    fid = open_findings(r1, "invariant-range-claims")[0]["id"]
    vault_sha_before = json.loads((world["state"] / "checkpoint.json").read_text())[
        "sources"
    ]["vault"]["sha"]

    def boom(*_a, **_k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(vl, "check_invariant_range_claims", boom)
    (world["vault"] / "INDEX.md").write_text("I1–I10\n")  # drift fixed in reality
    commit_all(world["vault_root"], "fix")
    r2 = run(world)
    checks = {c["id"]: c for c in r2["checks"]}
    assert checks["invariant-range-claims"]["status"] == vl.NOT_VERIFIED
    rows = {s["name"]: s for s in r2["sources"]}
    assert (
        not rows["vault"]["checkpoint_advanced"]
        and "check failed" in rows["vault"]["note"]
    )
    cp = json.loads((world["state"] / "checkpoint.json").read_text())
    assert cp["sources"]["vault"]["sha"] == vault_sha_before  # held, not advanced
    assert r2["findings"][fid]["state"] == "open"  # not resolved: the check did not run
    assert r2["overall"] == vl.NOT_VERIFIED


# 7b. a dirty working tree is checked but never checkpointed
def test_dirty_source_holds_checkpoint(world):
    run(world)
    (world["vault"] / "INDEX.md").write_text("uncommitted I1–I8\n")  # not committed
    r = run(world)
    rows = {s["name"]: s for s in r["sources"]}
    assert rows["vault"]["dirty"] and not rows["vault"]["checkpoint_advanced"]
    assert open_findings(r, "invariant-range-claims")  # content still checked


# 8. multiple repositories keep their own authority
def test_multi_repo_authority_is_preserved(world):
    run(world)
    (world["mgmt"] / "docs" / "DIRECTION.md").write_text("new direction\n")
    commit_all(world["mgmt"], "Merge pull request #9 from y/direction")
    r = run(world)
    f = open_findings(r, "arch-changes-unreflected")
    assert [x["source"] for x in f] == ["mgmt-os"]
    assert f[0]["authority"] == "management engine" and f[0]["path"].startswith(
        "mgmt-os@"
    )


# 9. pointer and wikilink mechanics (dead path, archived-as-active, broken link)
def test_pointer_and_link_checks(world):
    (world["vault"] / "INDEX.md").write_text(
        "see `repo/core/config.py` ok, `core/removed.py` dead, [[DEAD_PROTOCOL]] archived, [[NOWHERE]] broken, [[ALPHA|alias]] fine\n"
    )
    commit_all(world["vault_root"], "links")
    r = run(world)
    by_check = {}
    for f in open_findings(r):
        by_check.setdefault(f["check"], []).append(f["claim"])
    assert by_check["vault-repo-pointers"] == [
        "cites `core/removed.py` which does not exist in any tracked repo"
    ]
    assert by_check["archived-as-active"] == [
        "[[DEAD_PROTOCOL]] points only to an archived note"
    ]
    assert by_check["broken-wikilinks"] == ["[[NOWHERE]] has no target note"]


# 9b. a dot in a link target is part of a note name unless it is an attachment type
def test_dotted_link_targets(world):
    v = world["vault"]
    (v / "concepts" / "SPEC_V1.2.md").write_text("a note whose name carries a dot\n")
    (v / "INDEX.md").write_text(
        "[[concepts/SPEC_V1.2]] resolves, [[concepts/SPEC_V9.9]] does not, "
        "[[diagram.canvas]] and [[chart.png]] are attachments\n"
    )
    commit_all(world["vault_root"], "dotted targets")
    claims = [
        f["claim"] for f in open_findings(run(world), "broken-wikilinks")
    ]
    # the existing dotted note is found, the missing one is reported, attachments stay out
    assert claims == ["[[concepts/SPEC_V9.9]] has no target note"]


# 10. no credentials or sensitive strings leak into the report
def test_report_is_scrubbed():
    f = vl.Finding(
        "c",
        "vault",
        "a",
        "x.md",
        "token ghp_abcdefghijklmnopqrstuvwxyz0123 and mail rosa@example.com",
        "fix",
        vl.DRIFT_DETECTED,
    )
    run_ = {
        "run_at": "2026-10-11T00:00:00+00:00",
        "overall": vl.DRIFT_DETECTED,
        "sources": [],
        "checks": [],
        "findings": {
            f.id: {
                **vl.asdict(f),
                "id": f.id,
                "first_seen": "2026-10-11",
                "last_seen": "2026-10-11",
                "resolved_at": None,
                "state": "open",
            }
        },
    }
    report = vl.render_report(run_)
    assert "ghp_" not in report and "@example.com" not in report
    assert report.count("[REDACTED]") == 2 and "redacted" in report
