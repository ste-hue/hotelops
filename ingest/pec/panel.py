"""sync-panel: projection degli allegati importanti su AMM_CEO (Drive mirror).

GCS/BQ canonici; il pannello è una copia consultabile. Stato autoritativo:
f_pec_panel_projections. Whitelist positiva PANEL_ENTITIES (I-PEC-3). Solo
aggiunte, mai delete/overwrite (I-PEC-4/5/6). Spec 2026-07-17.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from core.config import (
    F_PEC_ALLEGATI,
    F_PEC_MESSAGES,
    F_PEC_PANEL_PROJECTIONS,
    PANEL_CATEGORY_FOLDERS,
    PANEL_ENTITIES,
    PANEL_MAX_ATTACHMENT_BYTES,
    PANEL_ROOT,
    PROJECT,
)
from core.schemas import PecPanelProjectionRow, validate_batch

log = logging.getLogger("ingest.pec.panel")

_SAFE_CHARS = re.compile(r"[^\w\s\.\-\(\)àèéìòùÀÈÉÌÒÙ']", re.UNICODE)


def _sanitize_filename(nome: str, max_len: int = 180) -> str:
    """Solo basename, niente traversal/control char, charset sicuro, cap."""
    nome = (nome or "").replace("\\", "/").rsplit("/", 1)[-1]
    # \s in _SAFE_CHARS ammette anche i control char whitespace (\n, \t, \r):
    # vanno tolti prima, non lasciati passare come "sicuri".
    nome = "".join("_" if (ord(c) < 32 or 0x7F <= ord(c) <= 0x9F) else c for c in nome)
    nome = _SAFE_CHARS.sub("_", nome)
    nome = re.sub(r"\.\.+", ".", nome).strip(" .") or "allegato"
    if len(nome) > max_len:
        stem, dot, ext = nome.rpartition(".")
        if dot and len(ext) <= 10:
            nome = stem[: max_len - len(ext) - 1] + "." + ext
        else:
            nome = nome[:max_len]
    return nome


def _destination_path(
    entity_id: str, category: str | None, data_evento: datetime, nome_file: str
) -> Path:
    """Path RELATIVO al root: <ENTITY>/PEC/<Categoria>/<AAAA-MM> - <nome>."""
    if entity_id not in PANEL_ENTITIES:
        raise ValueError(f"entity {entity_id} non in whitelist PANEL_ENTITIES")
    cartella = PANEL_CATEGORY_FOLDERS.get(category or "ALTRO", "Altro")
    nome = _sanitize_filename(nome_file)
    return Path(entity_id) / "PEC" / cartella / f"{data_evento:%Y-%m} - {nome}"


def projection_key(msgid: str, sha256: str, dest_rel: str) -> str:
    return hashlib.md5(f"{msgid}|{sha256}|{dest_rel}".encode()).hexdigest()


def _assert_under_root(dest_abs: Path, root: Path) -> None:
    if root.resolve() not in dest_abs.resolve().parents:
        raise ValueError(f"path fuori dal root pannello: {dest_abs}")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for blocco in iter(lambda: f.read(1 << 20), b""):
            h.update(blocco)
    return h.hexdigest()


def _con_suffisso(dest_rel: Path, suffisso: str) -> Path:
    """"<AAAA-MM> - nome.pdf" -> "<AAAA-MM> - nome (<suffisso>).pdf"."""
    stem, dot, ext = dest_rel.name.rpartition(".")
    nome = f"{stem} ({suffisso}).{ext}" if dot else f"{dest_rel.name} ({suffisso})"
    return dest_rel.parent / nome


def _resolve_dest(
    root: Path, dest_rel: Path, sha256: str, claims: dict[str, str]
) -> tuple[Path, bool]:
    """Path definitivo per un contenuto + flag "identico già presente lì".

    Un nome può essere legittimamente conteso da contenuti DIVERSI (es. tre
    RicevutaCu.pdf di pratiche camerali distinte nello stesso mese): il primo
    contenuto tiene il nome piano, gli altri prendono un suffisso derivato dal
    proprio sha256 — deterministico, quindi stabile tra run. Arbitro è il
    disco (più i claim del run corrente, che in dry-run lo simulano): mai
    overwrite, mai perdita silenziosa.
    """
    candidati = (
        dest_rel,
        _con_suffisso(dest_rel, sha256[:8]),
        _con_suffisso(dest_rel, sha256),
    )
    for rel in candidati:
        occupante = claims.get(str(rel))
        if occupante == sha256:
            return rel, True
        if occupante is not None:
            continue
        abs_ = root / rel
        if abs_.exists():
            if _sha256_file(abs_) == sha256:
                return rel, True
            continue
        return rel, False
    raise RuntimeError(
        f"collisione irrisolvibile su {dest_rel} (sha256 {sha256[:12]}…)"
    )


def _candidati(client) -> list:
    """Allegati con importance=ALTA di entity in whitelist, non ancora proiettati."""

    entities = ", ".join(f"'{e}'" for e in PANEL_ENTITIES)
    sql = f"""
    SELECT a.msgid, a.sha256, a.nome_file, a.gcs_uri, a.size_bytes,
           m.entity_id, m.data_evento, c.primary_category
    FROM `{F_PEC_ALLEGATI}` a
    JOIN `{F_PEC_MESSAGES}` m USING (msgid)
    JOIN `{PROJECT}.hotelops.v_pec_classificazione_corrente` c USING (msgid)
    WHERE m.entity_id IN ({entities})
      AND c.importance = 'ALTA'
      AND a.gcs_uri IS NOT NULL
    """
    return list(client.query(sql).result())


def _gia_proiettate(client) -> set[str]:
    """projection_key già proiettate con successo.

    Solo COPIED/SKIPPED_EXISTS contano come "fatto": una riga FAILED (es.
    download GCS fallito per errore transitorio) deve restare candidata al
    retry nei run successivi, quindi non va filtrata fuori qui.
    """
    sql = (
        f"SELECT projection_key FROM `{F_PEC_PANEL_PROJECTIONS}` "
        f"WHERE status IN ('COPIED', 'SKIPPED_EXISTS')"
    )
    try:
        return {r.projection_key for r in client.query(sql).result()}
    except Exception:  # tabella non ancora creata: primo run
        return set()


def sync_panel(dry_run: bool = False, verify: bool = False) -> dict:
    from core.bq.client import get_client

    client = get_client()
    root = Path(PANEL_ROOT)
    run_id = f"panel-{uuid.uuid4().hex[:12]}"
    now = datetime.now()
    report = {"run_id": run_id, "copiati": 0, "skippati": 0, "falliti": 0,
              "oversize": 0, "dry_run": dry_run, "anomalie_verify": []}

    if not root.exists():
        raise FileNotFoundError(
            f"root pannello non trovato (Drive spento?): {root}"
        )

    esistenti = _gia_proiettate(client)
    rows: list[dict] = []
    claims: dict[str, str] = {}  # dest_rel -> sha256 assegnato in questo run

    for cand in _candidati(client):
        if cand.size_bytes and cand.size_bytes > PANEL_MAX_ATTACHMENT_BYTES:
            report["oversize"] += 1
            continue  # segnalato dal digest (allegati non sincronizzati)
        dest_rel = _destination_path(
            cand.entity_id, cand.primary_category, cand.data_evento, cand.nome_file
        )
        dest_rel, gia_presente = _resolve_dest(root, dest_rel, cand.sha256, claims)
        key = projection_key(cand.msgid, cand.sha256, str(dest_rel))
        if key in esistenti:
            continue
        dest_abs = root / dest_rel
        _assert_under_root(dest_abs, root)
        if gia_presente:
            status = "SKIPPED_EXISTS"
            report["skippati"] += 1
        elif dry_run:
            status = "COPIED"
            report["copiati"] += 1
            claims[str(dest_rel)] = cand.sha256
        else:
            try:
                dest_abs.parent.mkdir(parents=True, exist_ok=True)
                _download_gcs(cand.gcs_uri, dest_abs)
                status = "COPIED"
                report["copiati"] += 1
                claims[str(dest_rel)] = cand.sha256
            except Exception as e:
                log.warning("copia fallita %s: %s", cand.gcs_uri, e)
                # un download fallito a metà può lasciare un file parziale:
                # va rimosso, altrimenti un re-run lo scambierebbe per valido
                # (SKIPPED_EXISTS) invece di ritentare il download.
                dest_abs.unlink(missing_ok=True)
                status = "FAILED"
                report["falliti"] += 1
        rows.append({
            "projection_key": key, "msgid": cand.msgid, "sha256": cand.sha256,
            "entity_id": cand.entity_id, "gcs_uri": cand.gcs_uri,
            "destination_path": str(dest_rel), "run_id": run_id,
            "projected_at": now, "status": status,
        })

    validate_batch(rows, PecPanelProjectionRow, context="f_pec_panel_projections")
    if rows and not dry_run:
        from core.bq.write import bq_write_validated

        bq_write_validated(
            F_PEC_PANEL_PROJECTIONS,
            [PecPanelProjectionRow(**r) for r in rows], mode="append",
        )

    if verify:
        report["anomalie_verify"] = _verify(client, root)

    _scrivi_indice(root, client, dry_run)
    log.info("sync-panel: %s", report)
    return report


def _download_gcs(gcs_uri: str, dest: Path) -> None:
    from google.cloud import storage

    bucket_name, _, blob_path = gcs_uri.removeprefix("gs://").partition("/")
    storage.Client(project=PROJECT).bucket(bucket_name).blob(
        blob_path
    ).download_to_filename(str(dest))


def _verify(client, root: Path) -> list[str]:
    """Riconciliazione nei due sensi: riferisce, MAI cancella."""
    anomalie = []
    sql = (
        f"SELECT destination_path FROM `{F_PEC_PANEL_PROJECTIONS}` "
        f"WHERE status = 'COPIED'"
    )
    attesi = {r.destination_path for r in client.query(sql).result()}
    for rel in attesi:
        if not (root / rel).exists():
            anomalie.append(f"riga COPIED senza file: {rel}")
    su_disco = {
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file() and p.parts[len(root.parts)] in PANEL_ENTITIES
        and "PEC" in p.parts
    }
    for rel in sorted(su_disco - attesi):
        anomalie.append(f"file senza riga projection: {rel}")
    return anomalie


def _scrivi_indice(root: Path, client, dry_run: bool) -> None:
    """Copia leggibile e rigenerabile dell'indice — informativa, non autorevole."""
    if dry_run:
        return
    try:
        sql = (
            f"SELECT entity_id, destination_path, projected_at "
            f"FROM `{F_PEC_PANEL_PROJECTIONS}` WHERE status='COPIED' "
            f"ORDER BY projected_at DESC LIMIT 500"
        )
        righe = list(client.query(sql).result())
        testo = ["# Indice documenti proiettati (rigenerato, non autorevole)", ""]
        testo += [f"- `{r.destination_path}` ({r.projected_at:%Y-%m-%d})" for r in righe]
        (root / "_indice.md").write_text("\n".join(testo) + "\n")
    except Exception as e:  # l'indice non deve mai far fallire il run
        log.warning("indice non aggiornato: %s", e)
