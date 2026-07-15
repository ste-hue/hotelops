"""Test del loader .env manuale (core/env.py)."""

import os

from core.env import load_dotenv_file


def test_load_dotenv_file_parses_and_does_not_override(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# commento\n"
        "\n"
        "PLAIN=valore\n"
        'QUOTED="con spazi dentro"\n'
        "PRESENTE=nuovo\n"
        "riga senza uguale\n"
    )
    monkeypatch.delenv("PLAIN", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    monkeypatch.setenv("PRESENTE", "originale")

    load_dotenv_file(env_path=env_file)

    assert os.environ["PLAIN"] == "valore"
    assert os.environ["QUOTED"] == "con spazi dentro"
    assert os.environ["PRESENTE"] == "originale"  # shell vince


def test_load_dotenv_file_missing_path_is_noop(tmp_path):
    missing = tmp_path / "does-not-exist.env"
    # non deve sollevare eccezioni se il file non esiste
    load_dotenv_file(env_path=missing)
