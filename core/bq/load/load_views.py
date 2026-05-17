"""Deploy BigQuery views from core/bq/views/*.sql.

Each .sql file is a self-contained CREATE OR REPLACE VIEW statement. Views may
reference other views; this loader extracts those references, topologically
sorts them, and deploys in dependency order. Idempotent (CREATE OR REPLACE).

Adding a new view = drop a .sql file in core/bq/views/. No edit here.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from core.bq.client import get_client

log = logging.getLogger(__name__)

VIEWS_DIR = Path(__file__).resolve().parents[1] / "views"
_VIEW_REF = re.compile(r"\bv_[a-z0-9_]+")
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _load_view_sql() -> dict[str, str]:
    """Map view name (file stem) -> SQL text for every .sql in views/."""
    return {
        f.stem: f.read_text(encoding="utf-8") for f in sorted(VIEWS_DIR.glob("*.sql"))
    }


def _dependency_order(views: dict[str, str]) -> list[str]:
    """Topologically sort view names so dependencies deploy first.

    A dependency is any v_* token in the SQL body (comments stripped) that is
    itself a view file here. Self-references and views without a .sql file are
    ignored — the latter are assumed to already exist in BigQuery.
    """
    names = set(views)
    deps: dict[str, set[str]] = {}
    for name, sql in views.items():
        body = _BLOCK_COMMENT.sub("", _LINE_COMMENT.sub("", sql))
        deps[name] = (set(_VIEW_REF.findall(body)) & names) - {name}

    ordered: list[str] = []
    seen: set[str] = set()

    def visit(name: str, stack: tuple[str, ...]) -> None:
        if name in seen:
            return
        if name in stack:
            cycle = " -> ".join(stack[stack.index(name):] + (name,))
            raise ValueError(f"Cyclic view dependency: {cycle}")
        for dep in sorted(deps[name]):
            visit(dep, stack + (name,))
        seen.add(name)
        ordered.append(name)

    for name in sorted(views):
        visit(name, ())
    return ordered


def deploy_views(dry_run: bool = False) -> list[str]:
    """CREATE OR REPLACE every view in core/bq/views/, in dependency order.

    Returns the ordered list of view names.
    """
    views = _load_view_sql()
    if not views:
        log.warning("No .sql files found in %s", VIEWS_DIR)
        return []
    order = _dependency_order(views)
    if dry_run:
        for i, name in enumerate(order, 1):
            log.info("[DRY-RUN] %2d. would deploy %s", i, name)
        return order
    client = get_client()
    for i, name in enumerate(order, 1):
        log.info("%2d/%d  deploying %s ...", i, len(order), name)
        client.query(views[name]).result()
    log.info("✓ %d views deployed", len(order))
    return order


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(
        description="Deploy BigQuery views from core/bq/views/ in dependency order"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Show deploy order, don't execute"
    )
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    deploy_views(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
