# DAMnation -- Self-hosted Digital Asset Management
# Copyright (C) 2026 Sean McGrath (github.com/sjmcgra)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# See LICENSE for the full license text, or visit:
# https://www.gnu.org/licenses/gpl-3.0.html
#
# Built with DAMnation -- powering Hokai (hokaiprime.com)

"""ffprobe discovery tests for the macOS URL handler's minimal PATH."""

from unittest.mock import Mock

import fcpxml_export


def test_find_ffprobe_prefers_explicit_env(monkeypatch):
    monkeypatch.setenv("FFPROBE", "/custom/ffprobe")
    assert fcpxml_export.find_ffprobe() == "/custom/ffprobe"


def test_find_ffprobe_falls_back_when_path_has_no_ffprobe(monkeypatch, tmp_path):
    fake = tmp_path / "ffprobe"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.delenv("FFPROBE", raising=False)
    monkeypatch.setattr(fcpxml_export.shutil, "which", lambda name: None)
    monkeypatch.setattr(fcpxml_export, "FFPROBE_FALLBACK_DIRS", (str(tmp_path),))
    assert fcpxml_export.find_ffprobe() == str(fake)


def test_find_ffprobe_returns_bare_name_when_nothing_found(monkeypatch, tmp_path):
    monkeypatch.delenv("FFPROBE", raising=False)
    monkeypatch.setattr(fcpxml_export.shutil, "which", lambda name: None)
    monkeypatch.setattr(fcpxml_export, "FFPROBE_FALLBACK_DIRS", (str(tmp_path),))
    assert fcpxml_export.find_ffprobe() == "ffprobe"


def test_probe_media_runs_the_resolved_ffprobe(monkeypatch):
    monkeypatch.setenv("FFPROBE", "/custom/ffprobe")
    run = Mock(return_value=Mock(stdout="{}"))
    monkeypatch.setattr(fcpxml_export.subprocess, "run", run)
    assert fcpxml_export.probe_media("clip.mov") == {}
    assert run.call_args.args[0][0] == "/custom/ffprobe"
