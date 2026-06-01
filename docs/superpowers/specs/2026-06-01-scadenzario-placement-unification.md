# Scadenzario placement — unification (DRY)

**Data:** 2026-06-01 · **Branch:** feat/cashflow · **Decisione:** Stefano ("unifichiamo, no redundancy, DRY")
**Lane:** design (questo doc) → exec (orange: codice app + pf_rotate). Sibling del saldi ledger.

## Problema — doppio motore di piazzamento

Oggi esistono **due implementazioni di `write_pf`** che piazzano i fornitori dello scadenzario nei fogli-dettaglio del PF:

| | CLI `pf-rotate` | Streamlit `app_scadenzario.py` |
|---|---|---|
| Writer | `pf_rotate` `write_pf` (via `step3.apply_scadenzario`) | **proprio** `write_pf` (`app_scadenzario.py:263`) |
| Layout-aware | sì (`find_layout`, ORTI month-closed + INTUR fixed-snapshot) | **no** — euristiche `_find_supplier_row_by_*`, tarato ORTI |
| Hardening | gate O-A, match esatto, 51/51 test | pre-refactor, non testato a quel livello |
| Esclusione | `write_pf(excluded=set)` | `write_pf(excluded=set)` — **stesso hook** |
| Step saldi/azzera/controlli | step1/2/5 | **importa gli stessi** step1/2/5 |

Quindi la duplicazione è **stretta**: saldi/azzera/controlli sono già condivisi; diverge **solo il piazzamento**. E il pezzo duplicato dell'app è il più vecchio/rischioso (non layout-aware → INTUR a rischio).

## Decisione

**L'app delega il piazzamento a `step3`. Si cancella `app_scadenzario.py:write_pf`.** L'app resta:
- la **UI** (checkbox esclusione + totale live) — il valore che Stefano vuole conservare;
- gli **step condivisi** (saldi/azzera/controlli, già importati);
- calcola `excluded_set` dalle checkbox e lo passa a `step3.apply_scadenzario(..., excluded=excluded_set)`.

Risultato: **una UI visiva per l'esclusione + un unico motore di piazzamento** (quello indurito, layout-aware). Niente più `app.write_pf` da mantenere.

## Validation points (prima di cancellare il vecchio writer)

Tenere `app.write_pf` finché questi non passano (poi switch + delete):

1. **Diff su file ORTI reale:** `step3` write vs `app.write_pf` write sullo stesso PF+scadenzario → stesse celle (codice col A, nome col B, valori mensili, riga previsionale ricalcolata). Diff atteso vuoto. *(`step3` ricalcola la previsionale via formule strutturali, l'app a mano — è IL punto da validare.)*
2. **Esclusione:** fornitori esclusi assenti dal PF scritto + previsionale ricalcolata coerente.
3. **INTUR fixed-snapshot:** è il payoff — `step3` lo gestisce (layout-aware), `app.write_pf` quasi certamente no. Dopo l'unificazione l'app produce INTUR corretto, oggi non garantito.

## Redundancy secondarie (DRY — stesso giro, opzionali)

Mentre si tocca il piazzamento, valutare di unificare anche:
- **fornitori→voce loader:** `scadenzario_excel.load_fornitori_map` + `app.load_fornitori_map` vs `fornitori_map.load_fornitori` (3 letture di `d_fornitori`).
- **row-finding:** `app._find_supplier_row_by_{name,codice}` vs l'equivalente in `step3`/`fornitori_map`.

Non bloccanti per la decisione principale (il `write_pf`); de-dup incrementale.

## Rischio / rollback

Switch dietro i 3 validation points. `app.write_pf` resta in git history; se il diff diverge su un caso, si analizza prima di cancellare. Nessun rischio sui PF già generati (sono su disco).
