# Trend punteggio: media smorzata per affidabilità

**Data:** 2026-07-21 · **Vertical:** reviews · **Stato:** approvata (chat)

## Problema

La media mensile da sola non comunica l'affidabilità del dato: un 10 ottenuto
con 3 recensioni pesa nel grafico quanto un 8,75 ottenuto con 118. I mesi a
basso campione producono picchi/crolli che sembrano segnale ma sono rumore.

## La domanda della sezione (invariata)

"Come sta andando il punteggio per BU nel tempo?" — la correzione serve a far
sì che il grafico risponda a QUESTA domanda senza urlare sui mesi vuoti.
Il confronto anno-su-anno è un'altra domanda: fuori scope, eventuale sezione
separata.

## Decisione: media smorzata (empirical Bayes, stile IMDB)

Alternative considerate: banda di confidenza (scartata: con 4-5 BU sovrapposte
diventa rumore visivo), rolling 3 mesi (scartata: perde risoluzione mensile su
business stagionali apr-ott).

```
media_adj = (n · media_mese + SHRINK_M · media_BU) / (n + SHRINK_M)
```

- `SHRINK_M = 10`: un mese domina il prior solo con ben più di 10 recensioni.
  Con n=118 la correzione è impercettibile; con n=3 il punto viene tirato
  per ~3/4 verso la media storica della BU.
- **Prior = media di `punteggio_norm` della BU sul dataset filtrato** (stessi
  filtri sidebar anno/piattaforme/BU del resto della pagina — niente stato
  nascosto, niente query aggiuntive).

## Comportamento

- `monthly_trend(df)` resta pura e ritorna una colonna in più: `media_adj`
  (colonne: `mese, business_unit_id, media, media_adj, n`).
- `trend_figure` traccia la linea su `media_adj`; hover mostra media corretta,
  media grezza e n. Resta il marker vuoto sotto `LOW_SAMPLE_N` recensioni.
- Caption sotto il grafico: una riga che spiega che i mesi con poche recensioni
  sono riportati verso la media della BU.

## Test

1. n grande → `media_adj` ≈ media grezza (convergenza).
2. n piccolo → `media_adj` tra media grezza e prior, vicina al prior.
3. BU con punteggi tutti uguali → `media_adj` == media (invarianza).
4. Df vuoto → colonna presente, schema stabile.
