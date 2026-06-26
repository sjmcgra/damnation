#!/usr/bin/env bash
# dam_post_add.sh — Index assets into DAMnation after a manual dvc add workflow
#
# Use this when you've already run dvc add / git commit / dvc push manually
# and just need to update the DAMnation database.
#
# Usage:
#   ./dam_post_add.sh <project_name>
#   ./dam_post_add.sh <project_name> <asset_subdirectory>
#
# Examples:
#   ./dam_post_add.sh hokai_ep2                   # index all subdirs
#   ./dam_post_add.sh hokai_ep2 generated_images  # index one subdir

set -euo pipefail

DAM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <project_name> [asset_subdirectory]"
  exit 1
fi

PROJECT_NAME="$1"
ASSET_SUBDIR="${2:-}"

# Load PROJECTS_ROOT from .env
if [ -f "$DAM_DIR/.env" ]; then
  PROJECTS_ROOT=$(grep -E '^PROJECTS_ROOT=' "$DAM_DIR/.env" | head -1 | cut -d'=' -f2- | tr -d '"\r')
else
  echo "✗ No .env found at $DAM_DIR/.env"
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

if [ -n "$ASSET_SUBDIR" ]; then
  echo "🔍 Indexing $PROJECT_NAME / $ASSET_SUBDIR ..."
  python "$DAM_DIR/dam_index.py" index "$PROJECT_NAME" "$ASSET_SUBDIR"
else
  echo "🔍 Indexing all asset subdirectories for $PROJECT_NAME ..."
  for d in "$ASSETS_DIR"/*/; do
    [ -d "$d" ] || continue
    subdir="$(basename "$d")"
    echo "  → $subdir"
    python "$DAM_DIR/dam_index.py" index "$PROJECT_NAME" "$subdir" || true
  done
fi

echo
echo "✅ Done. Refresh DAMnation to see your assets."
