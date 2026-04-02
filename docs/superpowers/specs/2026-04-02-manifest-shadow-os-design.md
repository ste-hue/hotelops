# Manifest & Budget Architecture — Design Spec

**Date:** 2026-04-02
**Status:** Draft

## Problema

La conoscenza di dove stanno i dati è nella testa di Stefano, non nel sistema. Un agente AI che riceve "quanto spendiamo di luce?" deve sapere quale tabella, quale colonna, quale codice conto interrogare. Oggi serve aprire BQ per scoprirlo.

Secondo problema: il budget in BQ ha 9 fonti sovrapposte che si sommano. Il modello Gasparotto fornisce lo **schema** (nomi, categorie, tipi costo) ma i **numeri** vengono da Esolver (consuntivo anno precedente × fattori di aggiustamento × stagionalità).

## Design

### 1. Manifest (`hotelops manifest`)

Comando CLI che interroga BQ e genera `core/bq/manifest.yaml` — un'etichetta leggibile per ogni tabella.

Per ogni tabella:
- `rows`: quante righe
- `freshness`: date min/max dei dati
- `sources`: file sorgente distinti
- `columns`: per ogni colonna, tipo + valori distinti (se <= 30) o sample (se > 100)

Il manifest è l'etichetta sul pacco. L'ontologia dice cosa *significa*, il manifest dice cosa *c'è dentro*.

**Consumatori:** Stefano (CLI), agenti AI (NanoClaw, Claude Code), governance (freshness alerts).

**Output:** `core/bq/manifest.yaml`, committed in git, rigenerato con `hotelops manifest`.

### 2. Budget architecture

**Principio:** Gasparotto = schema dei nomi. Esolver = fonte dei numeri.

Il modello Gasparotto definisce:
- ~120 codici conto con descrizione leggibile
- Classificazione: tipo_costo (F=fisso, V=variabile, IP=ricavo, P=personale)
- Gerarchia: categoria_ce (Ricavi, Costi Produttivi, Personale, etc.)
- Fattori di aggiustamento per tipo (inflazione, produttività)

I numeri vengono da:
- **Consuntivo:** `f_movimenti_contabili` (prima nota Esolver, cod_conto senza punti)
- **Budget:** consuntivo anno precedente × fattore × coefficiente_stagionalità mensile

Il problema attuale è che `f_budget_mensile` ha 9 fonti (GASPAROTTO, MAPPATURA, STRUTTURALI, INCIDENZA, PERSONALE, CONS2025_*) che si sovrappongono per lo stesso codice conto. La vista `v_budget_vs_consuntivo` somma tutto → double-counting.

**Fix:** Aggiungere logica di priorità nella vista. Dove esiste una fonte specifica (STRUTTURALI, MAPPATURA, PERSONALE), quella vince su GASPAROTTO. Ordine:

1. STRUTTURALI (costi fissi noti)
2. MAPPATURA (costi per BU)
3. PERSONALE
4. INCIDENZA
5. CONS2025_* (consuntivo come proxy)
6. GASPAROTTO (fallback)

### File coinvolti

| File | Azione |
|------|--------|
| `cli.py` | Nuovo subcommand `manifest` |
| `core/bq/manifest.py` | Nuovo: genera manifest da BQ |
| `core/bq/manifest.yaml` | Nuovo: output generato |
| `core/bq/views/v_budget_vs_consuntivo.sql` | Fix priorità fonti |

### Non in scope

- Nuovi verticali (prenotazioni, magazzino)
- Semantic layer (Cube.dev)
- API REST
- Nuovi detector in classify.py
