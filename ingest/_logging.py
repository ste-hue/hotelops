"""Shared logging setup for ingest pipelines (banca and flussi)."""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path


def setup_logging(
    logger_name: str, log_dir: Path, verbose: bool = False
) -> logging.Logger:
    """Create a logger with console handler and optional file handler.

    Args:
        logger_name: Name for the logger and log file prefix.
        log_dir: Directory where log files are written (non-cloud only).
        verbose: If True, set DEBUG level; otherwise INFO.
    """
    # K_SERVICE is set automatically by Cloud Run; HOTELOPS_ENV=cloud is a
    # manual override for non-Cloud-Run cloud contexts/tests.
    is_cloud = os.getenv("HOTELOPS_ENV", "").lower() == "cloud" or bool(
        os.getenv("K_SERVICE")
    )
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    if not is_cloud:
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fh = logging.FileHandler(log_dir / f"{logger_name}_{ts}.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
    logger.addHandler(ch)
    return logger
