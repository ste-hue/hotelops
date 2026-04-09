#!/usr/bin/env python3
"""Check freshness of repo docs against the code they describe.

Each doc in `docs/procedures/` and `docs/protocols/` carries YAML front-matter:

    ---
    subsystem: ingest
    code_paths:
      - ingest/classify.py
      - core/registry.yaml
    last_verified: 2026-04-09
    ---

This script flags two conditions:

  STALE — at least one `code_path` has a git commit date strictly newer than
          `last_verified`. The doc was not re-verified after the code change.
  DEAD  — at least one `code_path` no longer exists on disk.

Exit codes (CI-friendly):
    0  clean
    1  stale (some docs need re-verification)
    2  dead  (some docs reference missing paths) — takes precedence over stale

Used by `hotelops health` and as a standalone command.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_DIRS = ["docs/procedures", "docs/protocols"]


@dataclass
class DocReport:
    path: Path
    subsystem: str = ""
    last_verified: date | None = None
    code_paths: list[str] = field(default_factory=list)
    stale_paths: list[tuple[str, date]] = field(default_factory=list)  # (path, commit_date)
    dead_paths: list[str] = field(default_factory=list)
    parse_error: str = ""

    @property
    def is_stale(self) -> bool:
        return bool(self.stale_paths)

    @property
    def is_dead(self) -> bool:
        return bool(self.dead_paths)

    @property
    def is_broken(self) -> bool:
        return bool(self.parse_error)


# ── Front-matter parser (no PyYAML dep — keep it simple) ──────────────────


def parse_frontmatter(text: str) -> dict | None:
    """Parse a minimal YAML front-matter block. Returns dict or None.

    Supports: scalars (str/date), lists of scalars introduced by `key:` then `- item` lines.
    Comments and quoted strings are NOT supported — keep front-matter clean.
    """
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    block = text[4:end]
    out: dict = {}
    current_list_key: str | None = None
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") or line.startswith("- "):
            if current_list_key is None:
                continue
            item = line.lstrip()[2:].strip()
            out.setdefault(current_list_key, []).append(item)
            continue
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value == "":
                current_list_key = key
                out.setdefault(key, [])
            else:
                current_list_key = None
                out[key] = value
    return out


def _coerce_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


# ── Git helpers ───────────────────────────────────────────────────────────


def git_last_commit_date(path: Path) -> date | None:
    """Return the ISO date of the most recent commit that touched `path`.

    None if the path is not tracked or has no commits yet.
    """
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", str(path)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None
    out = result.stdout.strip()
    if not out:
        return None
    # %cI is committer date in strict ISO 8601, e.g. 2026-04-09T17:12:34+02:00
    return date.fromisoformat(out[:10])


# ── Per-doc check ─────────────────────────────────────────────────────────


def check_doc(doc_path: Path) -> DocReport:
    rep = DocReport(path=doc_path)
    text = doc_path.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    if fm is None:
        rep.parse_error = "missing or malformed front-matter"
        return rep

    rep.subsystem = str(fm.get("subsystem", "")).strip()
    rep.last_verified = _coerce_date(fm.get("last_verified"))
    rep.code_paths = list(fm.get("code_paths") or [])

    if rep.last_verified is None:
        rep.parse_error = "missing or invalid last_verified"
        return rep
    if not rep.code_paths:
        rep.parse_error = "missing code_paths"
        return rep

    for cp in rep.code_paths:
        full = REPO_ROOT / cp
        if not full.exists():
            rep.dead_paths.append(cp)
            continue
        commit_date = git_last_commit_date(full)
        if commit_date is None:
            # untracked or no commits — treat as fresh, just skip
            continue
        if commit_date > rep.last_verified:
            rep.stale_paths.append((cp, commit_date))

    return rep


def collect_docs() -> list[Path]:
    out: list[Path] = []
    for d in DOC_DIRS:
        base = REPO_ROOT / d
        if not base.exists():
            continue
        out.extend(sorted(p for p in base.glob("*.md") if not p.name.startswith("README")))
    return out


# ── Reporting ─────────────────────────────────────────────────────────────


def format_report(reports: Iterable[DocReport]) -> str:
    reports = list(reports)
    lines: list[str] = []
    n_total = len(reports)
    n_stale = sum(1 for r in reports if r.is_stale)
    n_dead = sum(1 for r in reports if r.is_dead)
    n_broken = sum(1 for r in reports if r.is_broken)
    n_clean = n_total - n_stale - n_dead - n_broken

    lines.append(
        f"  📚 DOCS FRESHNESS: {n_total} docs — "
        f"✓ {n_clean} clean, ⚠ {n_stale} stale, ✗ {n_dead} dead, ? {n_broken} broken"
    )

    for r in reports:
        rel = r.path.relative_to(REPO_ROOT)
        if r.is_broken:
            lines.append(f"    ? {rel}: {r.parse_error}")
            continue
        if r.is_dead:
            for dp in r.dead_paths:
                lines.append(f"    ✗ {rel}: dead path → {dp}")
        if r.is_stale:
            for cp, cd in r.stale_paths:
                delta = (cd - r.last_verified).days if r.last_verified else "?"
                lines.append(
                    f"    ⚠ {rel}: {cp} touched {cd} "
                    f"(+{delta}d after last_verified={r.last_verified})"
                )

    return "\n".join(lines)


def run() -> int:
    docs = collect_docs()
    reports = [check_doc(d) for d in docs]
    print(format_report(reports))
    if any(r.is_dead for r in reports):
        return 2
    if any(r.is_stale or r.is_broken for r in reports):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
