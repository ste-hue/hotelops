"""`hotelops drive manifest --folder <id>`: il manifest di una cartella Drive,
generato dall'inventario, mai scritto a mano. Spec 2026-10-17 drive-agent-friendly (P4).

Modello: HPAN26PIANO3/00_INDICE_e_RIEPILOGO_Archivio (una riga per file con
link, hash, stato) — qui le colonne sono le stesse per ogni cartella e arrivano
da f_drive_inventory + f_raw_objects, quindi il file non può mentire sul contenuto.
"""

from __future__ import annotations

from collections.abc import Callable

from core.config import DATASET, PROJECT

_T = f"`{PROJECT}.{DATASET}`"

_SQL = """
WITH ultimo AS (
  SELECT MAX(snapshot_date) AS snapshot_date FROM {t}.f_drive_inventory
),
cart AS (
  SELECT i.* FROM {t}.f_drive_inventory i JOIN ultimo USING (snapshot_date)
  WHERE i.parent_id = '{folder}'
),
dup AS (
  SELECT md5, COUNT(*) AS copie FROM {t}.f_drive_inventory JOIN ultimo USING (snapshot_date)
  WHERE md5 IS NOT NULL AND NOT is_shortcut GROUP BY md5
)
SELECT
  c.snapshot_date, c.file_id, c.name, c.mime_type, c.size_bytes, c.sha256, c.md5,
  c.modified_time, c.owner_email, c.is_folder, c.is_shortcut, c.shortcut_target_id,
  c.perm_anyone, c.perm_outside_domain, c.raw_object_id,
  IFNULL(d.copie, 1) AS copie,
  r.source_name
FROM cart c
LEFT JOIN dup d USING (md5)
LEFT JOIN {t}.f_raw_objects r ON r.raw_object_id = c.raw_object_id
ORDER BY c.is_folder DESC, c.name
"""

_PATH_SQL = """
SELECT path, name FROM {t}.f_drive_inventory
WHERE file_id = '{folder}' AND snapshot_date = (SELECT MAX(snapshot_date) FROM {t}.f_drive_inventory)
LIMIT 1
"""


def _fmt_size(n) -> str:
    if n is None:
        return "-"
    n = int(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def render_manifest(query: Callable[[str], list[dict]], folder_id: str) -> str:
    folder_id = folder_id.replace("'", "")
    rows = query(_SQL.format(t=_T, folder=folder_id))
    head = query(_PATH_SQL.format(t=_T, folder=folder_id))
    title = head[0]["path"] if head else folder_id
    if not rows:
        return (
            f"# Manifest — {title}\n\n"
            "Nessun oggetto nell'ultima fotografia: cartella vuota, oppure non condivisa "
            "con l'identità che esegue il job inventario.\n"
        )
    snap = rows[0]["snapshot_date"]
    out = [
        f"# Manifest — {title}",
        "",
        (
            f"Generato da `hotelops drive manifest` sulla fotografia del {snap}. "
            "Fonte: f_drive_inventory + f_raw_objects. Non modificare a mano: si rigenera."
        ),
        "",
        "| Nome | Tipo | Dim. | Modificato | sha256 | Lineage | Copie | Esposizione |",
        "|---|---|---:|---|---|---|---:|---|",
    ]
    for r in rows:
        tipo = (
            "cartella"
            if r["is_folder"]
            else (
                "scorciatoia"
                if r["is_shortcut"]
                else (r["mime_type"] or "").split("/")[-1]
            )
        )
        sha = (r["sha256"] or "")[:12] or "-"
        lin = (
            r["raw_object_id"][:8]
            + (f" ({r['source_name']})" if r.get("source_name") else "")
            if r["raw_object_id"]
            else "-"
        )
        esp = (
            "ANYONE"
            if r["perm_anyone"]
            else (
                ", ".join(r["perm_outside_domain"]) if r["perm_outside_domain"] else "-"
            )
        )
        mod = str(r["modified_time"])[:10] if r["modified_time"] else "-"
        link = f"[{r['name']}](https://drive.google.com/{'drive/folders' if r['is_folder'] else 'file/d'}/{r['file_id']})"
        copie = "" if r["is_folder"] or r["is_shortcut"] else str(r["copie"])
        out.append(
            f"| {link} | {tipo} | {_fmt_size(r['size_bytes'])} | {mod} | `{sha}` | {lin} | {copie} | {esp} |"
        )
    n_dup = sum(
        1
        for r in rows
        if not r["is_folder"] and not r["is_shortcut"] and int(r["copie"]) > 1
    )
    n_pub = sum(1 for r in rows if r["perm_anyone"])
    out += [
        "",
        f"Oggetti: {len(rows)} · con copie altrove: {n_dup} · pubblici: {n_pub}.",
        "",
    ]
    return "\n".join(out)
