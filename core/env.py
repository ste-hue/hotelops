"""Caricamento del .env di repo in os.environ — loader manuale, zero dipendenze."""

import os
from pathlib import Path


def load_dotenv_file(env_path: Path | None = None) -> None:
    """Load .env from repo root into os.environ (idempotent, no deps).

    Manual loader invece di `python-dotenv` o `export $(... | xargs)` perché
    quest'ultimo splitta su spazi i valori (es. Gmail App Password formato
    'xxxx xxxx xxxx xxxx') — bug reale che ci ha fatto perdere un'ora.
    Formato: KEY=VALUE per riga, `#` per commenti, quote opzionali.
    Non sovrascrive var già presenti (shell vince).

    `env_path` è opzionale e serve principalmente ai test: di default
    risolve alla root del repo (un livello sopra `core/`).
    """
    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
