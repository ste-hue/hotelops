"""Validazione semantica: candidato pf-genera vs ground truth (Rosa).

Risponde alla domanda di Stefano: il file generato è semanticamente
uguale-o-migliore del file corretto a mano da Rosa?

PITFALL CRITICO: le celle TOTALE del candidato sono FORMULE scritte da
openpyxl e MAI aperte in Excel → ``data_only=True`` ritorna None per esse.
Quindi NON leggiamo i risultati delle formule: ricalcoliamo i totali
per-voce/per-mese sommando i valori delle righe-fornitore grezze su ENTRAMBI
i file.

Confronto a due livelli:
  1. Per voce/foglio × mese: totale candidato vs Rosa, delta.
  2. Per fornitore/codice × mese: match per codice (fallback nome normalizzato).

Ogni differenza per-fornitore è classificata (vedi Task 9 del piano).
"""

from __future__ import annotations

import re
from io import BytesIO

import openpyxl

from verticals.condges.pf_rotate.pf_writer import _build_month_col_map
from verticals.condges.pf_generator.costanti import MESI, VOCE_SHEET_NAME

# --- soglie ---
TOLL = 0.01  # tolleranza di confronto importi (centesimi)
SOGLIA_DOPPIO = 0.02  # tolleranza relativa per riconoscere il 2x

# Label di col B che NON sono righe-fornitore (header, sezioni, totali).
_LABEL_NON_FORNITORE = (
    "totale",
    "saldo",
    "previsionale",
    "partite aperte",
    "previsioni",
    "cod",
    "fornitore / voce",
    "entrate",
    "uscite",
)
# La riga RETTIFICA va INCLUSA nel totale (parte della proiezione) ma NON
# trattata come fornitore confrontabile.
_LABEL_RETTIFICA = "rettifica"


def _norm_nome(s: str) -> str:
    """Nome normalizzato: minuscolo, whitespace collassato."""
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _is_formula_costanti(s: str) -> bool:
    """True se è una formula di sole costanti (=131.81+121.08), senza ref A1."""
    if not isinstance(s, str) or not s.startswith("="):
        return False
    # un riferimento di cella ha una lettera seguita da una cifra (A1, SUM(D5..))
    return re.search(r"[A-Za-z]+\d", s) is None


def _val_cella(v):
    """Valore numerico di una cella; valuta formule di sole costanti.

    Ritorna None se non interpretabile come numero (formule con ref, testo).
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        if _is_formula_costanti(s):
            try:
                return float(eval(s[1:], {"__builtins__": {}}, {}))  # noqa: S307
            except Exception:
                return None
        # numero scritto come stringa
        try:
            return float(s.replace(",", "."))
        except ValueError:
            return None
    return None


def _is_riga_fornitore(label, *, etichette_totale: set[str] = frozenset()) -> bool:
    if label is None:
        return False
    low = _norm_nome(label)
    if not low:
        return False
    if _LABEL_RETTIFICA in low:
        return False
    # riga-totale-di-voce: in entrambi i layout l'aggregato è etichettato col
    # nome stesso della voce (es. "Utenze", "Salari e Stipendi"). Va esclusa,
    # altrimenti somma genitore + figli = doppio conteggio. Match fuzzy per
    # assorbire i typo nel file di Rosa ("Gofimento", "Variee", "Commisisoni").
    if low in etichette_totale:
        return False
    if any(_nomi_simili(low, et) for et in etichette_totale):
        return False
    return all(tok not in low for tok in _LABEL_NON_FORNITORE)


def _is_riga_rettifica(label) -> bool:
    return label is not None and _LABEL_RETTIFICA in _norm_nome(label)


def _match_voce_sheet(nome_foglio: str) -> str | None:
    """Mappa un nome foglio (anche con typo/spazi) a un voce_id uscita.

    Confronto fuzzy: normalizza e cerca match esatto, poi per prefisso comune.
    """
    target = _norm_nome(nome_foglio)
    norm_map = {_norm_nome(v): vid for vid, v in VOCE_SHEET_NAME.items()}
    if target in norm_map:
        return norm_map[target]
    # fuzzy: confronta sui caratteri alfanumerici, prendi best overlap di token
    tgt_tok = set(re.findall(r"[a-z]+", target))
    best, best_score = None, 0
    for nv, vid in norm_map.items():
        nv_tok = set(re.findall(r"[a-z]+", nv))
        if not nv_tok:
            continue
        inter = len(tgt_tok & nv_tok)
        score = inter / max(len(nv_tok), 1)
        if inter >= 1 and score > best_score:
            best, best_score = vid, score
    # richiedi un overlap forte (>=0.5) per evitare match casuali
    return best if best_score >= 0.5 else None


def _leggi_foglio_voce(ws, primo_mese_aperto: int, voce_nome: str) -> dict:
    """Estrae righe-fornitore + rettifica da un foglio voce.

    Ritorna {
      'fornitori': [ {codice:int|None, nome:str, mesi:{m:val}} ],
      'rettifica': {m: val},
      'totali_mese': {m: somma (fornitori + rettifica)},
    }
    ``voce_nome``: nome canonico della voce; usato per riconoscere ed escludere
    la riga-totale aggregata (etichettata col nome della voce).
    """
    month_col = _build_month_col_map(ws)
    aperti = [m for m in month_col if m >= primo_mese_aperto]
    fornitori: list[dict] = []
    rettifica: dict[int, float] = {}
    totali: dict[int, float] = {m: 0.0 for m in aperti}
    # etichette che identificano la riga-totale: nome canonico + titolo r1 del
    # foglio (gestisce typo/spazi nel file di Rosa, es. "Utenze", "Gofimento...")
    etichette_totale = {_norm_nome(voce_nome)}
    titolo_r1 = ws.cell(row=1, column=2).value
    if titolo_r1:
        etichette_totale.add(_norm_nome(titolo_r1))

    for r in range(3, ws.max_row + 1):
        label = ws.cell(row=r, column=2).value
        cod_raw = ws.cell(row=r, column=1).value
        if _is_riga_rettifica(label):
            for m in aperti:
                v = _val_cella(ws.cell(row=r, column=month_col[m]).value)
                if v is not None:
                    rettifica[m] = rettifica.get(m, 0.0) + v
                    totali[m] += v
            continue
        if not _is_riga_fornitore(label, etichette_totale=etichette_totale):
            continue
        mesi: dict[int, float] = {}
        for m in aperti:
            v = _val_cella(ws.cell(row=r, column=month_col[m]).value)
            if v is not None and abs(v) > TOLL:
                mesi[m] = v
                totali[m] += v
        codice = None
        if cod_raw is not None:
            try:
                codice = int(float(cod_raw))
            except (ValueError, TypeError):
                codice = None
        if mesi or codice is not None:
            fornitori.append({"codice": codice, "nome": str(label), "mesi": mesi})
    return {"fornitori": fornitori, "rettifica": rettifica, "totali_mese": totali}


def _carica_voci(wb_bytes: bytes, primo_mese_aperto: int) -> dict[str, dict]:
    """Carica tutti i fogli voce-uscita di un workbook → {voce_id: dati_foglio}."""
    wb = openpyxl.load_workbook(BytesIO(wb_bytes), data_only=False)
    out: dict[str, dict] = {}
    for nome_foglio in wb.sheetnames:
        voce_id = _match_voce_sheet(nome_foglio)
        if voce_id is None:
            continue
        ws = wb[nome_foglio]
        dati = _leggi_foglio_voce(
            ws, primo_mese_aperto, VOCE_SHEET_NAME.get(voce_id, nome_foglio)
        )
        dati["nome_foglio"] = nome_foglio
        out[voce_id] = dati
    return out


def _indice_fornitori(dati: dict) -> tuple[dict[int, dict], dict[str, dict]]:
    """Indici per codice e per nome normalizzato."""
    by_cod: dict[int, dict] = {}
    by_nome: dict[str, dict] = {}
    for f in dati["fornitori"]:
        if f["codice"] is not None:
            by_cod[f["codice"]] = f
        by_nome[_norm_nome(f["nome"])] = f
    return by_cod, by_nome


def _tot_fornitore(f: dict, mesi_aperti: list[int]) -> float:
    return sum(f["mesi"].get(m, 0.0) for m in mesi_aperti)


def confronta_pf(
    candidato_bytes: bytes,
    ground_truth_bytes: bytes,
    *,
    primo_mese_aperto: int,
    scad_codici: set[int] | None = None,
) -> dict:
    """Confronta candidato vs ground truth. Ritorna report classificato."""
    scad_codici = scad_codici or set()
    cand = _carica_voci(candidato_bytes, primo_mese_aperto)
    rosa = _carica_voci(ground_truth_bytes, primo_mese_aperto)

    voci_tutte = sorted(set(cand) | set(rosa))
    mesi_aperti = list(range(primo_mese_aperto, 13))

    errori: list[dict] = []
    attese: list[dict] = []
    da_chiarire: list[dict] = []
    quadrature: dict[int, dict] = {}

    # --- quadrature per mese (totale uscite candidato vs Rosa) ---
    for m in mesi_aperti:
        tc = sum(cand[v]["totali_mese"].get(m, 0.0) for v in cand)
        tr = sum(rosa[v]["totali_mese"].get(m, 0.0) for v in rosa)
        if abs(tc) > TOLL or abs(tr) > TOLL:
            quadrature[m] = {
                "candidato": round(tc, 2),
                "rosa": round(tr, 2),
                "delta": round(tc - tr, 2),
            }

    # --- mappa fornitore → voce_id per rilevare RIMAPPATURA ---
    voce_di_cod_cand = _voce_per_codice(cand)

    # --- confronto per fornitore × mese ---
    for voce_id in voci_tutte:
        c = cand.get(voce_id, {"fornitori": [], "rettifica": {}})
        r = rosa.get(voce_id, {"fornitori": [], "rettifica": {}})
        voce_nome = VOCE_SHEET_NAME.get(voce_id, voce_id)

        # RETTIFICA: presente nel candidato per qualche mese → attesa
        for m, val in c.get("rettifica", {}).items():
            if abs(val) > TOLL:
                attese.append(
                    {
                        "classe": "RETTIFICA",
                        "voce": voce_nome,
                        "fornitore": "RETTIFICA PARTITE/PREVISIONI",
                        "mese": m,
                        "dettaglio": f"{round(val, 2)} (anti-doppio-conteggio)",
                    }
                )

        c_cod, c_nome = _indice_fornitori(c)
        r_cod, r_nome = _indice_fornitori(r)

        codici_visti: set[int] = set()
        nomi_visti: set[str] = set()

        # fornitori presenti in Rosa
        for f_rosa in r["fornitori"]:
            f_cand = _trova_match(f_rosa, c_cod, c_nome)
            cod = f_rosa["codice"]
            if cod is not None:
                codici_visti.add(cod)
            nomi_visti.add(_norm_nome(f_rosa["nome"]))

            if f_cand is None:
                _classifica_solo_rosa(
                    f_rosa,
                    voce_nome,
                    voce_id,
                    mesi_aperti,
                    scad_codici,
                    voce_di_cod_cand,
                    errori,
                    attese,
                )
                continue

            _classifica_match(
                f_cand, f_rosa, voce_nome, mesi_aperti, errori, attese, da_chiarire
            )

        # fornitori presenti solo nel candidato (non già visti via Rosa)
        for f_cand in c["fornitori"]:
            cod = f_cand["codice"]
            nome_n = _norm_nome(f_cand["nome"])
            if cod is not None and cod in codici_visti:
                continue
            if cod is None and nome_n in nomi_visti:
                continue
            # match per nome con Rosa? (cod None)
            if _trova_match(f_cand, r_cod, r_nome) is not None:
                continue
            tot = _tot_fornitore(f_cand, mesi_aperti)
            if abs(tot) <= TOLL:
                continue
            attese.append(
                {
                    "classe": "SOLO_CANDIDATO_STRUTTURA",
                    "voce": voce_nome,
                    "fornitore": f_cand["nome"],
                    "dettaglio": f"presente solo nel candidato, tot {round(tot, 2)}",
                }
            )

    verdetto = _verdetto(errori, attese, da_chiarire, quadrature)
    return {
        "verdetto": verdetto,
        "errori": errori,
        "attese": attese,
        "da_chiarire": da_chiarire,
        "quadrature": quadrature,
    }


def _voce_per_codice(voci: dict[str, dict]) -> dict[int, str]:
    out: dict[int, str] = {}
    for voce_id, dati in voci.items():
        for f in dati["fornitori"]:
            if f["codice"] is not None:
                out[f["codice"]] = voce_id
    return out


def _trova_match(f, by_cod: dict[int, dict], by_nome: dict[str, dict]):
    """Match per codice, fallback per nome normalizzato."""
    if f["codice"] is not None and f["codice"] in by_cod:
        return by_cod[f["codice"]]
    return by_nome.get(_norm_nome(f["nome"]))


def _classifica_solo_rosa(
    f_rosa,
    voce_nome,
    voce_id,
    mesi_aperti,
    scad_codici,
    voce_di_cod_cand,
    errori,
    attese,
):
    """Fornitore in Rosa, assente dal candidato."""
    cod = f_rosa["codice"]
    tot = _tot_fornitore(f_rosa, mesi_aperti)
    if abs(tot) <= TOLL:
        return  # riga vuota in Rosa, irrilevante

    # RIMAPPATURA: il codice esiste nel candidato ma in un'altra voce
    if cod is not None and cod in voce_di_cod_cand and voce_di_cod_cand[cod] != voce_id:
        altra = VOCE_SHEET_NAME.get(voce_di_cod_cand[cod], voce_di_cod_cand[cod])
        attese.append(
            {
                "classe": "RIMAPPATURA",
                "voce": voce_nome,
                "fornitore": f_rosa["nome"],
                "dettaglio": f"nel candidato è in '{altra}'",
            }
        )
        return

    if cod is not None and cod in scad_codici:
        # aveva partita aperta nell'export ma manca nel candidato → errore
        errori.append(
            {
                "classe": "PARTITA_PERSA",
                "voce": voce_nome,
                "fornitore": f_rosa["nome"],
                "dettaglio": (
                    f"cod {cod} con partita aperta, in Rosa tot {round(tot, 2)}, "
                    "assente dal candidato"
                ),
            }
        )
    else:
        # nessuna partita aperta → previsione manuale aggiunta da Rosa, attesa
        mesi_str = ", ".join(
            f"{m}={round(v, 2)}" for m, v in sorted(f_rosa["mesi"].items())
        )
        attese.append(
            {
                "classe": "PREVISIONE_AGGIUNTA_DA_ROSA",
                "voce": voce_nome,
                "fornitore": f_rosa["nome"],
                "dettaglio": f"non in aprile/export ({mesi_str})",
            }
        )


def _classifica_match(
    f_cand, f_rosa, voce_nome, mesi_aperti, errori, attese, da_chiarire
):
    """Fornitore presente in entrambi: confronta importi e distribuzione."""
    tot_c = _tot_fornitore(f_cand, mesi_aperti)
    tot_r = _tot_fornitore(f_rosa, mesi_aperti)

    # FORNITORE_SBAGLIATO: stesso codice, nome materialmente diverso
    if (
        f_cand["codice"] is not None
        and f_cand["codice"] == f_rosa["codice"]
        and not _nomi_simili(f_cand["nome"], f_rosa["nome"])
    ):
        errori.append(
            {
                "classe": "FORNITORE_SBAGLIATO",
                "voce": voce_nome,
                "fornitore": f"cod {f_cand['codice']}",
                "dettaglio": (
                    f"candidato '{f_cand['nome']}' vs Rosa '{f_rosa['nome']}'"
                ),
            }
        )
        return

    # importi per mese identici? → nessuna differenza
    diff_mesi = [
        m
        for m in mesi_aperti
        if abs(f_cand["mesi"].get(m, 0.0) - f_rosa["mesi"].get(m, 0.0)) > TOLL
    ]
    if not diff_mesi:
        return

    # DOPPIO_CONTEGGIO: candidato ≈ 2× Rosa (candidato sbagliato) →
    # oppure Rosa ≈ 2× candidato (Rosa sbagliata, candidato corretto → attesa MIGLIORE)
    if abs(tot_r) > TOLL and abs(tot_c - 2 * tot_r) <= max(
        TOLL, SOGLIA_DOPPIO * abs(tot_r)
    ):
        errori.append(
            {
                "classe": "DOPPIO_CONTEGGIO",
                "voce": voce_nome,
                "fornitore": f_rosa["nome"],
                "dettaglio": f"candidato {round(tot_c, 2)} ≈ 2× Rosa {round(tot_r, 2)}",
            }
        )
        return
    if abs(tot_c) > TOLL and abs(tot_r - 2 * tot_c) <= max(
        TOLL, SOGLIA_DOPPIO * abs(tot_c)
    ):
        attese.append(
            {
                "classe": "DOPPIO_CONTEGGIO",
                "voce": voce_nome,
                "fornitore": f_rosa["nome"],
                "dettaglio": (
                    f"Rosa {round(tot_r, 2)} ≈ 2× candidato {round(tot_c, 2)} "
                    "(doppione di Rosa, candidato corretto)"
                ),
            }
        )
        return

    # IMPORTO_SPOSTATO: stesso totale, distribuito su mesi diversi
    if abs(tot_c - tot_r) <= TOLL:
        det = ", ".join(
            f"m{m}: cand={round(f_cand['mesi'].get(m, 0.0), 2)} "
            f"rosa={round(f_rosa['mesi'].get(m, 0.0), 2)}"
            for m in diff_mesi
        )
        errori.append(
            {
                "classe": "IMPORTO_SPOSTATO",
                "voce": voce_nome,
                "fornitore": f_rosa["nome"],
                "dettaglio": f"stesso tot {round(tot_c, 2)}, mesi diversi — {det}",
            }
        )
        return

    # differenza di importo che non rientra negli schemi → da chiarire
    det = ", ".join(
        f"m{m}: cand={round(f_cand['mesi'].get(m, 0.0), 2)} "
        f"rosa={round(f_rosa['mesi'].get(m, 0.0), 2)}"
        for m in diff_mesi
    )
    da_chiarire.append(
        {
            "classe": "DIVERSO_DA_CHIARIRE",
            "voce": voce_nome,
            "fornitore": f_rosa["nome"],
            "dettaglio": f"tot cand={round(tot_c, 2)} rosa={round(tot_r, 2)} — {det}",
        }
    )


def _nomi_simili(a: str, b: str) -> bool:
    """True se due nomi sono lo stesso fornitore (token overlap, non solo format)."""
    ta = set(re.findall(r"[a-z0-9]+", _norm_nome(a)))
    tb = set(re.findall(r"[a-z0-9]+", _norm_nome(b)))
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    return inter / min(len(ta), len(tb)) >= 0.5


def _verdetto(errori, attese, da_chiarire, quadrature) -> str:
    if errori:
        return "PEGGIORE"
    # MIGLIORE se ci sono differenze che sono errori di Rosa corretti dal motore
    migliorie = {"DOPPIO_CONTEGGIO", "FORNITORE_SBAGLIATO"}
    if any(a["classe"] in migliorie for a in attese):
        return "MIGLIORE"
    # solo strutturale (rettifica, solo-candidato, rimappatura, previsioni aggiunte)?
    diff_non_strutturali = da_chiarire
    if not diff_non_strutturali and not attese:
        return "UGUALE"
    if diff_non_strutturali:
        return "DA_RIVEDERE"
    # solo differenze attese (no errori, no da_chiarire) → uguale-o-meglio = UGUALE
    return "UGUALE"


def scrivi_report(report: dict) -> str:
    """Report markdown leggibile (struttura del piano Task 9)."""
    out: list[str] = []
    out.append("## Validazione ORTI maggio — candidato vs Rosa")
    out.append(f"Verdetto: **{report['verdetto']}**")
    out.append("")

    errori = report["errori"]
    out.append(f"### Errori ({len(errori)}) — da risolvere prima del cutover")
    if not errori:
        out.append("- (nessuno)")
    for e in errori:
        out.append(
            f"- [{e['classe']}] {e['voce']} — {e['fornitore']}: {e['dettaglio']}"
        )
    out.append("")

    attese = report["attese"]
    out.append(f"### Differenze attese ({len(attese)})")
    if not attese:
        out.append("- (nessuna)")
    for a in attese:
        out.append(
            f"- [{a['classe']}] {a['voce']} — {a['fornitore']}: {a['dettaglio']}"
        )
    out.append("")

    dac = report["da_chiarire"]
    if dac:
        out.append(f"### Da chiarire ({len(dac)}) — lettura umana richiesta")
        for d in dac:
            out.append(
                f"- [{d['classe']}] {d['voce']} — {d['fornitore']}: {d['dettaglio']}"
            )
        out.append("")

    out.append("### Quadrature")
    if not report["quadrature"]:
        out.append("- (nessun mese aperto con importi)")
    for m in sorted(report["quadrature"]):
        q = report["quadrature"][m]
        nome = MESI[m - 1].capitalize()
        out.append(
            f"- {nome}: candidato={q['candidato']:,.2f} "
            f"Rosa={q['rosa']:,.2f} Δ={q['delta']:,.2f}"
        )
    out.append("")
    return "\n".join(out)
