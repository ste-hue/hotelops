"""One-shot migration: aggiunge colonne is_excluded, exclude_reason, societa_id."""

import csv
from pathlib import Path

SRC = Path("core/bq/dimensioni/d_fornitori.csv")


def main():
    with SRC.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    out_fields = [
        "codice_fornitore",
        "nome_esolver",
        "nome_pf",
        "voce_id",
        "is_intercompany",
        "is_excluded",
        "exclude_reason",
        "societa_id",
    ]
    with SRC.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields)
        writer.writeheader()
        for r in rows:
            r["is_excluded"] = "False"
            r["exclude_reason"] = ""
            r["societa_id"] = "ORTI"
            writer.writerow({k: r.get(k, "") for k in out_fields})
    print(f"Migrated {len(rows)} rows")


if __name__ == "__main__":
    main()
