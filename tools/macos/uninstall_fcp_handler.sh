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
    echo "The DAMnation URL handler can only be uninstalled on macOS." >&2
    exit 1
fi

HANDLER_APP="$HOME/Applications/DAMnation Handler.app"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"

if [[ -d "$HANDLER_APP" ]]; then
    if [[ -x "$LSREGISTER" ]]; then
        "$LSREGISTER" -u "$HANDLER_APP"
    fi
    rm -rf "$HANDLER_APP"
    echo "Removed DAMnation URL handler."
else
    echo "DAMnation URL handler is not installed."
fi
