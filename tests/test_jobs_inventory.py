"""L'inventario dei Cloud Run Job come oggetto di test.

Il difetto che questi controlli chiudono: il codice committato e il codice in
esecuzione possono divergere senza che niente lo segnali, e la ricevuta che il
repo promette può non esistere in `f_pipeline_runs` perché quel `PipelineRun`
non è nell'immagine distribuita. Qui si verifica la metà che si può verificare
offline — che l'inventario sia coerente col codice e col registry — su file
versionati, senza chiamare Google.

Perimetro: i Cloud Run Job dichiarati in `infra/jobs.yaml`. Le pipeline che non
girano su Cloud Run non vengono bloccate da qui.
"""

import os
from pathlib import Path

import pytest
import yaml

RADICE = Path(__file__).resolve().parents[1]
# Il percorso è sovrascrivibile: serve al rilascio e alle prove di mutazione,
# che devono poter dimostrare che questi controlli sanno diventare rossi.
PERCORSO = Path(os.environ.get("HOTELOPS_JOBS_INVENTORY", RADICE / "infra" / "jobs.yaml"))
INVENTARIO = yaml.safe_load(PERCORSO.read_text(encoding="utf-8"))
JOB = INVENTARIO["job"]
NOMI = [j["nome"] for j in JOB]

# Il codice Python del repo, una volta: i controlli sulle ricevute lo cercano.
SORGENTI = {
    p: p.read_text(encoding="utf-8")
    for p in RADICE.rglob("*.py")
    if "tests" not in p.parts and ".venv" not in p.parts and "scratchpad" not in p.parts
}


def ricevute_dichiarate():
    return {j["nome"]: j["ricevuta"] for j in JOB}


def test_ogni_job_ha_un_percorso_dichiarato():
    """Nessun job senza il punto del codice da ispezionare: se ne nasce uno
    nuovo, questo test chiede di dichiararlo invece di lasciarlo scoperto."""
    assert set(PERCORSI) == set(NOMI), (
        f"percorsi non dichiarati: {set(NOMI) - set(PERCORSI)}; "
        f"di troppo: {set(PERCORSI) - set(NOMI)}"
    )


def test_ogni_job_e_descritto_per_intero():
    """Un campo assente non è verificabile: qui si pretende che ci sia."""
    assert NOMI, "inventario vuoto"
    assert len(NOMI) == len(set(NOMI)), "due job con lo stesso nome"
    for j in JOB:
        for campo in ("nome", "entrypoint", "moduli", "service_account", "scheduler", "provisioning"):
            assert j.get(campo), f"{j.get('nome')}: manca {campo}"
        assert "ricevuta" in j, f"{j['nome']}: `ricevuta` va dichiarata, anche se nulla"
        assert j["entrypoint"].get("command") and j["entrypoint"].get("args"), j["nome"]
        for chiave in ("nome", "schedule", "fuso"):
            assert j["scheduler"].get(chiave), f"{j['nome']}: scheduler senza {chiave}"


def test_lo_script_di_provisioning_esiste_e_nomina_quel_job():
    for j in JOB:
        percorso = RADICE / j["provisioning"]
        assert percorso.exists(), f"{j['nome']}: {j['provisioning']} non esiste"
        testo = percorso.read_text(encoding="utf-8")
        assert f"jobs create {j['nome']} " in testo, (
            f"{j['nome']}: {j['provisioning']} non crea un job con questo nome"
        )


def test_l_entrypoint_riferisce_moduli_che_esistono():
    """Un entrypoint che punta a un modulo inesistente è un job che fallisce
    al primo avvio, e lo si scopre dal cloud invece che qui."""
    for j in JOB:
        comando = " ".join([j["entrypoint"]["command"], *j["entrypoint"]["args"]])
        for modulo in j["moduli"]:
            assert f"-m {modulo}" in comando, f"{j['nome']}: {modulo} non è nell'entrypoint"
            atteso = RADICE / (modulo.replace(".", "/") + ".py")
            assert atteso.exists(), f"{j['nome']}: il modulo {modulo} non esiste ({atteso})"


def test_l_immagine_non_e_pinnata_nell_inventario():
    """Il riferimento immutabile si risolve al rilascio.

    Un tag scritto qui tornerebbe mobile, che è metà del difetto di partenza.
    """
    immagine = INVENTARIO["immagine"]
    assert ":" not in immagine.split("/")[-1], f"{immagine}: nessun tag nell'inventario"
    assert "@" not in immagine, f"{immagine}: nessun digest nell'inventario"
    for j in JOB:
        osservato = j.get("osservato", {})
        assert osservato.get("il"), f"{j['nome']}: l'osservazione va datata"


# ── Dal flag dell'entrypoint al punto esatto che apre la ricevuta ───────────
# Cercare `PipelineRun("reviews_scrape")` in tutto il repo è un falso verde:
# resta verde anche se il job viene instradato su `--report`, che quella
# ricevuta non la scrive. Tabella esplicita per i sei percorsi che esistono,
# non un analizzatore generico: il file e, dove un flag discrimina, la
# funzione raggiunta.
import ast
import re

PERCORSI = {
    # job: (file che deve contenere il PipelineRun, funzione o None per tutto il file)
    "pec-fetch": ("ingest/pec_fetch.py", None),
    "coperti": ("ingest/flussi/ingest_coperti.py", None),
    "spiaggia-corrispettivi": ("ingest/drive_fetch.py", None),
    "reviews-scrape": ("verticals/reviews/cli_commands.py", "_cmd_scrape"),
    "reviews-report": ("verticals/reviews/cli_commands.py", "_cmd_report"),
    "canone-push": ("cli.py", "cmd_canone"),
}

# Il flag dell'entrypoint che deve portare a quella funzione, per i percorsi
# che passano da un dispatcher.
DISPATCH = {
    "reviews-scrape": ("verticals/reviews/cli_commands.py", "cmd_reviews", "scrape", "_cmd_scrape"),
    "reviews-report": ("verticals/reviews/cli_commands.py", "cmd_reviews", "report", "_cmd_report"),
}


def _funzione(percorso: Path, nome: str) -> ast.FunctionDef:
    albero = ast.parse(percorso.read_text(encoding="utf-8"))
    for nodo in ast.walk(albero):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == nome:
            return nodo
    raise AssertionError(f"{percorso}: nessuna funzione {nome}")


def _sorgente_di(file_relativo: str, funzione: str | None) -> str:
    percorso = RADICE / file_relativo
    assert percorso.exists(), f"{file_relativo} non esiste"
    if funzione is None:
        return percorso.read_text(encoding="utf-8")
    return ast.unparse(_funzione(percorso, funzione))


@pytest.mark.parametrize("nome", sorted(PERCORSI))
def test_il_flag_dell_entrypoint_porta_alla_funzione_dichiarata(nome):
    """Instradare reviews-scrape su `--report` deve rompere qualcosa, qui."""
    if nome not in DISPATCH:
        return
    file_relativo, dispatcher, flag, attesa = DISPATCH[nome]
    args = [j for j in JOB if j["nome"] == nome][0]["entrypoint"]["args"]
    assert f"--{flag}" in args, f"{nome}: l'entrypoint non passa --{flag}"
    # Nel dispatcher, il ramo che testa quel flag chiama proprio quella funzione.
    corpo = _funzione(RADICE / file_relativo, dispatcher)
    chiamate_per_flag = {}
    for nodo in ast.walk(corpo):
        if not isinstance(nodo, ast.If):
            continue
        testo_test = ast.unparse(nodo.test)
        chiamate = [
            c.func.id for c in ast.walk(ast.Module(body=nodo.body, type_ignores=[]))
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
        ]
        for f in ("scrape", "report", "alert", "stats", "rispondi"):
            if f in testo_test and chiamate:
                chiamate_per_flag.setdefault(f, chiamate[0])
    assert chiamate_per_flag.get(flag) == attesa, (
        f"{nome}: --{flag} porta a {chiamate_per_flag.get(flag)}, non a {attesa}"
    )


@pytest.mark.parametrize("nome,ricevuta", sorted(ricevute_dichiarate().items()))
def test_la_ricevuta_dichiarata_e_aperta_proprio_dal_percorso_di_quel_job(nome, ricevuta):
    """Non «esiste da qualche parte nel repo»: deve stare nel punto che
    l'entrypoint di QUESTO job raggiunge."""
    file_relativo, funzione = PERCORSI[nome]
    sorgente = _sorgente_di(file_relativo, funzione)
    if ricevuta is None:
        assert "PipelineRun(" not in sorgente, (
            f"{nome}: dichiara `ricevuta: null` ma {file_relativo}"
            f"{'::' + funzione if funzione else ''} apre un PipelineRun"
        )
        return
    if ":" in ricevuta:
        # Nome composto: il prefisso sta nel codice come f-string, e la parte
        # dopo i due punti deve venire dall'argomento dell'entrypoint — non
        # basta che il prefisso combaci.
        prefisso, valore = ricevuta.split(":", 1)
        # `ast.unparse` normalizza gli apici: il confronto non deve dipendere
        # dalla forma con cui la stringa è scritta nel sorgente.
        assert re.search(rf"""f['"]{re.escape(prefisso)}:""", sorgente), (
            f"{nome}: {file_relativo} non costruisce una ricevuta «{prefisso}:…»"
        )
        args = [j for j in JOB if j["nome"] == nome][0]["entrypoint"]["args"]
        assert "--source-name" in args, f"{nome}: nessun --source-name nell'entrypoint"
        passato = args[args.index("--source-name") + 1]
        assert passato == valore, (
            f"{nome}: la ricevuta dichiara «{valore}» ma l'entrypoint passa «{passato}»"
        )
    else:
        assert re.search(rf"""PipelineRun\(\s*['"]{re.escape(ricevuta)}['"]""", sorgente), (
            f"{nome}: dichiara «{ricevuta}» ma non è aperto in {file_relativo}"
            f"{'::' + funzione if funzione else ''}"
        )


def registry_auto():
    percorso = RADICE / "core" / "source_registry.yaml"
    sorgenti = yaml.safe_load(percorso.read_text(encoding="utf-8"))["sources"]
    fuori = {}
    for nome, s in sorgenti.items():
        acq = s.get("acquisition") or {}
        if acq.get("mode") == "AUTO" and acq.get("job"):
            fuori.setdefault(acq["job"], []).append(nome)
    return fuori


def test_le_sorgenti_automatiche_servite_da_questi_job_combaciano():
    """Nel perimetro: le pipeline che NON girano su Cloud Run non sono bloccate.

    Si verifica che ciò che l'inventario e il registry dicono della stessa
    pipeline non si contraddica, e che nessun job del registry sia rivendicato
    da due job diversi.
    """
    auto = registry_auto()
    dichiarate = {r: n for n, r in ricevute_dichiarate().items() if r is not None}
    comuni = set(auto) & set(dichiarate)
    assert comuni, "nessuna sorgente automatica è servita da un job dell'inventario"
    # Il pilota del rilascio: le tre caselle PEC passano da qui.
    assert "pec_fetch" in comuni, "pec_fetch non è più il raccordo fra registry e inventario"
    assert sorted(auto["pec_fetch"]) == [
        "PEC_MAILBOX_INTUR_APPEND",
        "PEC_MAILBOX_ORTI_APPEND",
        "PEC_MAILBOX_VIGNA_APPEND",
    ]
    # Nessuna ambiguità: una pipeline, un job.
    rivendicazioni = [r for n, r in ricevute_dichiarate().items() if r is not None]
    assert len(rivendicazioni) == len(set(rivendicazioni)), (
        "due job dell'inventario dichiarano la stessa ricevuta"
    )
