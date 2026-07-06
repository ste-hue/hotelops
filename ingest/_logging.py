"""Shared logging setup for ingest pipelines (banca and flussi)."""

import logging
from datetime import datetime
from pathlib import Path


def setup_logging(
    logger_name: str, log_dir: Path, verbose: bool = False
) -> logging.Logger:
    """Create a logger with file + console handlers.

    Args:
        logger_name: Name for the logger and log file prefix.
        log_dir: Directory where log files are written. If None (e.g.
            promotion mode without --datahub), the file handler is skipped.
        verbose: If True, set DEBUG level; otherwise INFO.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / f"{logger_name}_{ts}.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.addHandler(ch)
    return logger
