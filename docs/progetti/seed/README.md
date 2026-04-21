# HPAN25PIANO1 — Binario A MVP Seed Data

**Created:** 2026-04-21
**Purpose:** seed CSV denormalizzato per Binario A (flat subledger MVP). Non ancora produzione — vive qui come proposal finché la nuova CC instance non lo sposta in `core/bq/dimensioni/` (anagrafica) e genera loaders + view.

## Files

### `d_anagrafica_progetti.csv` (28 righe)

Anagrafica fornitori project-scoped con `supplier_id` 3-digit interno. Unione di:
- Walkthrough HPAN25PIANO1 (25 vendor user brief + 3 split scope)
- Vault ontology `CamerePrimoPiano.md` (10 vendor esistenti, allineati)
- Seed data Excel (best-guess mapping arredi)

Codici ID:
- `001-024` — suppliers reali (veri o ipotizzati con ragione sociale)
- `900-902` — placeholder per scope senza vendor identificato (piastrellista posa, luci balconi installer, segnaletica)
- `999` — cassa/imprevisti (non vendor-attributable)

Colonna `stato_censimento`:
- `ATTIVO` — ha movimenti in Esolver
- `CENSITO` — in anagrafica Esolver ma ancora no movimenti HPAN25PIANO1
- `DA_CENSIRE` — ancora nessun codice Esolver (nuovo fornitore)

Flag da risolvere (commento in `note`):
- `019 CAPONE` — ragione sociale DA DEFINIRE (disambiguare da Anna Capone persona)
- Possibili overlap: `011 Studio Ninni` vs `013 Rino Cuomo` su armadi, `012 Atelier` vs `028 Sedie+Tavoli`

### `f_progetto_stato_corrente_seed.csv` (28 righe)

Stato corrente del progetto: una riga per scope × supplier. Colonne:
- `preventivo_iniziale_eur` — cosa pensavamo di spendere (Preventivato)
- `preventivo_aggiornato_eur` — cosa abbiamo firmato (Impegnato, nullable se ancora IPOTESI)
- `acconti_pagati_eur` — cosa abbiamo davvero speso (Consumato, da calcolare via join Esolver — per ora 0 o vuoto)
- `stato_commitment` — IPOTESI | PREVENTIVO_PENDING | PREVENTIVO_RICEVUTO | FIRMATO | IN_CORSO | CHIUSO | ALLOCATO

Importi noti dal Excel `Budget Cost Piano 10 Cam Jan 26 2025.xlsx`:
- bucket (a) confermati: AMCN 413K, STE 107K
- bucket (b) confermati: Santelia 86K, Metal 2000 107K, Dierre 12K
- bucket (c) `NULL` su importo: Archisavio, Pisacane, NESE, Hospitality Project, Studio Ninni, Atelier — preventivi non in questo file (COMPLETO non disponibile)
- bucket (d) stime da Excel tab 02 (arredi): Dorelan 12K, Domus 27.5K, Flab 57K, Illuxit 5.6K, Zara 6K, ecc.
- imprevisti 38K allocati a supplier 999

Totali seed vs realtà:
- Sum(preventivo_iniziale) pop. = ~850K (mancano 6 righe professionisti + 2 arredi NULL)
- Sum previsto quando completa = ~1.084M (da dashboard Excel)
- Cap dichiarato = 1.2M, buffer nominale 116K, buffer reale post-overrun AMCN+STE = 73.8K

## Three-states model mapping

Il tuo framing (Preventivato / Impegnato / Consumato) mappa 1:1 ai campi:

| Stato concettuale | Campo CSV | Fonte |
|---|---|---|
| Preventivato (ipotesi) | `preventivo_iniziale_eur` | brief utente / Excel dashboard |
| Impegnato (firmato) | `preventivo_aggiornato_eur` | contratto firmato (se esiste) |
| Consumato (cassa) | `acconti_pagati_eur` | join con `f_movimenti_contabili` via `d_anagrafica_progetti.codice_esolver` |

Queries chiave derivabili in SQL view:

```sql
CREATE OR REPLACE VIEW v_progetto_stato_corrente AS
SELECT
  s.*,
  COALESCE(s.preventivo_aggiornato_eur, s.preventivo_iniziale_eur) AS commitment_attuale_eur,
  -- Consumato: join con Esolver quando supplier ha codice
  COALESCE((
    SELECT SUM(imp_dare - imp_avere)
    FROM `hotelops-suite.hotelops.f_movimenti_contabili` m
    WHERE m.codice_fornitore = (
      SELECT codice_esolver FROM d_anagrafica_progetti a WHERE a.supplier_id = s.supplier_id
    )
    AND m.codice_fornitore IS NOT NULL
    -- filtro project: TODO tag via f_progetto_invoice_link (Fase 2)
  ), 0) AS acconti_da_esolver_eur,
  -- Budget residuo (key query 1)
  COALESCE(s.preventivo_aggiornato_eur, s.preventivo_iniziale_eur) - COALESCE(s.acconti_pagati_eur, 0) AS residuo_eur,
  -- Variance scope change (key query 3a)
  s.preventivo_aggiornato_eur - s.preventivo_iniziale_eur AS delta_scope_change_eur,
  -- Variance overrun vs commitment
  s.acconti_pagati_eur - COALESCE(s.preventivo_aggiornato_eur, s.preventivo_iniziale_eur) AS delta_overrun_eur
FROM `hotelops-suite.hotelops.f_progetto_stato_corrente` s;
```

Vista aggregata progetto:

```sql
CREATE OR REPLACE VIEW v_progetto_overview AS
SELECT
  project_id,
  SUM(preventivo_iniziale_eur) AS budget_preventivato_eur,
  SUM(COALESCE(preventivo_aggiornato_eur, preventivo_iniziale_eur)) AS budget_impegnato_eur,
  SUM(acconti_pagati_eur) AS speso_cassa_eur,
  SUM(residuo_eur) AS da_pagare_eur,
  COUNT(*) AS n_scope_totali,
  SUM(CASE WHEN stato_commitment = 'IPOTESI' THEN 1 ELSE 0 END) AS n_scope_ipotesi,
  SUM(CASE WHEN stato_commitment LIKE 'PREVENTIVO_%' THEN 1 ELSE 0 END) AS n_scope_preventivo,
  SUM(CASE WHEN stato_commitment IN ('FIRMATO', 'IN_CORSO') THEN 1 ELSE 0 END) AS n_scope_firmati,
  SUM(CASE WHEN stato_commitment = 'CHIUSO' THEN 1 ELSE 0 END) AS n_scope_chiusi
FROM v_progetto_stato_corrente
GROUP BY project_id;
```

## Next steps (per nuova CC instance)

1. **Review seed data con Stefano** — verificare ragioni sociali, disambiguare Capone, Dierre bucket, scope Metal 2000.
2. **Spostare `d_anagrafica_progetti.csv`** da `docs/progetti/seed/` → `core/bq/dimensioni/` quando approvato.
3. **Creare `d_progetti.csv`** minimale (1 riga HPAN25PIANO1 con cap 1.2M, societa_owner INTUR, bu HOTEL, ecc.)
4. **Scrivere loaders** — `core/bq/load/load_anagrafica_progetti.py` e `load_progetto_stato_corrente.py` seguendo pattern di `load_voci_piano_finanziario.py` (idempotente WRITE_TRUNCATE).
5. **Deploy view SQL** — `v_progetto_stato_corrente.sql` e `v_progetto_overview.sql` in `core/bq/views/`.
6. **Streamlit minima** — `progetti/app_progetti.py` con 1 pagina: KPI overview + tabella scope × supplier + filtri (societa, stato).
7. **Esolver reconciliation** — aggiungere join reale su `f_movimenti_contabili` quando `codice_esolver` è popolato. Per fornitori DA_CENSIRE, il valore resta 0.
8. **Label propagation** — design di `f_progetto_invoice_link` per taggare movimenti Esolver con `(project_id, supplier_id, scope_id)` — Fase 2.

## Relationship con altri files

- **`../HPAN25PIANO1-walkthrough.md`** — conceptual validation del modello con rotture note. Questo seed implementa.
- **`../HPAN25PIANO1-seed-data.md`** — Excel reality check + reality buffer calcolato. Questo seed usa.
- **`../../superpowers/specs/2026-04-20-projects-mvp-design.md`** — spec normalizzata 7-entità. Questo flat seed si splitta in normalizzato quando Binario C parte.
- **`../../vault-snippets/refactor-roadmap.md`** — Fase 0 (INVESTIMENTI_CAPEX + stato_censimento) è indipendente da questo MVP; Fase 1 (enums + loaders) lo inglobba quando arriva.
