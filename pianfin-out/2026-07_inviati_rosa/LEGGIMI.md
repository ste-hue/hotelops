# PF luglio 2026 — i due file mandati a Rosa

Copiati qui il 2026-08-14 dalla cartella temporanea di WhatsApp (che iOS ripulisce da sola).
Sono **le copie come inviate a Rosa**, prima che lei cominciasse a compilarle: servono da
"prima" di riferimento, non come versione di lavoro. La versione viva è quella che torna da Rosa.

| file | società | griglia mesi del foglio Piano Finanziario |
|---|---|---|
| `INTUR_PF_2026-07_post-rotate_2026-08-12T12-33.xlsx` | INTUR | marzo 2026 → giugno 2027 (col. D→S) |
| `ORTI_PF_2026-07_extended_2027-06_2026-08-11T19-55.xlsx` | ORTI | aprile 2026 → giugno 2027 (col. D→R) |

Le colonne oltre dicembre 2026 sono l'allungamento fatto a mano ad agosto: servono a vedere se la
cassa arriva viva alla riapertura, quindi coprono tutta la chiusura stagionale. Al momento della
copia i mesi 2027 erano vuoti su tutte le voci — Rosa li stava riempiendo.

## Le righe mutui non si riempiono per continuità

Sono l'unica voce del piano già determinata dai contratti, e nella finestra 2027 hanno due salti
che il trascinamento dei valori non prende. Verificati contro `app-mutui`
(`public/data/mutui_completi.json`, compilato 2026-04-30) e coincidenti al centesimo con lo
scadenziario in BigQuery.

**INTUR** — foglio `Mutui e Finaziamenti`, colonne `T` (gen 2027) → `Y` (giu 2027):
righe 4 e 6 continuano a 9.000 e 1.388,48; la riga 7 (MPS 1,2M) vale 3.500 a gennaio — ultima rata
di soli interessi — e poi **12.902 da febbraio**, quando parte l'ammortamento. Totale mensile:
13.890 a gennaio, 23.290 da febbraio.

**ORTI** — foglio `Mutui e Finaziamenti`, colonne `M` (gen 2027) → `R` (giu 2027):
righe 5 e 6 continuano a 12.243,63 e 1.393,92; la riga 4 (MPS 3,5M) paga **a rate semestrali**,
quindi resta a zero da gennaio a maggio e vale **166.175,81 a giugno** (`R4`). È lo stesso importo
già presente a dicembre 2026.

In entrambi i file il totale in riga 3 è una `SUM` e si aggiorna da solo, e la riga corrispondente
del foglio `Piano Finanziario` è una formula che punta lì: si scrive solo nel foglio di dettaglio.

## Da decidere

- Nel file INTUR l'Intesa è a 9.000, mentre contratto e scadenziario dicono 8.500. Tasso variabile,
  può essere prudenza voluta.
- `scadenziario_mutui.csv` (fonte `SCADENZIARIO` in `f_piano_finanziario_input`) è caricato a mano,
  non ha pipeline nel repo e non copre oltre il 2027. Se questi due file diventano i campioni
  aggiornati ogni mese, le righe mutui conviene generarle da lì invece che a mano.
