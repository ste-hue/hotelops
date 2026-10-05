"""`hotelops budget base` — legge il 2026 da BigQuery e genera il foglio degli aumenti."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from verticals.condges.budget_camere import foglio, fonti, modello


def giorno(testo: str) -> tuple[int, int]:
    """'04-20' → (4, 20)."""
    d = datetime.strptime(f"2000-{testo}", "%Y-%m-%d")
    return d.month, d.day


def run(
    out_dir: Path,
    apertura: tuple[int, int] = modello.APERTURA_2027,
    chiusura: tuple[int, int] = modello.CHIUSURA_2027,
    anno_base: int = 2026,
    query=fonti._query,
    adesso: datetime | None = None,
) -> Path:
    adesso = adesso or datetime.now()
    dati = modello.costruisci(
        fonti.leggi_camere(query),
        fonti.leggi_categorie(anno_base, query),
        fonti.leggi_pms(anno_base, query),
        modello.carica_progetto(),
        anno_base,
        apertura,
        chiusura,
    )
    nome = f"budget_camere_HOTEL_{anno_base + 1}_base_{adesso:%Y%m%d-%H%M}.xlsx"
    path = foglio.scrivi(dati, Path(out_dir) / nome)

    print(
        f"\n  {'mese':<10}{'stato':<11}{'notti':>7}{'ricavo base':>13}{'effetto mix':>13}"
    )
    for x in dati["mesi"]:
        righe = [
            {
                "notti_base": r["notti_base"],
                "prezzo_base": r["prezzo_base"],
                "notti": r["notti_2027"],
                "prezzo": r["prezzo_base"],
            }
            for r in dati["righe"]
            if r["mese"] == x["mese"]
        ]
        e = modello.effetti(righe)
        notti = sum(r["notti_base"] for r in righe)
        print(
            f"  {foglio.MESI[x['mese']]:<10}{x['stato']:<11}{notti:>7}"
            f"{e['base']:>13,.0f}{e['mix']:>13,.0f}"
        )
    stime = [foglio.MESI[x["mese"]] for x in dati["mesi"] if x["stato"] == "stima"]
    if stime:
        print(
            f"\n  ⚠ {', '.join(stime)}: base = prenotazioni alla data dell'esportazione, "
            "sottostimata; totali n.d. finché non arriva l'esportazione nuova"
        )
    print(f"\n  ✓ {path}")
    return path
