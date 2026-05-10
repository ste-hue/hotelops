from __future__ import annotations

from pathlib import Path

SA_KEY_PATH = Path.home() / ".config" / "hotelops" / "workspace-controller.json"

DOMAIN = "panoramagroup.it"

SCOPE_GMAIL_READ = "https://www.googleapis.com/auth/gmail.readonly"
SCOPE_DRIVE_READ = "https://www.googleapis.com/auth/drive.readonly"
SCOPE_DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"

# Image extensions skipped during attachment extraction (noise reduction).
SKIP_ATTACHMENT_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".ico"}
