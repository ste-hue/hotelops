"""Quadratura al centesimo di un file PF prima del carico (procedura C6).

Per ogni colonna-mese del foglio master «Piano Finanziario» confronta la somma delle voci
parsate dal loader (`parse_piano_finanziario`, le stesse righe del master) con le righe
TOTALE ENTRATE e TOTALE USCITE scritte nel foglio, e segnala le righe con importi che il
loader non mappa o che stanno nel blocco sbagliato.

Cosa NON guarda, per costruzione: legge SOLO il master con i valori in cache (`data_only`)
e confronta i totali per colonna-mese; i totali di riga dei fogli di dettaglio (colonna C,
`=SUM(D3:Y3)`) le sono invisibili, perché il master punta ai mesi dei dettagli e non a C.
Un file senza valori in cache quadra a zero contro zero: il controllo dei valori in cache
(C1) viene prima. È uno strumento lanciato a mano: nessun passo automatico lo invoca.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

from ingest.flussi.ingest_piano_finanziario_xlsx import (
    _detect_year_and_month_block,
    _match_voce,
    _v,
    parse_piano_finanziario,
)

_LOG = logging.getLogger("pf_quadratura")
_LOG.addHandler(logging.NullHandler())


def quadratura(path: str | Path) -> dict:
    """Esito per un file: righe parsate, mesi, totali, differenze per mese, anomalie."""
    f = Path(path)
    rows = parse_piano_finanziario(f, None, _LOG)
    wb = openpyxl.load_workbook(str(f), read_only=True, data_only=True)
    ws = wb["Piano Finanziario"]
    cols = _detect_year_and_month_block(ws)
    tot: dict[str, dict] = {"ENTRATE": {}, "USCITE": {}}
    blocco, anomalie = None, []
    for r in range(4, 35):
        lab = ws.cell(r, 1).value
        if not isinstance(lab, str):
            continue
        testa = lab.strip().upper()
        if any(k in testa for k in ("SALDO", "CASH FLOW", "====")):
            continue  # come il parser
        if testa.startswith("TOTALE ENTRATE"):
            tot["ENTRATE"] = {
                (a, m): round(_v(ws.cell(r, c).value), 2) for c, a, m in cols
            }
            blocco = "USCITE"
            continue
        if testa.startswith("TOTALE USCITE"):
            tot["USCITE"] = {
                (a, m): round(_v(ws.cell(r, c).value), 2) for c, a, m in cols
            }
            blocco = None
            continue
        if blocco is None and not tot["ENTRATE"]:
            blocco = "ENTRATE"
        v = _match_voce(lab.strip())
        has = any(_v(ws.cell(r, c).value) != 0 for c, _, _ in cols)
        if blocco and has:
            if v is None:
                anomalie.append(f"r{r} '{lab.strip()}' NON MAPPATA in blocco {blocco}")
            elif not v.startswith(blocco):
                anomalie.append(f"r{r} '{lab.strip()}'→{v} ma sta nel blocco {blocco}")
    par: dict[str, dict] = {"ENTRATE": defaultdict(float), "USCITE": defaultdict(float)}
    for x in rows:
        par[x["voce_id"].split("_")[0]][(x["anno"], x["mese"])] += x["importo"]
    diffs = []
    for sez in ("ENTRATE", "USCITE"):
        for k in sorted(set(tot[sez]) | set(par[sez])):
            d = round(par[sez].get(k, 0) - tot[sez].get(k, 0), 2)
            if abs(d) >= 0.01:
                diffs.append(
                    (
                        sez,
                        f"{k[0]}-{k[1]:02d}",
                        round(par[sez].get(k, 0), 2),
                        tot[sez].get(k, 0),
                        d,
                    )
                )
    mesi = [f"{a}-{m:02d}" for _, a, m in cols]
    return {
        "file": f.name,
        "righe": len(rows),
        "mesi": mesi,
        "tot_entrate": round(sum(tot["ENTRATE"].values()), 2),
        "tot_uscite": round(sum(tot["USCITE"].values()), 2),
        "par_entrate": round(sum(par["ENTRATE"].values()), 2),
        "par_uscite": round(sum(par["USCITE"].values()), 2),
        "diff_mesi": diffs,
        "anomalie": anomalie,
        "ok": not diffs and not anomalie,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Quadratura al centesimo dei PF (C6): voci parsate vs TOTALE del master."
    )
    ap.add_argument(
        "percorsi",
        nargs="+",
        type=Path,
        help="file .xlsx o cartelle (tutti gli .xlsx dentro)",
    )
    args = ap.parse_args(argv)
    files = sorted(
        p for x in args.percorsi for p in (x.glob("*.xlsx") if x.is_dir() else [x])
    )
    tutto_ok = True
    for f in files:
        o = quadratura(f)
        tutto_ok = tutto_ok and o["ok"]
        flag = "OK" if o["ok"] else "DIFF"
        print(
            f"{flag:4} {o['file']:<40} {o['righe']:>4} righe  {o['mesi'][0]}→{o['mesi'][-1]} ({len(o['mesi'])})  E {o['par_entrate']:>14,.2f} / {o['tot_entrate']:>14,.2f}   U {o['par_uscite']:>14,.2f} / {o['tot_uscite']:>14,.2f}"
        )
        for a in o["anomalie"]:
            print("       !", a)
        for sez, m, p, t, d in o["diff_mesi"]:
            print(
                f"       Δ {sez:<7} {m}  parsato {p:>12,.2f}  foglio {t:>12,.2f}  diff {d:>+12,.2f}"
            )
    return 0 if tutto_ok else 1


if __name__ == "__main__":
    sys.exit(main())
