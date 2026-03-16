#!/usr/bin/env bash
# Sync Notion journal → Obsidian vault
# Usage: ./run_notion.sh [--days N] [--today] [--from YYYY-MM-DD] [--dry-run]
set -e
cd "$(dirname "$0")"
source ~/.virtualenvs/hotelops_core/bin/activate
python -m pipelines.notion.sync "$@"
