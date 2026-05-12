"""Triage CapEx mining output — classify each thread to F* supplier folder.

Reads index.csv files from a workspace mine-capex run, filters threads
≥ CUTOFF_DATE, asks Claude to map each thread to one of the 33 F* suppliers
(or SCARTATO_*/GENERIC_PROJECT/NOISE), writes triage_proposal.csv for user
review before applying routes.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

import anthropic
import yaml

MODEL = "claude-haiku-4-5-20251001"
BATCH_SIZE = 10

DEFAULT_CONFIG = (
    Path(__file__).resolve().parent.parent / "projects" / "HPAN25PIANO1" / "suppliers.yaml"
)


def load_config(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def build_static_from_config(cfg: dict):
    suppliers = [(s["code"], s["ragione_sociale"], s["scope"]) for s in cfg["suppliers"]]
    extras = [(c["code"], c["label"]) for c in cfg["extra_codes"]]
    valid_f = {s[0] for s in suppliers} | {c[0] for c in extras}
    valid_sub = set(cfg["valid_subfolders"])
    suppliers_text = "\n".join(f"  {c}: {n} — {s}" for c, n, s in suppliers)
    extras_text = "\n".join(f"  {c}: {label}" for c, label in extras)
    return suppliers, extras, valid_f, valid_sub, suppliers_text, extras_text


_CFG = load_config(DEFAULT_CONFIG)
SUPPLIERS, EXTRAS, VALID_F, VALID_SUB, SUPPLIERS_TEXT, EXTRAS_TEXT = build_static_from_config(_CFG)
CUTOFF_DATE = _CFG["cutoff_date"]


SYSTEM_PROMPT = f"""You classify emails for the CapEx project HPAN25PIANO1 (Hotel Panorama Maiori, Italy — renovation of 10 rooms on the first floor, end of project, retrospective lineage recovery).

The known suppliers (F-code: ragione sociale — scope):
{SUPPLIERS_TEXT}

ADDITIONAL codes:
{EXTRAS_TEXT}

Subfolders within F*/:
- 01_preventivi: offers, quotes, preventivi, technical specs from supplier
- 02_ordini_contratti: signed orders, contracts, accepted offers, OC, contratti di appalto
- 04_comunicazioni: discussion, decisions, scheduling, status updates, sopralluoghi, technical Q&A

For each thread input, output exactly one JSON object with these fields:
- f_code: one of the F-codes above, or SCARTATO_RUMOLO/SCARTATO_APICELLA/GENERIC_PROJECT/NOISE
- subfolder: 01_preventivi | 02_ordini_contratti | 04_comunicazioni (use 04_comunicazioni for GENERIC_PROJECT and any ambiguous case)
- confidence: HIGH | MED | LOW
- reasoning: ≤120 chars explaining the choice

Return a JSON ARRAY only (no markdown fences). One object per input thread, in the same order. No extra prose."""


def build_user_prompt(threads: list[dict]) -> str:
    lines = ["Classify these threads (one JSON object each, same order):", ""]
    for i, t in enumerate(threads, 1):
        lines.append(
            f"{i}. date={t['first_date']} | from={t['first_from']} | "
            f"subj={t['first_subject']} | msgs={t['n_messages']} atts={t['n_attachments']}"
        )
    return "\n".join(lines)


def parse_response(raw: str, n_expected: int) -> list[dict]:
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    fallback = {"f_code": "NOISE", "subfolder": "04_comunicazioni", "confidence": "LOW", "reasoning": "parse fail"}
    if not m:
        return [fallback] * n_expected
    try:
        items = json.loads(m.group(0))
    except json.JSONDecodeError:
        return [fallback] * n_expected
    out = []
    for it in items[:n_expected]:
        f = it.get("f_code", "NOISE")
        if f not in VALID_F:
            f = "NOISE"
        sub = it.get("subfolder", "04_comunicazioni")
        if sub not in VALID_SUB:
            sub = "04_comunicazioni"
        out.append({
            "f_code": f,
            "subfolder": sub,
            "confidence": it.get("confidence", "LOW"),
            "reasoning": (it.get("reasoning") or "")[:200],
        })
    while len(out) < n_expected:
        out.append(fallback)
    return out


def load_threads(csv_path: Path, mailbox: str) -> list[dict]:
    rows = []
    with csv_path.open() as f:
        for r in csv.DictReader(f):
            if r["first_date"] < CUTOFF_DATE:
                continue
            r["mailbox"] = mailbox
            rows.append(r)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gm-index", required=True, type=Path)
    ap.add_argument("--admin-index", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=0, help="Cap on threads for smoke test (0 = all)")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — load .env or export it", file=sys.stderr)
        sys.exit(2)

    threads = load_threads(args.gm_index, "gm") + load_threads(args.admin_index, "amministrazione")
    threads.sort(key=lambda r: r["first_date"], reverse=True)
    if args.limit:
        threads = threads[: args.limit]
    print(f"Loaded {len(threads)} threads (cutoff ≥ {CUTOFF_DATE})")

    client = anthropic.Anthropic()
    results: list[dict] = []
    total_in = total_out = total_cache_read = total_cache_create = 0

    for i in range(0, len(threads), BATCH_SIZE):
        batch = threads[i : i + BATCH_SIZE]
        msg = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": build_user_prompt(batch)}],
        )
        text = msg.content[0].text
        parsed = parse_response(text, len(batch))
        for t, c in zip(batch, parsed):
            results.append({**t, **c})
        u = msg.usage
        total_in += u.input_tokens
        total_out += u.output_tokens
        total_cache_read += getattr(u, "cache_read_input_tokens", 0) or 0
        total_cache_create += getattr(u, "cache_creation_input_tokens", 0) or 0
        print(
            f"  batch {i // BATCH_SIZE + 1:>2} ({len(batch)} threads) — "
            f"in={u.input_tokens} cache_r={total_cache_read} cache_w={total_cache_create} out={u.output_tokens}"
        )

    fields = [
        "mailbox", "thread_id", "first_date", "first_from", "first_subject",
        "n_messages", "n_attachments", "drive_folder",
        "f_code", "subfolder", "confidence", "reasoning",
    ]
    with args.output.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in fields})

    print(f"\nWrote {args.output} ({len(results)} rows)")
    print(f"Tokens: in={total_in}, out={total_out}, cache_read={total_cache_read}, cache_create={total_cache_create}")


if __name__ == "__main__":
    main()
