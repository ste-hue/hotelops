"""Vault Loop — incremental, deterministic reconciliation (Mode C subset).

Read-only on every source. State (checkpoint, findings, last report) lives in a
separate directory that is never inside a source. Semantic judgment is left to the
agent-run Mode C: this tool only emits DRIFT DETECTED for mechanical contradictions
and REVIEW REQUIRED where a human or agent must decide.

    python -m scripts.vault_loop.reconcile --config meta/vault-loop/sources.yaml \
        --state .hotelops_state/vault_loop --out report.md
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import yaml

# ── Status vocabulary (worst last) ────────────────────────────────────────

CURRENT = "CURRENT"
REVIEW_REQUIRED = "REVIEW REQUIRED"
DRIFT_DETECTED = "DRIFT DETECTED"
NOT_VERIFIED = "NOT VERIFIED"
SOURCE_UNAVAILABLE = "SOURCE UNAVAILABLE"
_ORDER = [CURRENT, REVIEW_REQUIRED, DRIFT_DETECTED, NOT_VERIFIED, SOURCE_UNAVAILABLE]


def worst(statuses) -> str:
    statuses = list(statuses)
    if not statuses:
        return CURRENT
    return max(statuses, key=_ORDER.index)


# ── Data ──────────────────────────────────────────────────────────────────


@dataclass
class Source:
    name: str
    path: Path
    authority: str
    available: bool = False
    sha: str | None = None
    dirty: bool = False
    error: str = ""
    subdir: str = ""
    watch_paths: list[str] = field(default_factory=list)
    skip_dirs: list[str] = field(default_factory=list)
    archive_dirs: list[str] = field(default_factory=list)
    note_dirs: list[str] = field(default_factory=list)
    note_files: list[str] = field(default_factory=list)

    @property
    def root(self) -> Path:
        return self.path / self.subdir if self.subdir else self.path

    @property
    def status(self) -> str:
        return SOURCE_UNAVAILABLE if not self.available else CURRENT


@dataclass
class Finding:
    check: str
    source: str
    authority: str
    path: str
    claim: str
    correction: str
    status: str  # DRIFT DETECTED | REVIEW REQUIRED
    severity: str = "MED"
    approval: bool = False

    @property
    def id(self) -> str:
        raw = f"{self.check}|{self.source}|{self.path}|{self.claim}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


@dataclass
class CheckResult:
    id: str
    status: str
    sources: list[str]
    findings: list[Finding] = field(default_factory=list)
    note: str = ""
    completed: bool = True


# ── Helpers ───────────────────────────────────────────────────────────────


def _git(path: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(path), *args], check=False, capture_output=True, text=True
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"git {' '.join(args)} failed")
    return out.stdout


def _sha1_file(p: Path) -> str:
    return hashlib.sha1(p.read_bytes()).hexdigest()


def load_config(config_path: Path) -> tuple[dict, dict[str, Source]]:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    base = (
        config_path.resolve().parent.parent.parent
    )  # meta/vault-loop/sources.yaml -> repo root
    sources: dict[str, Source] = {}
    for name, spec in (cfg.get("sources") or {}).items():
        env = "VAULT_LOOP_PATH_" + name.upper().replace("-", "_")
        raw = os.environ.get(env) or spec.get("path", ".")
        path = Path(raw) if os.path.isabs(raw) else (base / raw)
        if not path.exists() and not os.path.isabs(raw):
            # running from a git worktree: siblings live next to the main checkout
            try:
                main_root = Path(
                    _git(
                        base, "rev-parse", "--path-format=absolute", "--git-common-dir"
                    )
                ).parent
                if (main_root / raw).exists():
                    path = main_root / raw
            except RuntimeError:
                pass
        sources[name] = Source(
            name=name,
            path=path.resolve(),
            authority=spec.get("authority", ""),
            subdir=spec.get("subdir", ""),
            watch_paths=list(spec.get("watch_paths") or []),
            skip_dirs=list(spec.get("skip_dirs") or []),
            archive_dirs=list(spec.get("archive_dirs") or []),
            note_dirs=list(spec.get("note_dirs") or []),
            note_files=list(spec.get("note_files") or []),
        )
    return cfg, sources


def resolve(src: Source) -> Source:
    try:
        if not src.path.is_dir():
            raise RuntimeError("path does not exist")
        if not src.root.is_dir():
            raise RuntimeError("configured source subdirectory does not exist")
        top = Path(_git(src.path, "rev-parse", "--show-toplevel").strip()).resolve()
        if top != src.path.resolve():
            raise RuntimeError("source is not a repository root")
        src.sha = _git(src.path, "rev-parse", "HEAD").strip()
        src.dirty = bool(_git(src.path, "status", "--porcelain").strip())
        src.available = True
    except Exception as exc:  # noqa: BLE001 — any failure = unavailable, never a crash
        src.available = False
        src.error = str(exc)
    return src


def iter_notes(src: Source, *, include_skipped: bool = False):
    """Yield (relative path, text) for every .md under the source root."""
    root = src.root
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root)
        if not include_skipped and rel.parts and rel.parts[0] in src.skip_dirs:
            continue
        yield rel.as_posix(), p.read_text(encoding="utf-8")


def _is_archived(rel: str, src: Source) -> bool:
    return any(rel.startswith(d.rstrip("/") + "/") for d in src.archive_dirs)


# ── Checks ────────────────────────────────────────────────────────────────

_REPO_PATH_RE = re.compile(
    r"(?<![\w/.-])(?:repo/|~/dev/Projects/hotelops/)?"
    r"((?:docs|core|ingest|verticals|scripts|tests|meta|\.claude/commands)/"
    r"[\w./\-*]*\.(?:md|py|sql|yaml|yml|csv|sh|json))\b"
)


def _path_exists(root: Path, rel: str) -> bool:
    if "*" in rel:
        return any(root.glob(rel))
    return (root / rel).exists()


def check_vault_repo_pointers(vault: Source, repos: list[Source]) -> CheckResult:
    """Repo paths cited in vault notes must exist in one of the code repos."""
    res = CheckResult(
        "vault-repo-pointers", CURRENT, [vault.name] + [r.name for r in repos]
    )
    if any(not r.available for r in repos):
        return CheckResult(
            res.id,
            SOURCE_UNAVAILABLE,
            res.sources,
            note="pointer targets incomplete: a tracked repo is unavailable",
            completed=False,
        )
    roots = [r.path for r in repos if r.available]
    for rel, text in iter_notes(vault):
        seen: set[str] = set()
        for m in _REPO_PATH_RE.finditer(text):
            cited = m.group(1).rstrip(".")
            if cited in seen or any(
                _path_exists(root, cited) for root in roots + [vault.root]
            ):
                continue
            seen.add(cited)
            res.findings.append(
                Finding(
                    check=res.id,
                    source=vault.name,
                    authority="repo (file tree)",
                    path=rel,
                    claim=f"cites `{cited}` which does not exist in any tracked repo",
                    correction="update the pointer or mark the note historical",
                    status=DRIFT_DETECTED,
                    severity="LOW",
                )
            )
    res.status = DRIFT_DETECTED if res.findings else CURRENT
    return res


_INV_HEADING_RE = re.compile(r"^### I(\d+)\.", re.MULTILINE)
_INV_CLAIM_RE = re.compile(r"\bI1\s*[–\-—]\s*I(\d+)\b")


def check_invariant_range_claims(vault: Source, hotelops: Source) -> CheckResult:
    res = CheckResult("invariant-range-claims", CURRENT, [vault.name, hotelops.name])
    inv = hotelops.path / "docs" / "architecture" / "INVARIANTS.md"
    if not inv.exists():
        res.status, res.note = NOT_VERIFIED, "INVARIANTS.md not found in hotelops"
        res.completed = False
        return res
    numbers = [int(n) for n in _INV_HEADING_RE.findall(inv.read_text(encoding="utf-8"))]
    if not numbers:
        res.status, res.note = NOT_VERIFIED, "no `### In.` headings in INVARIANTS.md"
        res.completed = False
        return res
    top = max(numbers)
    for rel, text in iter_notes(vault):
        for claimed in sorted({int(x) for x in _INV_CLAIM_RE.findall(text)}):
            if claimed != top:
                res.findings.append(
                    Finding(
                        check=res.id,
                        source=vault.name,
                        authority="repo docs/architecture/INVARIANTS.md",
                        path=rel,
                        claim=f"says invariants are I1–I{claimed}; repo defines I1–I{top}",
                        correction=f"update to I1–I{top}",
                        status=DRIFT_DETECTED,
                        severity="MED",
                    )
                )
    res.status = DRIFT_DETECTED if res.findings else CURRENT
    return res


_WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]")


def check_wikilinks(vault: Source) -> tuple[CheckResult, CheckResult]:
    """Two results: links whose only target is archived, and links with no target."""
    archived = CheckResult("archived-as-active", CURRENT, [vault.name])
    broken = CheckResult("broken-wikilinks", CURRENT, [vault.name])
    # Obsidian resolves [[links]] vault-wide: index every note under the vault repo,
    # not only the HotelOps subdir; archived = under the subdir's archive dirs.
    index: dict[str, list[str]] = {}
    for p in sorted(vault.path.rglob("*.md")):
        rel = p.relative_to(vault.path).as_posix()
        if vault.subdir and rel.startswith(vault.subdir + "/"):
            rel = rel[len(vault.subdir) + 1 :]
        index.setdefault(p.stem.lower(), []).append(rel)
    for rel, text in iter_notes(vault):
        seen: set[str] = set()
        for m in _WIKILINK_RE.finditer(text):
            target = m.group(1).strip()
            if (
                not target
                or target in seen
                or target.endswith("/")
                or target.startswith("../")
            ):
                continue  # folder links and out-of-vault relative links are not note links
            seen.add(target)
            stem = Path(target).name
            if stem.lower().endswith(".md"):
                stem = stem[:-3]
            elif "." in stem:  # images, canvases, bases: out of scope
                continue
            matches = index.get(stem.lower(), [])
            if not matches:
                broken.findings.append(
                    Finding(
                        check=broken.id,
                        source=vault.name,
                        authority="vault (file tree)",
                        path=rel,
                        claim=f"[[{target}]] has no target note",
                        correction="fix the link or create the note",
                        status=DRIFT_DETECTED,
                        severity="LOW",
                    )
                )
            elif all(_is_archived(mm, vault) for mm in matches):
                archived.findings.append(
                    Finding(
                        check=archived.id,
                        source=vault.name,
                        authority="vault archive policy",
                        path=rel,
                        claim=f"[[{target}]] points only to an archived note",
                        correction="drop the link or mark it as historical reference",
                        status=DRIFT_DETECTED,
                        severity="MED",
                    )
                )
    archived.status = DRIFT_DETECTED if archived.findings else CURRENT
    broken.status = DRIFT_DETECTED if broken.findings else CURRENT
    return archived, broken


_PR_RE = re.compile(r"#(\d+)")


def _note_corpus(vault: Source) -> list[str]:
    lines: list[str] = []
    root = vault.root
    for f in vault.note_files:
        p = root / f
        if p.exists():
            lines.extend(p.read_text(encoding="utf-8", errors="replace").splitlines())
    for d in vault.note_dirs:
        for p in sorted((root / d).rglob("*.md")) if (root / d).is_dir() else []:
            lines.extend(p.read_text(encoding="utf-8", errors="replace").splitlines())
    return lines


_SHA7_RE = re.compile(r"@([0-9a-f]{7})")


def check_arch_changes_unreflected(
    repo: Source,
    vault: Source,
    since_sha: str | None,
    window_days: int,
    reexamine: list[str] | None = None,
) -> CheckResult:
    """Commits touching watched paths since the checkpoint with no vault mention.

    `reexamine` = short SHAs of findings still open from earlier runs: they are
    re-evaluated against today's notes, so an item stays open until a note cites
    it (or a human closes it) instead of vanishing when the checkpoint moves.
    """
    res = CheckResult(
        f"arch-changes-unreflected:{repo.name}", CURRENT, [repo.name, vault.name]
    )
    if not repo.watch_paths:
        res.note = "no watch_paths configured"
        return res
    if since_sha:
        _git(repo.path, "merge-base", "--is-ancestor", since_sha, "HEAD")
        rng = [f"{since_sha}..HEAD"]
    else:
        rng = [f"--since={window_days} days ago"]
    log = _git(
        repo.path, "log", "--format=%H%x1f%cs%x1f%s", *rng, "--", *repo.watch_paths
    )
    for sha7 in reexamine or []:
        try:
            log += (
                "\n"
                + _git(repo.path, "log", "-1", "--format=%H%x1f%cs%x1f%s", sha7).strip()
            )
        except RuntimeError as exc:
            raise RuntimeError("unresolved finding commit is unavailable") from exc
    corpus = _note_corpus(vault)
    by_key: dict[str, dict] = {}
    for line in log.splitlines():
        if not line.strip():
            continue
        sha, cdate, subject = line.split("\x1f", 2)
        pr = _PR_RE.search(subject)
        if not pr:  # a feature commit: name it after the PR that merged it, if any
            merges = _git(
                repo.path,
                "log",
                "--merges",
                "--format=%s",
                "--ancestry-path",
                f"{sha}..HEAD",
            ).splitlines()
            pr = _PR_RE.search(merges[-1]) if merges else None
        key = f"PR#{pr.group(1)}" if pr else sha[:7]
        files = _git(repo.path, "show", "--name-only", "--format=", sha).split()
        entry = by_key.setdefault(
            key, {"sha": sha[:7], "date": cdate, "subject": subject, "files": set()}
        )
        entry["files"].update(Path(f).name for f in files)
    needle_repo = repo.name.lower().replace("-", "_").split("_")[0]
    for key, e in by_key.items():
        mentioned = False
        for line in corpus:
            low = line.lower()
            if (
                key.startswith("PR#")
                and re.search(re.escape(key[2:]) + r"(?!\d)", line)
                and needle_repo in low
            ):
                mentioned = True
                break
            if (
                re.search(r"(?<![0-9a-f])" + e["sha"] + r"[0-9a-f]*(?![0-9a-f])", low)
                and needle_repo in low
            ):
                mentioned = True
                break
        if not mentioned:
            res.findings.append(
                Finding(
                    check=res.id,
                    source=repo.name,
                    authority=repo.authority,
                    path=f"{repo.name}@{e['sha']} ({e['date']})",
                    claim=f"{key}: {e['subject'][:110]} — touches watched paths, no vault note cites it",
                    correction="capture (decision/concept/log.md line) or confirm it needs none",
                    status=REVIEW_REQUIRED,
                    severity="MED",
                    approval=True,
                )
            )
    res.status = REVIEW_REQUIRED if res.findings else CURRENT
    return res


_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def vault_hashes(vault: Source) -> dict[str, str]:
    """Hashes of archived notes and decisions — the content that must not move silently."""
    out: dict[str, str] = {}
    root = vault.root
    dirs = list(vault.archive_dirs) + ["decisions"]
    for d in dirs:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.md")):
            out[p.relative_to(root).as_posix()] = _sha1_file(p)
    return out


def check_archived_content_modified(
    vault: Source,
    baseline: dict[str, str],
    current: dict[str, str],
    age_days: int,
    today: date,
) -> CheckResult:
    res = CheckResult("archived-content-modified", CURRENT, [vault.name])
    if not baseline:
        res.note = "first run: baseline recorded, nothing compared"
        return res
    for rel, h in current.items():
        old = baseline.get(rel)
        if old is None or old == h:
            continue
        if _is_archived(rel, vault):
            why = "archived note changed"
        else:
            m = _DATE_PREFIX_RE.match(Path(rel).name)
            if not m:
                continue
            if (today - date.fromisoformat(m.group(1))).days < age_days:
                continue
            why = f"decision older than {age_days} days changed"
        res.findings.append(
            Finding(
                check=res.id,
                source=vault.name,
                authority="vault history (append-only decisions)",
                path=rel,
                claim=why,
                correction="confirm the edit is an explicit amendment (superseded_by / addendum), never a rewrite",
                status=REVIEW_REQUIRED,
                severity="HIGH",
                approval=True,
            )
        )
    for rel in baseline:
        match = _DATE_PREFIX_RE.match(Path(rel).name)
        historical = _is_archived(rel, vault) or (
            match is not None
            and (today - date.fromisoformat(match.group(1))).days >= age_days
        )
        if rel not in current and historical:
            res.findings.append(
                Finding(
                    check=res.id,
                    source=vault.name,
                    authority="vault history",
                    path=rel,
                    claim="historical note deleted",
                    correction="restore or record the deletion in log.md",
                    status=REVIEW_REQUIRED,
                    severity="HIGH",
                    approval=True,
                )
            )
    res.status = REVIEW_REQUIRED if res.findings else CURRENT
    return res


def check_repo_docs_freshness(hotelops: Source) -> CheckResult:
    """Reuse scripts/check_docs_freshness.py on the hotelops checkout."""
    res = CheckResult("repo-docs-freshness", CURRENT, [hotelops.name])
    from scripts import (
        check_docs_freshness as cdf,
    )  # local import: keeps module import light

    previous = cdf.REPO_ROOT
    cdf.REPO_ROOT = hotelops.path
    try:
        reports = [cdf.check_doc(d) for d in cdf.collect_docs()]
    finally:
        cdf.REPO_ROOT = previous
    for r in reports:
        rel = r.path.relative_to(hotelops.path).as_posix()
        for dp in r.dead_paths:
            res.findings.append(
                Finding(
                    res.id,
                    hotelops.name,
                    "repo docs front-matter",
                    rel,
                    f"code_path `{dp}` no longer exists",
                    "fix code_paths",
                    DRIFT_DETECTED,
                    "MED",
                )
            )
        for cp, cd in r.stale_paths:
            res.findings.append(
                Finding(
                    res.id,
                    hotelops.name,
                    "repo docs front-matter",
                    rel,
                    f"`{cp}` changed on {cd} after last_verified={r.last_verified}",
                    "re-verify the doc and bump last_verified",
                    REVIEW_REQUIRED,
                    "LOW",
                )
            )
        if r.is_broken:
            res.findings.append(
                Finding(
                    res.id,
                    hotelops.name,
                    "repo docs front-matter",
                    rel,
                    f"front-matter: {r.parse_error}",
                    "fix front-matter",
                    DRIFT_DETECTED,
                    "LOW",
                )
            )
    res.status = worst(f.status for f in res.findings)
    return res


def coverage_not_verified() -> CheckResult:
    return CheckResult(
        "bigquery-ontology-i3",
        NOT_VERIFIED,
        [],
        note="D_* values vs vault ontology need BigQuery; this tool does not query runtime systems",
        completed=True,
    )


# ── State ─────────────────────────────────────────────────────────────────


def load_json(p: Path, default):
    if p.exists():
        value = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("invalid reconciliation state: expected object")
        return value
    return default


def merge_findings(
    previous: dict, current: list[Finding], checked_checks: set[str], now: str
) -> dict:
    """Stable IDs; resolve only after the exact check completed on verified snapshots."""
    out = copy.deepcopy(previous)
    seen = set()
    for f in current:
        seen.add(f.id)
        old = out.get(f.id, {})
        out[f.id] = {
            **asdict(f),
            "id": f.id,
            "first_seen": old.get("first_seen", now),
            "last_seen": now,
            "resolved_at": None,
            "state": "open",
        }
    for fid, rec in out.items():
        if fid in seen or rec.get("state") != "open":
            continue
        if rec.get("check") in checked_checks:
            rec["state"] = "resolved"
            rec["resolved_at"] = now
    return out


# ── Report ────────────────────────────────────────────────────────────────

_SECRET_RE = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|op://[^\s]+|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|sk-[A-Za-z0-9]{20,}|[\w.+-]+@[\w-]+\.[\w.-]+)"
)


def scrub(text: str) -> tuple[str, int]:
    scrubbed, n = _SECRET_RE.subn("[REDACTED]", text)
    return scrubbed, n


def _scrub_values(value):
    if isinstance(value, str):
        return scrub(value)[0]
    if isinstance(value, dict):
        return {k: _scrub_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_values(v) for v in value]
    return value


def render_report(run: dict) -> str:
    L: list[str] = []
    L.append(f"# Vault Loop reconciliation — {run['run_at'][:10]}")
    L.append("")
    L.append(
        f"**Overall: {run['overall']}**  (run {run['run_at']}, deterministic checks only)"
    )
    L.append("")
    L.append("## Sources")
    L.append("")
    L.append("| Source | Status | HEAD | Dirty | Checkpoint | Note |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for s in run["sources"]:
        L.append(
            f"| {s['name']} | {s['status']} | {(s['sha'] or '')[:7]} | {'yes' if s['dirty'] else 'no'} | "
            f"{'advanced' if s['checkpoint_advanced'] else 'held'} | {s['note']} |"
        )
    L.append("")
    L.append("## Checks")
    L.append("")
    L.append("| Check | Status | Findings | Note |")
    L.append("| --- | --- | --- | --- |")
    for c in run["checks"]:
        L.append(f"| {c['id']} | {c['status']} | {c['count']} | {c['note']} |")
    L.append("")
    open_f = [f for f in run["findings"].values() if f["state"] == "open"]
    resolved = [
        f for f in run["findings"].values() if f.get("resolved_at") == run["run_at"]
    ]
    for status in (DRIFT_DETECTED, REVIEW_REQUIRED):
        group = sorted(
            (f for f in open_f if f["status"] == status),
            key=lambda f: (f["severity"] != "HIGH", f["path"]),
        )
        L.append(f"## {status} ({len(group)} open)")
        L.append("")
        low: dict[tuple[str, str], list[dict]] = {}
        for f in group:
            if f["severity"] == "LOW":
                low.setdefault((f["check"], f["path"]), []).append(f)
                continue
            flag = " · approval" if f["approval"] else ""
            L.append(
                f"- `{f['id']}` [{f['severity']}] **{f['source']}** `{f['path']}` — {f['claim']}  "
                f"→ {f['correction']} (authority: {f['authority']}; since {f['first_seen'][:10]}{flag})"
            )
        if low:
            L.append("")
            L.append(
                f"LOW severity, grouped by note ({sum(len(v) for v in low.values())} findings; ids in findings.json):"
            )
            for (check, path), fs in sorted(low.items()):
                sample = "; ".join(f["claim"] for f in fs[:3]) + (
                    " …" if len(fs) > 3 else ""
                )
                L.append(f"- `{path}` · {check} × {len(fs)} — {sample}")
        if not group:
            L.append("- none")
        L.append("")
    L.append(f"## Resolved this run ({len(resolved)})")
    L.append("")
    for f in resolved:
        L.append(f"- `{f['id']}` {f['source']} `{f['path']}` — {f['claim']}")
    if not resolved:
        L.append("- none")
    L.append("")
    L.append("## Coverage")
    L.append("")
    L.append("- BigQuery / runtime state: NOT VERIFIED (not queried by this tool).")
    L.append(
        "- Semantic drift (Mode C check 9, judgment calls): left to the agent-run Vault Loop."
    )
    text = "\n".join(L) + "\n"
    text, n = scrub(text)
    if n:
        text += f"\n> {n} token/e-mail-like string(s) were redacted from this report.\n"
    return text


# ── Orchestration ─────────────────────────────────────────────────────────


def _run_reconcile(
    config_path: Path,
    state_dir: Path,
    *,
    today: date | None = None,
    window_days: int | None = None,
) -> dict:
    cfg, sources = load_config(config_path)
    today = today or datetime.now(UTC).date()
    window = window_days or int(cfg.get("first_run_window_days", 30))
    age_days = int(cfg.get("decision_age_days", 30))
    now = datetime.now(UTC).replace(microsecond=0).isoformat()

    state_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = state_dir / "state.json"
    bundle = load_json(bundle_path, {})
    if bundle_path.exists() and not bundle:
        raise ValueError("invalid reconciliation state bundle: empty object")
    checkpoint = (
        bundle.get("checkpoint")
        if bundle
        else load_json(
            state_dir / "checkpoint.json", {"sources": {}, "vault_hashes": {}}
        )
    )
    previous_findings = (
        bundle.get("findings") if bundle else load_json(state_dir / "findings.json", {})
    )
    if not isinstance(checkpoint, dict) or not isinstance(previous_findings, dict):
        raise TypeError("invalid reconciliation state bundle")

    for s in sources.values():
        resolve(s)
    hotelops = sources.get("hotelops")
    vault = sources.get("vault")
    repos = [s for n, s in sources.items() if n != "vault"]

    results: list[CheckResult] = []
    failed_sources: set[str] = set()

    def guard(fn, *args, cid: str, srcs: list[str]):
        try:
            out = fn(*args)
            checked = list(out) if isinstance(out, tuple) else [out]
            results.extend(checked)
            for result in checked:
                if any(
                    sources[name].dirty for name in result.sources if name in sources
                ):
                    result.completed = False
                    result.status = worst([result.status, NOT_VERIFIED])
                    result.note = (
                        result.note + "; " if result.note else ""
                    ) + "dependent working tree dirty: checkpoint and resolutions held"
                if not result.completed or result.status in (
                    NOT_VERIFIED,
                    SOURCE_UNAVAILABLE,
                ):
                    failed_sources.update(result.sources)
        except Exception as exc:  # noqa: BLE001 — a crashing check must not fake a result
            results.append(
                CheckResult(
                    cid,
                    NOT_VERIFIED,
                    srcs,
                    note=f"check failed: {exc}",
                    completed=False,
                )
            )
            failed_sources.update(srcs)

    if vault and vault.available:
        guard(
            check_vault_repo_pointers,
            vault,
            repos,
            cid="vault-repo-pointers",
            srcs=[vault.name] + [r.name for r in repos],
        )
        guard(check_wikilinks, vault, cid="wikilinks", srcs=[vault.name])
        if hotelops and hotelops.available:
            guard(
                check_invariant_range_claims,
                vault,
                hotelops,
                cid="invariant-range-claims",
                srcs=[vault.name, hotelops.name],
            )
        else:
            failed_sources.add(vault.name)
            results.append(
                CheckResult(
                    "invariant-range-claims",
                    SOURCE_UNAVAILABLE,
                    [vault.name, "hotelops"],
                    completed=False,
                )
            )
        for repo in repos:
            if repo.available:
                since = (checkpoint["sources"].get(repo.name) or {}).get("sha")
                reexamine = [
                    m.group(1)
                    for f in previous_findings.values()
                    if f.get("state") == "open"
                    and f.get("check") == f"arch-changes-unreflected:{repo.name}"
                    for m in [_SHA7_RE.search(f.get("path", ""))]
                    if m
                ]
                guard(
                    check_arch_changes_unreflected,
                    repo,
                    vault,
                    since,
                    window,
                    reexamine,
                    cid=f"arch-changes-unreflected:{repo.name}",
                    srcs=[repo.name, vault.name],
                )
        current_hashes = {}
        guard(
            lambda: (
                current_hashes.update(vault_hashes(vault))
                or check_archived_content_modified(
                    vault,
                    checkpoint.get("vault_hashes", {}),
                    current_hashes,
                    age_days,
                    today,
                )
            ),
            cid="archived-content-modified",
            srcs=[vault.name],
        )
    else:
        failed_sources.update(sources)
        current_hashes = {}
        for cid in (
            "vault-repo-pointers",
            "wikilinks",
            "invariant-range-claims",
            "arch-changes-unreflected:*",
            "archived-content-modified",
        ):
            results.append(
                CheckResult(
                    cid, SOURCE_UNAVAILABLE, ["vault"], note="vault unavailable"
                )
            )
    if hotelops and hotelops.available:
        guard(
            check_repo_docs_freshness,
            hotelops,
            cid="repo-docs-freshness",
            srcs=[hotelops.name],
        )
    else:
        results.append(
            CheckResult(
                "repo-docs-freshness",
                SOURCE_UNAVAILABLE,
                ["hotelops"],
                note="hotelops unavailable",
            )
        )
    coverage = coverage_not_verified()

    # Checkpoint: advance only clean, available sources whose checks all completed.
    checked_checks = {
        r.id
        for r in results
        if r.completed and r.status not in (NOT_VERIFIED, SOURCE_UNAVAILABLE)
    }
    source_rows = []
    for s in sources.values():
        advanced = s.available and not s.dirty and s.name not in failed_sources
        note = (
            s.error
            if not s.available
            else ("working tree dirty: checkpoint held" if s.dirty else "")
        )
        if s.name in failed_sources:
            note = (note + "; " if note else "") + "a check failed: checkpoint held"
        if advanced:
            checkpoint["sources"][s.name] = {"sha": s.sha, "verified_at": now}
            if s.name == "vault" and not any(
                r.id == "archived-content-modified" and r.findings for r in results
            ):
                checkpoint["vault_hashes"] = current_hashes
        source_rows.append(
            {
                "name": s.name,
                "status": NOT_VERIFIED
                if s.available and (s.dirty or s.name in failed_sources)
                else s.status,
                "sha": s.sha,
                "dirty": s.dirty,
                "checkpoint_advanced": advanced,
                "note": note,
                "authority": s.authority,
            }
        )
    all_findings = [f for r in results for f in r.findings]
    merged = _scrub_values(
        merge_findings(previous_findings, all_findings, checked_checks, now)
    )
    source_rows = _scrub_values(source_rows)
    overall = worst(
        [s["status"] for s in source_rows]
        + [r.status for r in results]
        + [f["status"] for f in merged.values() if f["state"] == "open"]
    )

    run = {
        "run_at": now,
        "overall": overall,
        "sources": source_rows,
        "checks": [
            {"id": r.id, "status": r.status, "count": len(r.findings), "note": r.note}
            for r in results + [coverage]
        ],
        "findings": merged,
    }
    checkpoint["last_run_at"] = now
    checkpoint["last_overall"] = overall
    report = render_report(run)
    # One atomic authoritative bundle: exports can be regenerated after a crash.
    _atomic_write(
        state_dir / "state.json",
        json.dumps(
            {"checkpoint": checkpoint, "findings": merged, "report": report},
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    _atomic_write(
        state_dir / "checkpoint.json",
        json.dumps(checkpoint, indent=2, sort_keys=True) + "\n",
    )
    _atomic_write(
        state_dir / "findings.json", json.dumps(merged, indent=2, sort_keys=True) + "\n"
    )
    _atomic_write(state_dir / "last_report.md", report)
    run["report"] = report
    return run


def _atomic_write(path: Path, content: str) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".vault-loop-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run_reconcile(config_path: Path, state_dir: Path, **kwargs) -> dict:
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _run_reconcile(config_path, state_dir, **kwargs)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    here = Path(__file__).resolve().parent.parent.parent
    ap.add_argument(
        "--config", type=Path, default=here / "meta" / "vault-loop" / "sources.yaml"
    )
    ap.add_argument(
        "--state", type=Path, default=here / ".hotelops_state" / "vault_loop"
    )
    ap.add_argument("--out", type=Path, default=None, help="also write the report here")
    ap.add_argument(
        "--since-days", type=int, default=None, help="first-run commit window"
    )
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    run = run_reconcile(a.config, a.state, window_days=a.since_days)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(run["report"], encoding="utf-8")
    if not a.quiet:
        print(run["report"])
    if run["overall"] == SOURCE_UNAVAILABLE:
        return 2
    if run["overall"] == NOT_VERIFIED:
        return 3
    return 0 if run["overall"] == CURRENT else 1


if __name__ == "__main__":
    sys.exit(main())
