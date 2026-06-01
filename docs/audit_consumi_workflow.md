# Audit consumi F&B — Workflow

Strumento per raccogliere dalla direzione di Hotel Panorama l'interpretazione
del primo modello F&B (canonical-transformation-matrix a 6 layer × 3 vertical).

## Setup iniziale (1 volta)

1. **Genera Google Form** — Stefano:
   - Apri `verticals/condges/audit_form.gs`
   - Copia su https://script.google.com (nuovo progetto)
   - Esegui `createAuditForm()`, autorizza
   - Nei Log trovi `Form URL` + `Spreadsheet URL`
2. **Aggiorna `FORM_URL`** in `verticals/condges/audit_consumi_dashboard.py` con
   l'URL reale ottenuto
3. Commit del cambio

## Esecuzione audit

1. Stefano apre la Streamlit:
   ```bash
   streamlit run verticals/condges/audit_consumi_dashboard.py
   ```
2. Condivide URL (locale o tunnel) + link Form al direttore
3. Direttore:
   - Apre la Streamlit (~5 min Primer + ~15 min B1/B2/B3 + ~5 min anomalie)
   - Apre il Google Form e risponde (~15 min)
   - Tempo totale: 30-40 min

## Post-risposte

1. Stefano apre il Google Sheet collegato alla Form
2. Esporta CSV o copia/incolla risposte
3. Insieme a Claude:
   - **S1-S3 (vertical codici)**: aggiorniamo lista codici nelle SQL di
     `v_fb_kpi` o nuove view
   - **S4 (coperti)**: aggiorniamo logica per leggere coperti dalla fonte
     corretta (Hoxell vs Sheet)
   - **S5 (range)**: aggiorniamo `target_lo/target_hi/warning_hi` nei semafori
     della dashboard
   - **S6 (anomalie FYI)**: applichiamo i fix confermati, riapriamo quelle
     non confermate
   - **S7 (catch-all)**: nuove pagine/vertical/KPI se emergono
4. Stefano approva i cambi → implementazione

## File coinvolti

| File | Tipo | Scopo |
|---|---|---|
| `verticals/condges/audit_consumi_dashboard.py` | Streamlit | Read-only viewer 6 pagine |
| `verticals/condges/audit_form.gs` | Apps Script | Google Form 8 sezioni |
| `docs/superpowers/specs/2026-05-21-audit-consumi-fb-direzione-design.md` | Spec | Design canonical-transformation-matrix |
| `docs/superpowers/plans/2026-05-21-audit-consumi-fb-direzione.md` | Plan | Questo piano |

## Round successivi (out of scope ora)

- Chef → matrice `categoria_prodotto` → ricetta (KPI quantità/coperto)
- POS Ristocube → separare drink bar/ristorante/banchetti
- Streamlit Cloud hosting per accesso remoto direttore
