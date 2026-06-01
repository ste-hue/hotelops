"""CLI handler per `hotelops pf-rotate`."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from verticals.condges.pf_rotate.rotate import rotate
from verticals.condges.pf_rotate.step3_scadenzario import UnmappedPolicy

MESI_IT = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}


def _parse_mese(s: str) -> int:
    s = s.strip().lower()
    if s in MESI_IT:
        return MESI_IT[s]
    return int(s)


def _parse_data(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _parse_banca_overrides(items: list[str]) -> dict[str, float]:
    out = {}
    for it in items or []:
        if "=" not in it:
            raise argparse.ArgumentTypeError(
                f"--banca atteso 'BANCA=IMPORTO', avuto '{it}'"
            )
        k, v = it.split("=", 1)
        out[k.strip()] = float(v)
    return out


def _default_policy() -> UnmappedPolicy:
    return UnmappedPolicy.INTERACTIVE if sys.stdin.isatty() else UnmappedPolicy.FAIL


def add_subparser(subparsers: argparse._SubParsersAction):
    _add_normalize_intur_subparser(subparsers)
    p = subparsers.add_parser(
        "pf-rotate", help="Rotation mensile del Piano Finanziario."
    )
    p.add_argument("--pf", type=Path, required=True)
    p.add_argument("--scad", type=Path, required=True)
    p.add_argument(
        "--scad-tipo",
        choices=("riepilogo", "partite", "sintetica"),
        default="sintetica",
    )
    p.add_argument("--societa", choices=("ORTI", "INTUR"), required=True)
    p.add_argument("--mese-chiuso", type=_parse_mese, required=True)
    p.add_argument("--data-saldo", type=_parse_data, required=True)
    p.add_argument(
        "--banca",
        action="append",
        default=[],
        help="Override saldo: BANCA=IMPORTO (ripetibile).",
    )
    p.add_argument(
        "--unmapped-policy",
        choices=tuple(p.value for p in UnmappedPolicy),
        default=None,
        help="Default: 'interactive' se TTY, altrimenti 'fail'.",
    )
    p.add_argument("--out", type=Path, default=Path.cwd() / "pianfin-out")
    p.add_argument(
        "--fornitori-csv", type=Path, default=Path("core/bq/dimensioni/d_fornitori.csv")
    )
    p.add_argument(
        "--allow-partial-saldi",
        action="store_true",
        help="Genera un PF parziale (marcato _FAILED_CHECKS) anche se mancano conti "
        "saldo obbligatori, invece di hard-fail.",
    )
    p.set_defaults(func=_handle)
    return p


def _handle(args: argparse.Namespace) -> int:
    from io import BytesIO

    from verticals.condges.pf_rotate.step1_saldi import SaldiIncompletiError
    from verticals.condges.scadenze_parse import parse_scadenze

    with args.scad.open("rb") as f:
        scad_df, bucket_months = parse_scadenze(BytesIO(f.read()))

    overrides = _parse_banca_overrides(args.banca)
    policy = (
        UnmappedPolicy(args.unmapped_policy)
        if args.unmapped_policy
        else _default_policy()
    )

    try:
        result = rotate(
            pf_path=args.pf,
            scad_df=scad_df,
            bucket_months=bucket_months,
            societa=args.societa,
            mese_chiuso=args.mese_chiuso,
            data_saldo=args.data_saldo,
            saldi=overrides or None,
            fornitori_csv=args.fornitori_csv,
            out_dir=args.out,
            unmapped_policy=policy,
            allow_partial_saldi=args.allow_partial_saldi,
        )
    except SaldiIncompletiError as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        return 2

    print(f"Output: {result.out_path}")
    print(
        f"Controlli: OK={result.n_controlli_ok}  ERR={result.n_controlli_err}  INDET={result.n_controlli_indet}"
    )
    if result.failed_checks:
        print("\nFailed checks:")
        for c in result.failed_checks:
            print(f"  - {c}")
    if result.scadenzario_summary:
        print(
            f"\nFornitori scritti: {result.scadenzario_summary['totale_fornitori_scritti']}"
        )
    return 1 if result.failed else 0


def _add_normalize_intur_subparser(subparsers: argparse._SubParsersAction):
    p = subparsers.add_parser(
        "pf-normalize-intur",
        help="Normalizza col A dei fogli dettaglio INTUR (step 0, una tantum).",
    )
    p.add_argument("--pf", type=Path, required=True)
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Default: <pf>.normalized.xlsx accanto al file di input.",
    )
    p.add_argument(
        "--fornitori-csv",
        type=Path,
        default=Path("core/bq/dimensioni/d_fornitori.csv"),
    )
    p.set_defaults(func=_handle_normalize_intur)
    return p


def _handle_normalize_intur(args: argparse.Namespace) -> int:
    from verticals.condges.pf_rotate.step0_normalize_intur import normalize_intur

    pf_bytes = args.pf.read_bytes()
    out_bytes, overwrites, unmapped = normalize_intur(
        pf_bytes=pf_bytes, fornitori_csv=args.fornitori_csv
    )

    out_path = args.out or args.pf.with_suffix(".normalized.xlsx")
    out_path.write_bytes(out_bytes)

    print(f"Output: {out_path}")
    print(f"Col A overwrites: {len(overwrites)}")
    print(f"Fornitori non mappati (col A lasciata invariata): {len(unmapped)}")
    if unmapped:
        print("\nNon mappati (primi 20):")
        for u in unmapped[:20]:
            print(f"  - {u['foglio']!r:30s} r{u['riga']:<4d}  {u['nome_b']!r}")
        if len(unmapped) > 20:
            print(f"  ... e altri {len(unmapped) - 20}")
    return 0
