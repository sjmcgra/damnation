#!/usr/bin/env bash
# DAMnation -- Self-hosted Digital Asset Management
# Copyright (C) 2026 Sean McGrath (github.com/sjmcgra)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# See LICENSE for the full license text.
# Built with DAMnation -- powering Hokai (hokaiprime.com)
#
# dam_sync.sh — Full DVC + Git + DAMnation sync
#
# Runs the complete asset workflow in one command:
#   1. dvc add   — track each asset subdirectory
#   2. dvc push  — upload content to S3
#   3. git add / commit / push — commit the .dvc pointer files
#   4. dam_index.py — index all asset subdirectories into DAMnation
#
# DVC tracks at the subdirectory level (one .dvc file per subdir).
# This gives per-subdirectory version history without a .dvc file per asset.
#
# Usage:
#   ./dam_sync.sh <project_name>
#   ./dam_sync.sh <project_name> "optional commit message"
#   ./dam_sync.sh <project_name> "" generated_images   # one subdir only

set -euo pipefail

DAM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <project_name> [commit message] [asset_subdirectory]"
  exit 1
fi

PROJECT_NAME="$1"
COMMIT_MSG="${2:-"DAM sync $(date '+%Y-%m-%d %H:%M:%S')"}";
ONLY_SUBDIR="${3:-}"

# Load PROJECTS_ROOT from .env
if [ -f "$DAM_DIR/.env" ]; then
  PROJECTS_ROOT=$(grep -E '^PROJECTS_ROOT=' "$DAM_DIR/.env" | head -1 | cut -d'=' -f2- | tr -d '"\r')
else
  echo "✗ No .env found at $DAM_DIR/.env"
  exit 1
fi

if [ -z "${PROJECTS_ROOT:-}" ]; then
  echo "✗ PROJECTS_ROOT not set in .env"
  exit 1
fi

PROJECT_DIR="$PROJECTS_ROOT/$PROJECT_NAME"
ASSETS_DIR="$PROJECT_DIR/assets"

if [ ! -d "$PROJECT_DIR" ]; then
  echo "✗ Project directory not found: $PROJECT_DIR"
  exit 1
fi

# Activate DAMnation venv
if [ -f "$DAM_DIR/.venv/bin/activate" ]; then
  source "$DAM_DIR/.venv/bin/activate"
else
  echo "✗ DAMnation venv not found at $DAM_DIR/.venv"
  echo "  Run: cd $DAM_DIR && ./install.sh"
  exit 1
fi

echo
echo "🎬 DAM sync: $PROJECT_NAME"
echo "   $PROJECT_DIR"
echo

cd "$PROJECT_DIR"

# ---------------------------------------------------------------------------
# 1. DVC add — track each asset subdirectory
# ---------------------------------------------------------------------------
echo "📦 Tracking asset subdirectories with DVC..."

TRACKED=0
SKIPPED=0

if [ -n "$ONLY_SUBDIR" ]; then
  SUBDIRS=("$ASSETS_DIR/$ONLY_SUBDIR")
else
  SUBDIRS=("$ASSETS_DIR"/*/)
fi

for subdir_path in "${SUBDIRS[@]}"; do
  [ -d "$subdir_path" ] || continue
  subdir="$(basename "$subdir_path")"
  dvc_file="$ASSETS_DIR/${subdir}.dvc"

  # Check if directory has any real files to track
  file_count=$(find "$subdir_path" -type f ! -name '.gitkeep' ! -name '.DS_Store' ! -name 'Thumbs.db' | wc -l | tr -d ' ')

  if [ "$file_count" -eq 0 ]; then
    echo "  - $subdir (empty, skipping)"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  if [ -f "$dvc_file" ]; then
    echo "  = $subdir ($file_count files, already tracked)"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  echo "  + $subdir ($file_count files)"
  dvc add "$subdir_path" && TRACKED=$((TRACKED + 1)) || echo "  ✗ Failed to track: $subdir"
done

echo "  ✓ Tracked $TRACKED subdirectories, skipped $SKIPPED empty"

# ---------------------------------------------------------------------------
# 2. DVC push — upload to S3
# ---------------------------------------------------------------------------
echo
echo "☁️  Pushing to S3..."
dvc push
echo "  ✓ S3 push complete"

# ---------------------------------------------------------------------------
# 3. Git — stage .dvc pointer files, commit, push
# ---------------------------------------------------------------------------
echo
echo "📝 Committing DVC pointer files to Git..."

git add -A
if git diff --cached --quiet; then
  echo "  ✓ Nothing new to commit"
else
  git commit -m "$COMMIT_MSG"
  echo "  ✓ Committed: $COMMIT_MSG"
fi

git push origin main
echo "  ✓ Pushed to GitHub"

# ---------------------------------------------------------------------------
# 4. Index into DAMnation
# ---------------------------------------------------------------------------
echo
echo "🔍 Indexing into DAMnation..."

if [ -n "$ONLY_SUBDIR" ]; then
  echo "  → $ONLY_SUBDIR"
  python "$DAM_DIR/dam_index.py" index "$PROJECT_NAME" "$ONLY_SUBDIR" || true
else
  for d in "$ASSETS_DIR"/*/; do
    [ -d "$d" ] || continue
    subdir="$(basename "$d")"
    echo "  → $subdir"
    python "$DAM_DIR/dam_index.py" index "$PROJECT_NAME" "$subdir" || true
  done
fi

echo
echo "✅ Sync complete! Refresh DAMnation to see your assets."
