# Progetti

**L'astrazione è il progetto.** Soft Panorama e Cantiere 2026 sono due
istanze, non due nuovi verticali. Audience: Stefano, che passa dagli
strumenti di esecuzione al governo in Regia.

| Progetto | Strumento operativo | Fronte Regia |
| --- | --- | --- |
| `HPAN26SOFT` | https://soft.panorama-host.com | `68079b85` |
| `HPAN26PIANO3` | https://hpan26.panorama-host.com | `ea45459f` |

`catalog.py` contiene solo i raccordi di navigazione. `progetto_id` riusa il
vocabolario del modello `Progetto` in `core/schemas.py`; non crea una seconda
anagrafica, né attesta che questi ID siano già censiti nel BigQuery live.

Il Hub monta una sola pagina `projects`, sensibile e con controllo di accesso
server-side. Accessibile agli admin già esistenti; nessun nuovo grant a reparti.
Le destinazioni conservano i propri controlli di accesso.

## Confini

- App di progetto: dettaglio operativo, rilievi, lavorazioni e forniture.
- Regia: risultati, decisioni, responsabilità e verifiche.
- HotelOps: fatti finanziari e calcoli canonici, con CASSA / COMPETENZA / IMPEGNO.

Questa prima connessione è navigazione, non ingestione o sincronizzazione.
Un successivo adapter dovrà raccordare `progetto_id` e ID sorgente, dichiarare
versione, data di lettura e copertura; distinguere avanzamento dichiarato da
verificato. I dati finanziari passeranno dai gate e dalle viste esistenti,
senza sommare stime, impegni e pagamenti.

Fonte: indicazione di Stefano del 25/10/2026 e copia Regia della stessa data.
URL e nodi sono riferimenti forniti; accesso live e dati non collaudati in questa PR.
