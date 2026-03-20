#!/usr/bin/env python3
"""
Budget Wizard — input interattivo con storico BQ a fianco.

Per ogni voce × mese mostra gli ultimi 2 anni di consuntivo e chiede il valore budget.

Comandi al prompt:
  <numero>   → imposta importo (es. 28000)
  =          → copia valore del mese precedente
  s          → salta (lascia vuoto)
  q          → salva e esci
  ?          → mostra storico esteso

Output: CSV pronto per ingest_piano_finanziario_input.py

Usage:
    python tools/budget_wizard.py --societa ORTI --from 2026-04 --to 2026-12
    python tools/budget_wizard.py --societa INTUR --from 2026-01 --to 2026-12
    python tools/budget_wizard.py --societa ORTI --sezione ENTRATE --from 2026-04 --to 2026-12
    python tools/budget_wizard.py --societa ORTI --voce ENTRATE_HOTEL --from 2026-04 --to 2026-12
"""

import argparse
import csv
import hashlib
import sys

try:
    from google.cloud import bigquery
    HAS_BQ = True
except ImportError:
    HAS_BQ = False

PROJECT = "hotelops-suite"
DATASET = "hotelops"


def make_hash(societa_id, voce_id, anno, mese, fonte):
    key = f"{societa_id}|{voce_id}|{anno}|{mese}|{fonte}"
    return hashlib.md5(key.encode()).hexdigest()


def months_range(from_ym, to_ym):
    """Generate (anno, mese) tuples between YYYY-MM strings inclusive."""
    y0, m0 = int(from_ym[:4]), int(from_ym[5:7])
    y1, m1 = int(to_ym[:4]), int(to_ym[5:7])
    result = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        result.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return result


def load_voci(bq, societa, sezione_filter, voce_filter):
    q = f"""
        SELECT voce_id, voce_label, sezione, categoria, societa_id
        FROM `{PROJECT}.{DATASET}.d_voci_piano_finanziario`
        WHERE fonte = 'ESOLVER' OR fonte = 'BANCHE'
    """
    if sezione_filter:
        q += f" AND sezione = '{sezione_filter.upper()}'"
    if voce_filter:
        q += f" AND voce_id = '{voce_filter}'"
    q += " ORDER BY ord"

    rows = list(bq.query(q).result())
    # Filter by societa: include voci with NULL societa or matching societa
    return [r for r in rows if not r.societa_id or r.societa_id == societa]


def load_storico(bq, voce_id, societa):
    """Last 24 months of consuntivo for this voce+societa."""
    q = f"""
        SELECT anno, mese, ROUND(importo, 0) AS importo
        FROM `{PROJECT}.{DATASET}.v_piano_finanziario_consuntivo`
        WHERE voce_id = '{voce_id}'
          AND societa_id = '{societa}'
          AND DATE(CAST(anno AS STRING) || '-' || FORMAT('%02d', mese) || '-01')
              >= DATE_SUB(CURRENT_DATE('Europe/Rome'), INTERVAL 24 MONTH)
        ORDER BY anno, mese
    """
    try:
        return {(r.anno, r.mese): int(r.importo) for r in bq.query(q).result()}
    except Exception:
        return {}


def load_stesso_anno_precedente(storico, anno, mese):
    """Stessa voce, anno precedente."""
    return storico.get((anno - 1, mese))


def format_storico_line(storico, mesi_range_plan):
    """Build a compact historical display."""
    # Show last 12 months before planning period
    y0, m0 = mesi_range_plan[0]
    history = []
    y, m = y0, m0
    for _ in range(12):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        history.insert(0, (y, m))

    parts = []
    for y, m in history:
        val = storico.get((y, m))
        if val is not None:
            parts.append(f"{y}-{m:02d}:{val:>9,.0f}")
        else:
            parts.append(f"{y}-{m:02d}:{'—':>9}")
    return "  ".join(parts)


MESE_NOMI = ["", "Gen", "Feb", "Mar", "Apr", "Mag", "Giu",
             "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

CYAN  = "\033[96m"
GREEN = "\033[92m"
YELLOW= "\033[93m"
BOLD  = "\033[1m"
DIM   = "\033[2m"
RESET = "\033[0m"


def run_wizard(bq, societa, from_ym, to_ym, sezione_filter, voce_filter, fonte, output_path):
    voci = load_voci(bq, societa, sezione_filter, voce_filter)
    if not voci:
        print("Nessuna voce trovata con i filtri specificati.")
        sys.exit(1)

    mesi = months_range(from_ym, to_ym)
    rows_out = []
    last_value = {}  # voce_id → last entered value

    print(f"\n{BOLD}{'='*70}{RESET}")
    print(f"{BOLD}  Budget Wizard — {societa}  {from_ym} → {to_ym}{RESET}")
    print(f"  {len(voci)} voci × {len(mesi)} mesi = {len(voci)*len(mesi)} valori")
    print("  Comandi: <numero> | = (ripeti) | s (salta) | ? (storico) | q (salva+esci)")
    print(f"{BOLD}{'='*70}{RESET}\n")

    total = len(voci) * len(mesi)
    done = 0

    for voce in voci:
        voce_id = voce.voce_id
        label = voce.voce_label
        sezione = voce.sezione
        categoria = voce.categoria

        storico = load_storico(bq, voce_id, societa)

        color = CYAN if sezione == "ENTRATE" else YELLOW
        print(f"\n{color}{BOLD}▶ {label}{RESET}  {DIM}[{voce_id}  {categoria}]{RESET}")

        # Show compact storico
        hist_line = format_storico_line(storico, mesi)
        print(f"  {DIM}Storico:{RESET} {hist_line}")

        # Same period prior year summary
        anno_min = mesi[0][0]
        prior = [(m, storico.get((anno_min - 1, m))) for _, m in mesi]
        prior_vals = [(m, v) for m, v in prior if v is not None]
        if prior_vals:
            prior_str = "  ".join(f"{MESE_NOMI[m]}:{v:>9,.0f}" for m, v in prior_vals)
            print(f"  {DIM}Anno prec:{RESET} {prior_str}")

        print()

        for anno, mese in mesi:
            done += 1
            pct = done / total * 100
            prior_val = storico.get((anno - 1, mese))
            prior_hint = f"  {DIM}(anno prec: {prior_val:,.0f}){RESET}" if prior_val else ""
            last_hint  = f"  {DIM}(= ripete {last_value.get(voce_id, '—'):,.0f}){RESET}" if voce_id in last_value else ""

            prompt = (f"  {MESE_NOMI[mese]} {anno}"
                      f"{prior_hint}{last_hint}"
                      f"  {DIM}[{pct:.0f}%]{RESET} → ")

            while True:
                try:
                    raw = input(prompt).strip()
                except (EOFError, KeyboardInterrupt):
                    print(f"\n{GREEN}Salvataggio...{RESET}")
                    _save(rows_out, output_path, societa, fonte)
                    return

                if raw == "q":
                    print(f"\n{GREEN}Salvataggio e uscita...{RESET}")
                    _save(rows_out, output_path, societa, fonte)
                    return
                elif raw == "s":
                    break  # skip
                elif raw == "=":
                    if voce_id in last_value:
                        importo = last_value[voce_id]
                        rows_out.append(_row(societa, voce_id, anno, mese, importo, fonte, label))
                        last_value[voce_id] = importo
                        print(f"    {GREEN}✓ {importo:,.0f}{RESET}")
                        break
                    else:
                        print("    Nessun valore precedente da copiare.")
                elif raw == "?":
                    # Extended storico
                    for (y, mo), v in sorted(storico.items()):
                        print(f"    {y}-{mo:02d}: {v:>12,.0f}")
                elif raw == "":
                    break  # skip silently
                else:
                    try:
                        # Accept numbers with comma or dot as thousands/decimal
                        cleaned = raw.replace(".", "").replace(",", ".")
                        importo = float(cleaned)
                        rows_out.append(_row(societa, voce_id, anno, mese, importo, fonte, label))
                        last_value[voce_id] = importo
                        print(f"    {GREEN}✓ {importo:,.0f}{RESET}")
                        break
                    except ValueError:
                        print(f"    Valore non valido: '{raw}'. Usa un numero, =, s, q, o ?")

    print(f"\n{GREEN}{BOLD}Completato!{RESET}")
    _save(rows_out, output_path, societa, fonte)


def _row(societa, voce_id, anno, mese, importo, fonte, label):
    return {
        "hash_riga":     make_hash(societa, voce_id, anno, mese, fonte),
        "societa_id":    societa,
        "voce_id":       voce_id,
        "anno":          anno,
        "mese":          mese,
        "importo":       importo,
        "fonte":         fonte,
        "note":          label,
    }


def _save(rows, output_path, societa, fonte):
    if not rows:
        print("Nessun valore inserito.")
        return

    fieldnames = ["societa_id", "voce_id", "anno", "mese", "importo", "fonte", "note"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"\n  {rows[0]['fonte']} {societa}: {len(rows)} valori → {output_path}")
    print("\n  Per caricare in BQ:")
    print(f"  python -m pipelines.amministrativa.ingest_piano_finanziario_input --file {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Budget Wizard — input interattivo con storico BQ")
    parser.add_argument("--societa",  required=True, choices=["INTUR", "ORTI"])
    parser.add_argument("--from",     dest="from_ym", required=True, help="Es. 2026-04")
    parser.add_argument("--to",       dest="to_ym",   required=True, help="Es. 2026-12")
    parser.add_argument("--sezione",  help="ENTRATE o USCITE (opzionale)")
    parser.add_argument("--voce",     help="Filtra su una voce specifica (es. ENTRATE_HOTEL)")
    parser.add_argument("--fonte",    default="BUDGET", help="Fonte da scrivere nel CSV (default: BUDGET)")
    parser.add_argument("--output",   help="Path CSV output (default: /tmp/budget_<societa>_<from>.csv)")
    args = parser.parse_args()

    if not HAS_BQ:
        print("google-cloud-bigquery non installato.")
        sys.exit(1)

    output = args.output or f"/tmp/budget_{args.societa}_{args.from_ym}.csv"

    bq = bigquery.Client(project=PROJECT)
    run_wizard(bq, args.societa, args.from_ym, args.to_ym,
               args.sezione, args.voce, args.fonte, output)


if __name__ == "__main__":
    main()
