# Brief — F&B Looker close-out

> **Branch:** `feat/fb-looker-close` · **Base:** `main` · **Tipo:** coda/polish, non feature.
> **Stato in ingresso:** F&B è ~90% shipped. `v_fb_kpi` v3 (3 bucket onesti) + esclusione 9 articoli UoM-rotti = **già fatti e live su BQ** (commit `d4fe92b`, `25705f0`). Questo branch chiude la coda, niente di nuovo.

## Regola operativa: verify-then-close

Ogni item qui sotto va **prima verificato** — buona parte può essere già chiuso. **Non rifare lavoro fatto.** Se un item risulta già chiuso, segnalalo nel PR e barralo, non inventare modifiche.

Tag: `[code]` = fattibile da agente · `[stefano]` = manuale, account/UI di Stefano · `[verify]` = confermare se ancora aperto.

## Items

1. **`[code]` (sbloccato da input Stefano) — FORM_URL placeholder**
   - `verticals/condges/audit_consumi_dashboard.py:19` → `FORM_URL = "https://forms.gle/PLACEHOLDER"`.
   - Stefano genera la Form via Apps Script (`verticals/condges/audit_form.gs`, `createAuditForm()`) col suo account `stefano@panoramagroup.it` → ottiene l'URL reale.
   - Agente: sostituisci la riga 19 con l'URL reale (6 call-site usano la costante, basta cambiare la riga), commit. **Bloccato finché Stefano non fornisce l'URL.**

2. **`[stefano]` (NON codice) — Looker dashboard al contratto colonne v3**
   - CLAUDE.md checkpoint: *"resta aggiornare i dashboard Looker F&B al nuovo contratto colonne."*
   - `v_fb_kpi` ora espone `food_cost_pct_ristorante` + `food_cost_pct_bar` separati e ricavi split food/beverage. I dashboard Looker Studio vanno ricollegati **a mano** alle nuove colonne. Nessun diff repo. L'agente non può farlo → resta come checklist per Stefano in fondo al PR.

3. **`[verify]` — 3 minor fix dalla review audit 2026-05-21**
   - `alert_color` collassa "warn low" + "investigate low" in rosso per ricavo/pax (spec voleva 2 bande distinte). Verifica `audit_consumi_dashboard.py:43`.
   - B3 (Bar) monthly query: WHERE non filtrava reparto → scan tabella. Verifica `~:317+` — sembra già avere `WHERE codice IN (...)`, probabilmente **già ok**.
   - `docs/audit_consumi_workflow.md` mancava sezione "Possibili esiti dell'audit". Verifica/aggiungi.

4. **`[verify]` — CLAUDE.md gap residui**
   - `v_fb_kpi` v3 già documentato (riga ~320). Verifica se mancano: 33 reparti `f_consumi_economato` (vs 25 documentati storicamente) e le tabelle dell'audit tool. Aggiungi **solo** ciò che manca.

## Out of scope (NON toccare)

- `v_fb_kpi` v3 / esclusione 9 UoM — già fatto.
- Refactor viste F&B (già "wide", BQ-largo/Looker-filtra) — già fatto.
- Cash/PF, ingestione, P0 re-baseline — altri branch / altri task.

## Verify / criterio di merge

- `pytest` verde, `ruff check .` clean.
- Onestà > volume: se dopo la verifica l'unico lavoro-codice residuo è l'update FORM_URL (bloccato su Stefano), il PR è legittimamente minuscolo. Dichiararlo, non gonfiarlo.
- **Sub-skill:** usa `superpowers:verification-before-completion` prima di dichiarare done.

## Per Stefano (manuale, fuori dal diff)

- [ ] Generare la Google Form via `createAuditForm()` in script.google.com → fornire l'URL per l'item 1.
- [ ] Ricollegare i dashboard Looker Studio al contratto colonne `v_fb_kpi` v3 (item 2).
- [ ] Dare accesso al direttore alla Streamlit audit (hosting/tunnel — decisione aperta dal 2026-05-21).
