"""Blocco A (partite aperte) e regole numeriche del generatore PF."""

from __future__ import annotations

import pandas as pd


def cascata_nc(amounts: dict[int, float]) -> dict[int, float]:
    """Scala i saldi positivi (note credito) sul primo mese con fatture
    in avanti. Input/output: {mese: importo} con debiti NEGATIVI.
    Una NC residua oltre l'ultimo mese viene scartata.
    """
    out: dict[int, float] = {}
    carry = 0.0
    for mese in sorted(amounts):
        net = amounts[mese] + carry
        if net >= 0:
            carry = net
            continue
        carry = 0.0
        out[mese] = round(net, 2)
    return out


def blocco_a_per_voce(
    scad_df: pd.DataFrame,
    bucket_months: list[int],
    fornitori: dict[int, dict],
    *,
    primo_mese_aperto: int,
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Partite aperte raggruppate per voce: righe pronte per il foglio.

    Ritorna (per_voce, unmapped). Riga = {codice, nome, mesi: {mese: importo
    POSITIVO}}. scaduto -> primo_mese_aperto; cascata NC applicata; nome dal
    CSV (authority), MAI dall'export. Gli unmapped NON si perdono: vanno nel
    foglio DA MAPPARE (nome dall'export, è l'unico che abbiamo).
    """
    per_voce: dict[str, list[dict]] = {}
    unmapped: list[dict] = []
    for _, row in scad_df.iterrows():
        codice = int(row["codice_fornitore"])
        amounts: dict[int, float] = {}
        raw_scad = row.get("scaduto", 0)
        scaduto = 0.0 if pd.isna(raw_scad) else float(raw_scad)
        if scaduto:
            amounts[primo_mese_aperto] = amounts.get(primo_mese_aperto, 0.0) + scaduto
        for m in bucket_months:
            raw_val = row.get(f"mese_{m}", 0)
            val = 0.0 if pd.isna(raw_val) else float(raw_val)
            if val:
                amounts[m] = amounts.get(m, 0.0) + val
        netted = cascata_nc(amounts)
        if not netted:
            continue
        mesi = {m: round(abs(v), 2) for m, v in netted.items()}
        info = fornitori.get(codice)
        if info is None:
            unmapped.append({"codice": codice, "nome": str(row["nome"]), "mesi": mesi})
            continue
        per_voce.setdefault(info["voce_id"], []).append(
            {
                "codice": codice,
                "nome": info["nome_pf"] or str(row["nome"]),
                "mesi": mesi,
            }
        )
    for righe in per_voce.values():
        righe.sort(key=lambda r: (r["nome"].lower(), r["codice"]))
    return per_voce, unmapped


def _chiave_norm(nome: str) -> str:
    return " ".join(str(nome).lower().split())


def rettifica_doppio_conteggio(
    blocco_a: list[dict], blocco_b: list[dict]
) -> dict[int, float]:
    """Riga RETTIFICA: per ogni fornitore presente in entrambi i blocchi
    (match per codice, fallback nome normalizzato) e per ogni mese,
    -min(previsione, partite). Implementa prev_eff = max(0, prev - partite)
    senza toccare le celle previsione originali (spec, nota di design).
    """
    a_per_codice: dict[int, dict[int, float]] = {}
    a_per_nome: dict[str, dict[int, float]] = {}
    for r in blocco_a:
        a_per_codice[r["codice"]] = r["mesi"]
        a_per_nome[_chiave_norm(r["nome"])] = r["mesi"]

    rett: dict[int, float] = {}
    for r in blocco_b:
        mesi_a = None
        if r.get("codice") is not None:
            mesi_a = a_per_codice.get(int(r["codice"]))
        if mesi_a is None:
            mesi_a = a_per_nome.get(_chiave_norm(r["nome"]))
        if not mesi_a:
            continue
        for mese, prev in r["mesi"].items():
            partite = mesi_a.get(mese, 0.0)
            taglio = min(float(prev), float(partite))
            if taglio > 0:
                rett[mese] = round(rett.get(mese, 0.0) - taglio, 2)
    return rett
