"""Centralized Google Drive / rclone integration for the datahub.

Every pipeline that reads files from Drive must import DATAHUB_ROOT and the
sync helpers from here — do NOT hardcode the path or reimplement rclone.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from core.local_paths import resolve_datahub_root

DATAHUB_ROOT = resolve_datahub_root()

RCLONE_REMOTE = os.environ.get("HOTELOPS_RCLONE_REMOTE", "mywork")
DATAHUB_REMOTE_ROOT = f"{RCLONE_REMOTE}:00_hotelops_datahub"

log = logging.getLogger(__name__)


class RcloneError(RuntimeError):
    pass


def _remote(subpath: str) -> str:
    return f"{DATAHUB_REMOTE_ROOT}/{subpath.lstrip('/')}"


def _run(
    cmd: list[str], verb: str, *, dry_run: bool, verbose: bool, timeout: int
) -> None:
    if dry_run:
        cmd = cmd + ["--dry-run"]
    if verbose:
        cmd = cmd + ["-v"]
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=False, timeout=timeout
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        log.error(f"rclone {verb} failed (exit {result.returncode}): {stderr}")
        raise RcloneError(f"rclone {verb} failed (exit {result.returncode}): {stderr}")


def rclone_sync(
    remote_subpath: str,
    local_dest: Path,
    *,
    include: str | None = None,
    dry_run: bool = False,
    verbose: bool = False,
    timeout: int = 300,
) -> None:
    """Mirror a remote Drive subpath to a local folder. Raises RcloneError on failure."""
    if not dry_run:
        local_dest.mkdir(parents=True, exist_ok=True)
    cmd = ["rclone", "sync", _remote(remote_subpath), str(local_dest)]
    if include:
        cmd.extend(["--include", include])
    _run(cmd, "sync", dry_run=dry_run, verbose=verbose, timeout=timeout)


def rclone_copy(
    remote_subpath: str,
    local_dest: Path,
    *,
    include: str | None = None,
    dry_run: bool = False,
    verbose: bool = False,
    timeout: int = 300,
) -> None:
    """Copy (not sync) from remote to local. Does not delete extra files at dest."""
    if not dry_run:
        local_dest.mkdir(parents=True, exist_ok=True)
    cmd = ["rclone", "copy", _remote(remote_subpath), str(local_dest)]
    if include:
        cmd.extend(["--include", include])
    _run(cmd, "copy", dry_run=dry_run, verbose=verbose, timeout=timeout)


def rclone_copyto(
    remote_subpath: str,
    local_file: Path,
    *,
    dry_run: bool = False,
    verbose: bool = False,
    timeout: int = 300,
) -> None:
    """Copy a single remote file to a specific local file (like `cp` semantics)."""
    if not dry_run:
        local_file.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["rclone", "copyto", _remote(remote_subpath), str(local_file)]
    _run(cmd, "copyto", dry_run=dry_run, verbose=verbose, timeout=timeout)


def rclone_copy_to_remote(
    local_src: Path,
    remote_subpath: str,
    *,
    dry_run: bool = False,
    verbose: bool = False,
    timeout: int = 300,
) -> None:
    """Copy a local file or folder up to the remote datahub."""
    cmd = ["rclone", "copy", str(local_src), _remote(remote_subpath)]
    _run(cmd, "copy→remote", dry_run=dry_run, verbose=verbose, timeout=timeout)
