"""hotelops pf-genera — genera il PF post-rotation da zero."""

from __future__ import annotations

import argparse
import calendar
import sys
from datetime import date
from io import BytesIO
from pathlib import Path

DEFAULT_FORNITORI_CSV = Path(__file__).resolve().parents[3] / (
    "core/bq/dimensioni/d_fornitori.csv"
)

MESI_IT = {
    m.lower(): i
    for i, m in enumerate(
        [
            "gennaio",
            "febbraio",
            "marzo",
            "aprile",
            "maggio",
            "giugno",
            "luglio",
            "agosto",
            "settembre",
            "ottobre",
            "novembre",
            "dicembre",
        ],
        start=1,
    )
}


def _parse_mese(s: str) -> int:
    s = s.strip().lower()
    if s.isdigit():
        return int(s)
    if s not in MESI_IT:
        raise argparse.ArgumentTypeError(
            f"Mese non riconosciuto: '{s}'. Usa nome italiano o numero (1-12)."
        )
    return MESI_IT[s]


def build_parser(subparsers) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "pf-genera",
        help="Genera il PF post-rotation da zero (layout standard)",
    )
    p.add_argument(
        "--pf-prev",
        type=Path,
        required=True,
        help="PF precedente (fonte previsioni + entrate)",
    )
    p.add_argument(
        "--scad",
        type=Path,
        required=True,
        help="Export Esolver situazione partite fornitori",
    )
    p.add_argument("--societa", choices=("ORTI", "INTUR"), required=True)
    p.add_argument("--mese-chiuso", type=_parse_mese, required=True)
    p.add_argument(
        "--anno",
        type=int,
        default=None,
        help="Anno di riferimento. Default: anno corrente.",
    )
    p.add_argument(
        "--fornitori-csv",
        type=Path,
        default=DEFAULT_FORNITORI_CSV,
    )
    p.add_argument("--out", type=Path, default=Path("/tmp/pf-genera"))
    p.add_argument(
        "--mostra-previsioni",
        action="store_true",
        help="Stampa l'estrazione previsioni + entrate e esce (gate ispezione migrazione)",
    )
    p.set_defaults(func=_handle)
    return p


def _handle(args: argparse.Namespace) -> int:
    from verticals.condges.pf_generator.assemble import genera_pf
    from verticals.condges.pf_generator.previsioni import (
        estrai_entrate,
        estrai_previsioni,
    )
    from verticals.condges.pf_rotate.fornitori_map import load_fornitori
    from verticals.condges.scadenze_parse import parse_scadenze

    anno = args.anno or date.today().year
    mese_chiuso = args.mese_chiuso
    if mese_chiuso == 12:
        primo_aperto, anno_aperto = 1, anno + 1
    else:
        primo_aperto, anno_aperto = mese_chiuso + 1, anno

    with args.scad.open("rb") as f:
        scad_df, bucket_months = parse_scadenze(
            BytesIO(f.read()), primo_mese_aperto=(anno_aperto, primo_aperto)
        )
    pf_prev = args.pf_prev.read_bytes()

    if args.mostra_previsioni:
        codici = {int(c) for c in scad_df["codice_fornitore"]}
        estratto = estrai_previsioni(
            pf_prev, codici_partite=codici, primo_mese_aperto=primo_aperto
        )
        print("=== PREVISIONI per voce ===")
        for voce, righe in estratto.items():
            if not righe:
                continue
            print(f"\n{voce}:")
            for r in righe:
                mesi = {m: v for m, v in sorted(r["mesi"].items())}
                print(f"  {str(r['codice'] or ''):>5} {r['nome'][:36]:36} {mesi}")
        entrate = estrai_entrate(pf_prev, primo_mese_aperto=primo_aperto)
        print("\n=== ENTRATE estratte ===")
        for r in entrate:
            mesi = {m: v for m, v in sorted(r["mesi"].items())}
            print(f"  {r['nome'][:40]:40} {mesi}")
        return 0

    # --- saldo iniziale da BQ ---
    last_day = calendar.monthrange(anno, mese_chiuso)[1]
    data_saldo = date(anno, mese_chiuso, last_day)
    saldo_iniziale = 0.0
    try:
        from verticals.condges.pf_rotate.step1_saldi import fetch_saldi_da_bq

        saldi_dict = fetch_saldi_da_bq(args.societa, data_saldo)
        if saldi_dict:
            saldo_iniziale = sum(saldi_dict.values())
            print(
                f"Ancora saldo: {args.societa} al {data_saldo.isoformat()} "
                f"= {saldo_iniziale:,.2f} EUR "
                f"({len(saldi_dict)} banche: {', '.join(sorted(saldi_dict))})"
            )
        else:
            print(
                f"AVVISO: nessun saldo trovato in BQ per {args.societa} al "
                f"{data_saldo.isoformat()}. saldo_iniziale=0.0 (anchor da completare).",
                file=sys.stderr,
            )
    except Exception as exc:
        print(
            f"AVVISO: impossibile leggere saldi da BQ ({exc}). "
            "saldo_iniziale=0.0 (anchor da completare).",
            file=sys.stderr,
        )

    # --- entrate dal PF precedente ---
    entrate = estrai_entrate(pf_prev, primo_mese_aperto=primo_aperto)

    # --- fornitori ---
    fornitori_rows = load_fornitori(args.fornitori_csv, societa=args.societa)
    fornitori = {
        cod: {
            "voce_id": r.voce_id,
            "nome_pf": r.nome_pf,
            "is_excluded": r.is_excluded,
            "exclude_reason": r.exclude_reason,
        }
        for cod, r in fornitori_rows.items()
    }

    # --- genera ---
    out_bytes, report = genera_pf(
        pf_prev_bytes=pf_prev,
        scad_df=scad_df,
        bucket_months=bucket_months,
        fornitori=fornitori,
        societa=args.societa,
        anno=anno_aperto,
        primo_mese_aperto=primo_aperto,
        entrate=entrate,
        saldo_iniziale=saldo_iniziale,
    )

    args.out.mkdir(parents=True, exist_ok=True)
    ts = date.today().isoformat()
    nome = f"{args.societa}_PF_{anno_aperto}-{primo_aperto:02d}_generato_{ts}.xlsx"
    out_path = args.out / nome
    out_path.write_bytes(out_bytes)

    print(f"Output: {out_path}")
    print(
        f"Fornitori scritti: {report['fornitori_scritti']}"
        f" | voci: {len(report['voci'])}"
        f" | DA MAPPARE: {len(report['unmapped'])}"
        f" | ESCLUSI: {len(report['esclusi'])}"
    )
    print(f"saldo_iniziale usato: {saldo_iniziale:,.2f} EUR")
    for c in report["controlli"]:
        print(f"  [{c['esito']}] {c['check']} — {c['dettaglio']}")

    err = any(c["esito"] == "ERR" for c in report["controlli"])
    return 1 if err else 0
