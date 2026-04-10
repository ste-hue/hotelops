# POC Archive — `tri_angle/hotel-review-aggregator`

**Status:** SHELVED 2026-04-10
**Branch:** `poc/apify-aggregator` (deleted)
**Worktree:** `.worktrees/poc-aggregator` (removed)

## Cosa era

POC per consolidare le 4 chiamate Apify separate (Booking, TripAdvisor, Google,
Expedia) in un'unica chiamata all'actor `tri_angle/hotel-review-aggregator`,
che identifica una property via Google Maps e poi cross-matcha le review dalle
altre piattaforme.

## Run #1 (2026-04-10)

- **Target:** Hotel Panorama (Maiori)
- **Window:** 10 giorni
- **Cap:** $1
- **Result:** 5 item (tutti Booking), costo $0.0181
- **`reviewsFromDate` server-side:** confermato funzionante → efficient incremental scrape

Output raw salvato in `poc_output_hotel.json`.

## Perché shelf

**Blocker fondamentale: Expedia cross-match fallisce.**

L'aggregator parte da Google Maps per risolvere l'identità della property, poi
cerca sulle altre piattaforme. Per Hotel Panorama fallisce con
`"Failed to get any URLs"` su Expedia, nonostante noi abbiamo 197 row Expedia
già scrapate via `memo23/expedia-scraper` nel fan-out corrente.

Senza Expedia l'aggregator ci dà un sottoinsieme di quello che già abbiamo.

## Perché non è prioritario risolverlo

Il fan-out 4-actor corrente:
- Funziona end-to-end
- Copre tutte e 4 le piattaforme (Expedia incluso)
- Costa frazioni di cent per run a regime (watermark gate + cap 15/property)
- Budget Apify $25/mese non è minacciato
- È testato, in prod, con observability (f_apify_runs)

Il solo vantaggio dell'aggregator sarebbe architetturale (1 actor vs 4). A
questi costi non compensa il rischio di migrazione.

## Condizioni per riaprire

1. `tri_angle/hotel-review-aggregator` espone un modo per passare URL Expedia
   manualmente (bypass del Google-first cross-match), **oppure**
2. Il fan-out inizia a costare >$5/mese (oggi ~$0.10), **oppure**
3. Serve dedup cross-platform avanzato che il fan-out non copre

## File conservati

- `poc_aggregator.py` — script driver del POC. Documenta il pattern
  `reviewsFromDate` server-side per incremental scrape (riusabile se in futuro
  lo applichiamo agli actor del fan-out come ottimizzazione costi).
- `poc_output_hotel.json` — output raw di Run #1 per reference.
