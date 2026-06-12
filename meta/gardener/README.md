# Giardiniere notturno

Agente Claude Code headless che ogni notte alle 02:00 esegue i chores pre-approvati
(issue GitHub etichettate `gardener`), apre PR, e propone triage sui thread nuovi
(issue `triage-proposta`). Mandato completo in `GARDENER.md`.

## Il board (il "Linear tra di noi")

- **`gardener`** su un'issue = pre-approvata, il giardiniere la esegue stanotte (max 3/notte).
- **`triage-proposta`** = proposta del giardiniere, aspetta il tuo verdetto: se ok,
  ri-etichetti `gardener`; se no, chiudi con un commento (resta come decision-memory).
- I PR linkano le issue (`Closes #N`): merge del PR = issue chiusa.
- STATUS.md resta il diario; le issue sono la coda esecutiva.

## Setup (una tantum)

```bash
# 1. gh CLI autenticato
brew install gh && gh auth login

# 2. Label
gh label create gardener --color 2ea44f --description "Pre-approvato per il run notturno"
gh label create triage-proposta --color fbca04 --description "Proposta del giardiniere, attende verdetto"

# 3. Test manuale diurno (PRIMA di schedulare!)
bash meta/gardener/run.sh
tail -f meta/gardener/logs/*.log

# 4. Schedula
cp meta/gardener/com.hotelops.gardener.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hotelops.gardener.plist

# 5. Il Mac deve essere acceso/sveglio alle 02:00 (caffeinate copre solo il run):
sudo pmset repeat wakeorpoweron MTWRFSU 01:55:00
```

## Rituale del mattino (5 min)

1. GitHub → PR aperti dal giardiniere: merge o commento.
2. Issue `triage-proposta`: promuovi a `gardener` o chiudi.
3. Issue `gardener-report`: il riepilogo della notte.

## Spegnere / sospendere

```bash
launchctl bootout gui/$(id -u)/com.hotelops.gardener
```

O semplicemente: nessuna issue `gardener` aperta = la notte fa solo triage proposte.
