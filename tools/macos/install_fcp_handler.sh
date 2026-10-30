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

set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "The DAMnation URL handler can only be installed on macOS." >&2
    exit 1
fi

DAMNATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
PYTHON_PATH="$DAMNATION_DIR/.venv/bin/python"
EXPORTER_PATH="$DAMNATION_DIR/fcpxml_export.py"
HANDLER_APP="$HOME/Applications/DAMnation Handler.app"
APPLE_SCRIPT_DIR="$(mktemp -d)"
APPLE_SCRIPT="$APPLE_SCRIPT_DIR/DAMnationHandler.applescript"
trap 'rm -f "$APPLE_SCRIPT"; rmdir "$APPLE_SCRIPT_DIR"' EXIT

if [[ ! -x "$PYTHON_PATH" ]]; then
    echo "Missing host virtual-environment Python: $PYTHON_PATH" >&2
    echo "Run ./install.sh first." >&2
    exit 1
fi
if [[ ! -f "$EXPORTER_PATH" ]]; then
    echo "Missing FCPXML exporter: $EXPORTER_PATH" >&2
    exit 1
fi
if ! command -v osacompile >/dev/null 2>&1; then
    echo "osacompile is required to build the URL handler." >&2
    exit 1
fi

mkdir -p "$HOME/Applications"
rm -rf "$HANDLER_APP"

"$PYTHON_PATH" - "$APPLE_SCRIPT" "$PYTHON_PATH" "$EXPORTER_PATH" <<'PY'
import json
import sys
from pathlib import Path

script_path, python_path, exporter_path = sys.argv[1:]
source = '''property pythonPath : @PYTHON_PATH@
property exporterPath : @EXPORTER_PATH@

on open location theURL
    try
        do shell script "/usr/bin/printf '%s' " & quoted form of theURL & " | /usr/bin/grep -Eq '^damnation://send-to-fcp[?]ids=[0-9,]+$'"
    on error
        return
    end try

    set commandText to quoted form of pythonPath & " " & quoted form of exporterPath & " --url " & quoted form of theURL & " --open"
    try
        set outputText to do shell script commandText & " 2>&1"
        set notificationText to "Sent clips to Final Cut Pro"
        set openFailure to ""
        repeat with outputLine in paragraphs of outputText
            if outputLine starts with "Sent " then set notificationText to outputLine
            if outputLine starts with "Error opening Final Cut Pro:" then set openFailure to outputLine
        end repeat
        if openFailure is not "" then
            display notification openFailure with title "DAMnation" subtitle "Final Cut Pro import failed"
        else
            display notification notificationText with title "DAMnation"
        end if
    on error errorMessage number errorNumber
        set firstLine to paragraph 1 of errorMessage
        display notification firstLine with title "DAMnation" subtitle "Final Cut Pro import failed"
    end try
end open location
'''
source = source.replace("@PYTHON_PATH@", json.dumps(python_path, ensure_ascii=False))
source = source.replace("@EXPORTER_PATH@", json.dumps(exporter_path, ensure_ascii=False))
Path(script_path).write_text(source, encoding="utf-8")
PY

osacompile -l AppleScript -o "$HANDLER_APP" "$APPLE_SCRIPT"
PLIST="$HANDLER_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Delete :CFBundleURLTypes' "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes array' "$PLIST"
/usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes:0 dict' "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLName string 'DAMnation URL'" "$PLIST"
/usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes:0:CFBundleURLSchemes array' "$PLIST"
/usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string damnation' "$PLIST"
/usr/libexec/PlistBuddy -c 'Delete :LSUIElement' "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c 'Add :LSUIElement bool true' "$PLIST"

LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
if [[ ! -x "$LSREGISTER" ]]; then
    echo "Launch Services registration utility not found: $LSREGISTER" >&2
    exit 1
fi
"$LSREGISTER" -f "$HANDLER_APP"
echo "Installed DAMnation URL handler at: $HANDLER_APP"
