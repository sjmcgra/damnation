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
#   ./dam_sync.sh <project> [project2 ...]
#   ./dam_sync.sh <project> "optional commit message"
#   ./dam_sync.sh <project> "" generated_images   # one subdir only
#   ./dam_sync.sh <project1> <project2> -m "shared commit message"
#   ./dam_sync.sh <project> -s generated_images
#
# Multiple project names are synced in sequence. An argument is treated as a
# project if $PROJECTS_ROOT/<name> exists as a directory. Otherwise, for a
# single-project invocation, a non-project second arg is the commit message
# (backward compatible) and a third arg is an optional asset subdirectory.

set -euo pipefail

DAM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "Usage: $0 <project> [project2 ...] [-m \"commit message\"] [-s subdir]"
  echo "       $0 <project> [\"commit message\"] [asset_subdirectory]"
  exit 1
}

if [ -z "${1:-}" ]; then
  usage
fi

# Load PROJECTS_ROOT from .env (needed early to detect project names)
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

# Activate DAMnation venv once
if [ -f "$DAM_DIR/.venv/bin/activate" ]; then
  source "$DAM_DIR/.venv/bin/activate"
else
  echo "✗ DAMnation venv not found at $DAM_DIR/.venv"
  echo "  Run: cd $DAM_DIR && ./install.sh"
  exit 1
fi

PROJECTS=()
COMMIT_MSG=""
ONLY_SUBDIR=""
DEFAULT_COMMIT_MSG="DAM sync $(date '+%Y-%m-%d %H:%M:%S')"

# Parse arguments
i=1
while [ $i -le $# ]; do
  arg="${!i}"
  case "$arg" in
    -m|--message)
      i=$((i + 1))
      if [ $i -gt $# ]; then
        echo "✗ $arg requires a commit message"
        exit 1
      fi
      COMMIT_MSG="${!i}"
      ;;
    -s|--subdir)
      i=$((i + 1))
      if [ $i -gt $# ]; then
        echo "✗ $arg requires a subdirectory name"
        exit 1
      fi
      ONLY_SUBDIR="${!i}"
      ;;
    -h|--help)
      usage
      ;;
    -*)
      echo "✗ Unknown option: $arg"
      usage
      ;;
    *)
      if [ -d "$PROJECTS_ROOT/$arg" ]; then
        PROJECTS+=("$arg")
      else
        # Backward-compatible single-project mode:
        # non-project arg after the first project = commit message,
        # next optional arg = asset subdirectory.
        if [ ${#PROJECTS[@]} -eq 1 ] && [ -z "$COMMIT_MSG" ] && [ -z "$ONLY_SUBDIR" ]; then
          # Empty string means "use default message, next arg may be subdir"
          if [ -n "$arg" ]; then
            COMMIT_MSG="$arg"
          fi
          # Peek at next arg for subdir (legacy: project "" subdir)
          next=$((i + 1))
          if [ $next -le $# ]; then
            next_arg="${!next}"
            # Only consume as subdir if it is not another known project
            if [ ! -d "$PROJECTS_ROOT/$next_arg" ]; then
              ONLY_SUBDIR="$next_arg"
              i=$next
            fi
          fi
        else
          echo "✗ Not a project directory and not a valid option: $arg"
          echo "  Expected under: $PROJECTS_ROOT/$arg"
          exit 1
        fi
      fi
      ;;
  esac
  i=$((i + 1))
done

if [ ${#PROJECTS[@]} -eq 0 ]; then
  echo "✗ No project specified"
  usage
fi

if [ -z "$COMMIT_MSG" ]; then
  COMMIT_MSG="$DEFAULT_COMMIT_MSG"
fi

# ---------------------------------------------------------------------------
# Sync one project
# ---------------------------------------------------------------------------
sync_project() {
  local PROJECT_NAME="$1"
  local PROJECT_DIR="$PROJECTS_ROOT/$PROJECT_NAME"
  local ASSETS_DIR="$PROJECT_DIR/assets"

  if [ ! -d "$PROJECT_DIR" ]; then
    echo "✗ Project directory not found: $PROJECT_DIR"
    return 1
  fi

  echo
  echo "🎬 DAM sync: $PROJECT_NAME"
  echo "   $PROJECT_DIR"
  echo

  cd "$PROJECT_DIR"

  # 1. DVC add — track each asset subdirectory
  echo "📦 Tracking asset subdirectories with DVC..."

  local TRACKED=0
  local SKIPPED=0
  local SUBDIRS=()

  if [ -n "$ONLY_SUBDIR" ]; then
    SUBDIRS=("$ASSETS_DIR/$ONLY_SUBDIR")
  else
    # shellcheck disable=SC2206
    SUBDIRS=("$ASSETS_DIR"/*/)
  fi

  local subdir_path subdir dvc_file file_count
  for subdir_path in "${SUBDIRS[@]}"; do
    [ -d "$subdir_path" ] || continue
    subdir="$(basename "$subdir_path")"
    dvc_file="$ASSETS_DIR/${subdir}.dvc"

    file_count=$(find "$subdir_path" -type f ! -name '.gitkeep' ! -name '.DS_Store' ! -name 'Thumbs.db' | wc -l | tr -d ' ')

    if [ "$file_count" -eq 0 ]; then
      echo "  - $subdir (empty, skipping)"
      SKIPPED=$((SKIPPED + 1))
      continue
    fi

    if [ -f "$dvc_file" ]; then
      echo "  ~ $subdir ($file_count files, checking for changes)"
    else
      echo "  + $subdir ($file_count files, new)"
    fi
    dvc add "$subdir_path" && TRACKED=$((TRACKED + 1)) || echo "  ✗ Failed to track: $subdir"
  done

  echo "  ✓ Tracked $TRACKED subdirectories, skipped $SKIPPED empty"

  # 2. DVC push — upload to S3
  echo
  echo "☁️  Pushing to S3..."
  dvc push
  echo "  ✓ S3 push complete"

  # 3. Git — stage .dvc pointer files, commit, push
  echo
  echo "📝 Committing DVC pointer files to Git..."

  git add -A

  local LARGE_STAGED
  LARGE_STAGED=$(git diff --cached --name-only --diff-filter=A | while read -r f; do
    [ -f "$f" ] || continue
    size=$(git cat-file -s ":$f" 2>/dev/null || echo 0)
    if [ "$size" -gt 52428800 ]; then
      echo "$f ($((size / 1048576)) MB)"
    fi
  done)

  if [ -n "$LARGE_STAGED" ]; then
    echo "  ✗ Refusing to commit: staged files over 50MB detected:"
    echo "$LARGE_STAGED" | sed 's/^/      /'
    echo "    This usually means a directory (like master/) is missing"
    echo "    from .gitignore and got picked up by 'git add -A'."
    echo "    Run: git status --ignored   to inspect, then fix .gitignore."
    git restore --staged .
    return 1
  fi

  if git diff --cached --quiet; then
    echo "  ✓ Nothing new to commit"
  else
    git commit -m "$COMMIT_MSG"
    echo "  ✓ Committed: $COMMIT_MSG"
  fi

  git push origin main
  echo "  ✓ Pushed to GitHub"

  # 4. Index into DAMnation
  echo
  echo "🔍 Indexing into DAMnation..."

  if [ -n "$ONLY_SUBDIR" ]; then
    echo "  → $ONLY_SUBDIR"
    python "$DAM_DIR/dam_index.py" index "$PROJECT_NAME" "$ONLY_SUBDIR" || true
  else
    local d
    for d in "$ASSETS_DIR"/*/; do
      [ -d "$d" ] || continue
      subdir="$(basename "$d")"
      echo "  → $subdir"
      python "$DAM_DIR/dam_index.py" index "$PROJECT_NAME" "$subdir" || true
    done
  fi

  echo
  echo "✅ Sync complete for $PROJECT_NAME"
}

# Run for each project
FAILED=0
for PROJECT_NAME in "${PROJECTS[@]}"; do
  if ! sync_project "$PROJECT_NAME"; then
    echo "✗ Failed: $PROJECT_NAME"
    FAILED=$((FAILED + 1))
  fi
done

echo
if [ ${#PROJECTS[@]} -gt 1 ]; then
  if [ "$FAILED" -eq 0 ]; then
    echo "✅ All ${#PROJECTS[@]} projects synced. Refresh DAMnation to see your assets."
  else
    echo "⚠️  Finished with $FAILED failure(s) out of ${#PROJECTS[@]} projects."
    exit 1
  fi
else
  if [ "$FAILED" -eq 0 ]; then
    echo "✅ Sync complete! Refresh DAMnation to see your assets."
  else
    exit 1
  fi
fi
