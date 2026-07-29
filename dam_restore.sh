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
# dam_restore.sh -- Restore a specific file from a previous DVC version
#
# Usage:
#   ./dam_restore.sh <project> <relative_filepath> <git_commit> [--copy]
#
# Arguments:
#   project           Project name (e.g. hokai)
#   relative_filepath Path relative to assets/ (e.g. motion/gravity-drive.motn)
#   git_commit        Git commit hash from version history
#   --copy            Restore as a dated copy instead of overwriting current file
#
# Examples:
#   ./dam_restore.sh hokai motion/gravity-drive.motn abc1234
#   ./dam_restore.sh hokai motion/gravity-drive.motn abc1234 --copy

set -euo pipefail

DAM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
if [ $# -lt 3 ]; then
  echo "Usage: $0 <project> <relative_filepath> <git_commit> [--copy]"
  echo "  project           e.g. hokai"
  echo "  relative_filepath e.g. motion/gravity-drive.motn"
  echo "  git_commit        from DAMnation version history panel"
  echo "  --copy            restore as dated copy, don't overwrite current"
  exit 1
fi

PROJECT="$1"
REL_PATH="$2"
GIT_COMMIT="$3"
AS_COPY="${4:-}"

# Load PROJECTS_ROOT from .env
if [ -f "$DAM_DIR/.env" ]; then
  PROJECTS_ROOT=$(grep -E '^PROJECTS_ROOT=' "$DAM_DIR/.env" | head -1 | cut -d'=' -f2- | tr -d '"\r')
else
  echo "[x] No .env found at $DAM_DIR/.env"
  exit 1
fi

PROJECT_DIR="$PROJECTS_ROOT/$PROJECT"
ASSETS_DIR="$PROJECT_DIR/assets"
TARGET_FILE="$ASSETS_DIR/$REL_PATH"

# Derive the top-level subdir (DVC tracks at assets/<subdir>.dvc level)
# e.g. motion/return to hokai prime 360-4/file.motn -> motion
SUBDIR="$(echo "$REL_PATH" | cut -d'/' -f1)"
FILENAME="$(basename "$REL_PATH")"
# Path relative to the top-level subdir for manifest lookup
REL_TO_SUBDIR="$(echo "$REL_PATH" | cut -d'/' -f2-)"
DVC_FILE="$ASSETS_DIR/${SUBDIR}.dvc"

# Activate DAMnation venv (for python json parsing)
if [ -f "$DAM_DIR/.venv/bin/activate" ]; then
  source "$DAM_DIR/.venv/bin/activate"
fi

echo
echo "[dam] DAMnation restore"
echo "   Project  : $PROJECT"
echo "   File     : $REL_PATH"
echo "   Commit   : $GIT_COMMIT"
echo "   Mode     : $([ "$AS_COPY" = "--copy" ] && echo 'restore as copy' || echo 'restore in place')"
echo

# ---------------------------------------------------------------------------
# 1. Validate
# ---------------------------------------------------------------------------
if [ ! -d "$PROJECT_DIR" ]; then
  echo "[x] Project not found: $PROJECT_DIR"
  exit 1
fi

if [ ! -f "$DVC_FILE" ]; then
  echo "[x] No DVC tracking found for subdir: $SUBDIR"
  echo "    Expected: $DVC_FILE"
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. Get the .dvc manifest at the requested commit
# ---------------------------------------------------------------------------
echo "[1/4] Reading DVC manifest at commit $GIT_COMMIT..."
DVC_MANIFEST=$(git -C "$PROJECT_DIR" show "${GIT_COMMIT}:assets/${SUBDIR}.dvc" 2>/dev/null) || {
  echo "[x] Could not read assets/${SUBDIR}.dvc at commit $GIT_COMMIT"
  echo "    Make sure the commit hash is correct."
  exit 1
}

# Extract the directory md5 hash from the .dvc file
DIR_MD5=$(echo "$DVC_MANIFEST" | python3 -c "
import sys, yaml
data = yaml.safe_load(sys.stdin)
print(data['outs'][0]['md5'])
")

echo "    Directory hash: $DIR_MD5"

# ---------------------------------------------------------------------------
# 3. Find the specific file's hash in the directory manifest
# ---------------------------------------------------------------------------
echo "[2/4] Locating $FILENAME in directory manifest..."

# The directory manifest is stored in .dvc/cache as <dir_hash>.dir
DIR_HASH_PATH="$PROJECT_DIR/.dvc/cache/files/md5/${DIR_MD5:0:2}/${DIR_MD5:2}"

# If not in local cache, fetch it from remote
if [ ! -f "$DIR_HASH_PATH" ]; then
  echo "    Not in local cache, fetching directory manifest from remote..."
  cd "$PROJECT_DIR"
  dvc fetch --run-cache 2>/dev/null || true
fi

if [ ! -f "$DIR_HASH_PATH" ]; then
  echo "[x] Directory manifest not found in cache: $DIR_HASH_PATH"
  echo "    Try: cd $PROJECT_DIR && dvc fetch"
  exit 1
fi

# Parse the directory manifest to find our file's hash
FILE_MD5=$(python3 -c "
import json, sys
manifest = json.load(open('$DIR_HASH_PATH'))
rel_to_subdir = '$REL_TO_SUBDIR'
filename = '$FILENAME'
for entry in manifest:
    relpath = entry.get('relpath', '')
    if relpath == rel_to_subdir or relpath == filename:
        print(entry['md5'])
        sys.exit(0)
print('')
")

if [ -z "$FILE_MD5" ]; then
  echo "[x] File '$FILENAME' not found in this version's manifest."
  echo "    The file may not have existed at commit $GIT_COMMIT."
  exit 1
fi

echo "    File hash: $FILE_MD5"

# ---------------------------------------------------------------------------
# 4. Fetch the specific file from cache/remote
# ---------------------------------------------------------------------------
echo "[3/4] Fetching file content..."

FILE_CACHE_PATH="$PROJECT_DIR/.dvc/cache/files/md5/${FILE_MD5:0:2}/${FILE_MD5:2}"

if [ ! -f "$FILE_CACHE_PATH" ]; then
  echo "    Not in local cache, fetching from remote..."
  cd "$PROJECT_DIR"
  # Fetch just this specific file by its hash
  python3 -c "
import subprocess, sys
result = subprocess.run(
    ['dvc', 'fetch', '--run-cache'],
    cwd='$PROJECT_DIR', capture_output=True, text=True
)
" 2>/dev/null || true
fi

if [ ! -f "$FILE_CACHE_PATH" ]; then
  echo "[x] Could not retrieve file from cache or remote."
  echo "    Hash: $FILE_MD5"
  exit 1
fi

# ---------------------------------------------------------------------------
# 5. Restore
# ---------------------------------------------------------------------------
echo "[4/4] Restoring file..."

TIMESTAMP=$(date '+%Y-%m-%d_%H-%M-%S')

if [ "$AS_COPY" = "--copy" ]; then
  # Restore as a dated copy alongside the current file
  EXT="${FILENAME##*.}"
  BASE="${FILENAME%.*}"
  DEST="$ASSETS_DIR/$SUBDIR/${BASE}-restored-${TIMESTAMP}.${EXT}"
  cp "$FILE_CACHE_PATH" "$DEST"
  echo
  echo "[ok] Restored as copy:"
  echo "     $DEST"
  echo
  echo "Run dam_sync.sh to track and index the restored copy:"
  echo "  ./dam_sync.sh $PROJECT"
else
  # Restore in place -- back up current file first
  if [ -f "$TARGET_FILE" ]; then
    EXT="${FILENAME##*.}"
    BASE="${FILENAME%.*}"
    BACKUP="$ASSETS_DIR/$SUBDIR/${BASE}-backup-${TIMESTAMP}.${EXT}"
    cp "$TARGET_FILE" "$BACKUP"
    echo "    Backed up current file to: $(basename "$BACKUP")"
  fi
  cp "$FILE_CACHE_PATH" "$TARGET_FILE"
  echo
  echo "[ok] Restored in place: $TARGET_FILE"
  echo "     (backup saved alongside)"
  echo
  echo "Run dam_sync.sh to re-track and re-index:"
  echo "  ./dam_sync.sh $PROJECT"
fi
