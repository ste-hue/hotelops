"""Classify run-folder attachments file-by-file.

Stage 1 — filename + extension heuristic (free, instant).
Stage 2 — for ambiguous PDFs: pdftotext first 2 pages + Claude classifier (cheap).

Categories:
  PREVENTIVO       — offerta fornitore (quote with prices)
  CONTRATTO        — signed order / conferma ordine / contratto appalto
  FATTURA          — invoice (skip in apply: already in 06_FATTURE/)
  TECNICO          — capitolato, computo, SAL, abaco, planimetria, DWG
  LEGAL_NOISE      — atto notarile, visura, fitto, donazione, assemblea
  GENERIC_PROJECT  — business plan, perizia banca, bilancio, cronoprogramma
  FOTO             — image attachments
  SKIP             — non-classifiable garbage (.mso, .eml chunks)
  ALTRO            — Stage 2 fallback when nothing fits
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import anthropic

MODEL = "claude-haiku-4-5-20251001"
BATCH_SIZE = 8

KEYWORDS = [
    ("FATTURA",        re.compile(r"(fattura|\bft[\s_\-]|fpr|\.xml\.p7m|invoice|nota_credito)", re.I)),
    ("CONTRATTO",      re.compile(r"(contratto|conferma[\s_]*ordine|\boc[\s_\-]\d|ordine[\s_]firmato|appalto|sottoscritto)", re.I)),
    ("PREVENTIVO",     re.compile(r"(preventivo|\bprev\d|\bprev[\s_]|offerta|quotation|quote|offer|listino|preventivi)", re.I)),
    ("TECNICO",        re.compile(r"(computo|metrico|\bsal\d?\b|capitolato|abaco|planimetria|render|rendering|disegno|esecutivo|sezione|elevati|pavimentazione|definitiv|prospetto|tinteggiatur|condizionamento)", re.I)),
    ("LEGAL_NOISE",    re.compile(r"(\batto\b|donazione|nulla[\s_]osta|fitto|visura|assemblea|verbale|nota[\s_]ipotecaria|sentenza|procura|catastale|notaio|ipoteca|tribunale|aras)", re.I)),
    ("GENERIC_PROJECT", re.compile(r"(business[\s_]plan|\bbp[\s_]|bilancio|perizia|asseverazione|finanziamento|credito[\s_]imposta|medio[\s_]credito|gantt|cronoprogramma|sviluppo[\s_]turistico|budget[\s_]cost)", re.I)),
]

PDF_EXT = ".pdf"
DWG_EXT = {".dwg", ".dxf"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".heic", ".gif", ".bmp"}
ARCHIVE_EXT = {".rar", ".zip", ".7z"}
SKIP_EXT = {".mso", ".eml", ".ics", ".vcf"}
SPREADSHEET_EXT = {".xlsx", ".xls", ".csv"}
DOCUMENT_EXT = {".doc", ".docx", ".odt"}


def stage1_classify(filename: str) -> str | None:
    """Return category or None if ambiguous (needs Stage 2)."""
    name = filename.lower()
    ext = Path(filename).suffix.lower()
    if ext in SKIP_EXT:
        return "SKIP"
    if ext in IMG_EXT:
        return "FOTO"
    if ext in DWG_EXT:
        return "TECNICO"
    if ext in ARCHIVE_EXT:
        return "TECNICO"  # likely DWG/specs bundles
    for cat, pat in KEYWORDS:
        if pat.search(filename):
            return cat
    # Spreadsheet/Document without keyword → ambiguous, but we won't Stage2 them
    if ext in SPREADSHEET_EXT or ext in DOCUMENT_EXT:
        return "ALTRO"
    if ext != PDF_EXT:
        return "ALTRO"
    return None  # ambiguous PDF — Stage 2


def list_files(run_dir: Path) -> list[Path]:
    return [
        p for p in run_dir.rglob("*")
        if p.is_file()
        and p.name not in ("thread.json", "index.csv", "README.md", "triage_proposal.csv")
        and not p.name.startswith(".")
    ]


def pdftotext_excerpt(pdf: Path, max_chars: int = 2500) -> str:
    try:
        r = subprocess.run(
            ["pdftotext", "-l", "2", "-layout", str(pdf), "-"],
            capture_output=True, text=True, timeout=15
        )
        return (r.stdout or "")[:max_chars]
    except Exception as e:
        return f"<pdftotext failed: {e}>"


SYSTEM_STAGE2 = """You classify single CapEx documents (Italian, hotel renovation HPAN25PIANO1 — Camere Primo Piano Hotel Panorama).

Categories (pick exactly one):
- PREVENTIVO: offerta economica di un fornitore (prezzi unitari + totale, intestato a Panorama/INTUR/ORTI, ricevuto dal vendor)
- CONTRATTO: contratto firmato, ordine di acquisto, conferma ordine
- FATTURA: fattura fornitore (numero FT/FPR, importo definitivo, partita IVA emittente)
- TECNICO: capitolato, computo metrico, SAL, abaco, planimetria, rendering, disegno tecnico, schede tecniche
- LEGAL_NOISE: atto notarile, visura catastale, nulla osta edilizio, donazione, fitto d'azienda, sentenza, procura
- GENERIC_PROJECT: business plan, bilancio, perizia/asseverazione per banca, documenti finanziamento, cronoprogramma
- ALTRO: non rientra in nessuna categoria sopra (es. email di servizio, ricevute generiche)

For each input, output JSON object:
{
  "category": "<one of above>",
  "fornitore": "<nome fornitore se identificabile dal testo, else null>",
  "importo_eur": <numero netto IVA esc. se preventivo/contratto/fattura con totale chiaro, else null>,
  "confidence": "HIGH|MED|LOW",
  "reasoning": "<short, <=80 chars>"
}

Return JSON ARRAY only (one item per input, same order). No markdown fences."""


def stage2_batch(client, items: list[tuple[str, str]]) -> list[dict]:
    blocks = []
    for i, (fn, text) in enumerate(items, 1):
        blocks.append(f"### {i}. filename: {fn}\nextract:\n{text}")
    user_prompt = "Classify these documents:\n\n" + "\n\n".join(blocks)
    msg = client.messages.create(
        model=MODEL, max_tokens=4096,
        system=[{"type": "text", "text": SYSTEM_STAGE2, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = msg.content[0].text
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    fallback = {"category": "ALTRO", "fornitore": None, "importo_eur": None, "confidence": "LOW", "reasoning": "parse fail"}
    if not m:
        return [fallback] * len(items)
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError:
        return [fallback] * len(items)
    while len(parsed) < len(items):
        parsed.append(fallback)
    return parsed[:len(items)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-run-dir", required=True, type=Path,
                    help="Local copy of the run folder (rclone copy ... --here)")
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY missing", file=sys.stderr)
        sys.exit(2)

    files = list_files(args.local_run_dir)
    if args.limit:
        files = files[: args.limit]
    print(f"Total files: {len(files)}")

    rows = []
    ambiguous_idx = []
    for f in files:
        cat = stage1_classify(f.name)
        rel = f.relative_to(args.local_run_dir)
        rows.append({
            "path": str(rel),
            "filename": f.name,
            "ext": f.suffix.lower(),
            "size_kb": f.stat().st_size // 1024,
            "stage1": cat or "AMBIGUOUS",
            "stage2": "",
            "category_final": cat or "",
            "fornitore": "",
            "importo_eur": "",
            "confidence": "",
            "reasoning": "",
        })
        if cat is None:
            ambiguous_idx.append((len(rows) - 1, f))

    c1 = Counter(r["stage1"] for r in rows)
    print(f"Stage 1: {dict(c1)}")
    print(f"Ambiguous PDFs → Stage 2: {len(ambiguous_idx)}")

    if ambiguous_idx:
        client = anthropic.Anthropic()
        total_in = total_out = 0
        for i in range(0, len(ambiguous_idx), BATCH_SIZE):
            batch = ambiguous_idx[i : i + BATCH_SIZE]
            texts = [(f.name, pdftotext_excerpt(f)) for _, f in batch]
            results = stage2_batch(client, texts)
            for (idx, _), r in zip(batch, results):
                cat = r.get("category", "ALTRO")
                rows[idx]["stage2"] = cat
                rows[idx]["category_final"] = cat
                rows[idx]["fornitore"] = r.get("fornitore") or ""
                imp = r.get("importo_eur")
                rows[idx]["importo_eur"] = str(imp) if imp is not None else ""
                rows[idx]["confidence"] = r.get("confidence", "LOW")
                rows[idx]["reasoning"] = (r.get("reasoning") or "")[:200]
            # token tracking (best-effort)
            print(f"  Stage 2 batch {i // BATCH_SIZE + 1}: {len(batch)} files")

    fields = ["path", "filename", "ext", "size_kb", "stage1", "stage2",
              "category_final", "fornitore", "importo_eur", "confidence", "reasoning"]
    with args.output.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    final = Counter(r["category_final"] or "EMPTY" for r in rows)
    print(f"\nFinal category breakdown:")
    for k in sorted(final, key=lambda x: -final[x]):
        print(f"  {k:18s} {final[k]:>4}")
    print(f"\nWrote {args.output} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
