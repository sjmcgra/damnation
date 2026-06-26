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

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    cp .env.example .env
    echo ".env created from .env.example"
  else
    echo "ERROR: .env.example not found"
    exit 1
  fi
else
  echo ".env already exists"
fi

python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

python3 - <<'PY'
from pathlib import Path
from config import DB_PATH, THUMBNAIL_DIR
Path(DB_PATH.parent).mkdir(parents=True, exist_ok=True)
Path(THUMBNAIL_DIR).mkdir(parents=True, exist_ok=True)
print(f"Created directories: {DB_PATH.parent}, {THUMBNAIL_DIR}")
PY

echo "Installation complete. You are DAM'd"
echo "Activate the environment with: source .venv/bin/activate"
echo "Edit .env before running the application."
