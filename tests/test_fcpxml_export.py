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

import sqlite3
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from unittest.mock import Mock

import pytest

import fcpxml_export
from dam_utils import resolve_asset_path


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        ("24000/1001", "1001/24000s"),
        ("24/1", "1/24s"),
        ("25/1", "1/25s"),
        ("30000/1001", "1001/30000s"),
        ("30/1", "1/30s"),
        ("60000/1001", "1001/60000s"),
        ("60/1", "1/60s"),
    ],
)
def test_frame_duration_for_common_rates(rate, expected):
    assert fcpxml_export.frame_duration(Fraction(rate)) == expected


def test_rational_time_formats_decimal_durations():
    assert fcpxml_export.rational_time("1.25") == "5/4s"
    assert fcpxml_export.rational_time(Fraction(1001, 30000)) == "1001/30000s"


def test_file_url_percent_encodes_tricky_path_characters(tmp_path):
    media_path = tmp_path / "spaces # % ü (take).mov"
    expected = (
        "file://" + str(media_path.resolve()).replace(
            "spaces # % ü (take).mov",
            "spaces%20%23%20%25%20%C3%BC%20%28take%29.mov",
        )
    )
    assert fcpxml_export.file_url(media_path) == expected


def test_parse_asset_ids_accepts_integer_list_and_rejects_other_input():
    assert fcpxml_export.parse_asset_ids("12,15,40") == [12, 15, 40]
    assert fcpxml_export.parse_asset_ids("12,12,15") == [12, 15]
    for invalid in ("", "1, 2", "+2", "-1", "1.0", "1;touch", "abc", "1,"):
        with pytest.raises(ValueError, match="comma-separated integers"):
            fcpxml_export.parse_asset_ids(invalid)


def test_parse_send_url_requires_exact_supported_shape():
    assert fcpxml_export.parse_send_url("damnation://send-to-fcp?ids=12,15") == [12, 15]
    for invalid in (
        "https://send-to-fcp?ids=1",
        "damnation://wrong?ids=1",
        "damnation://send-to-fcp?ids=1&extra=2",
        "damnation://send-to-fcp?ids=1#fragment",
        "damnation://send-to-fcp?ids=1%2C%20two",
    ):
        with pytest.raises(ValueError):
            fcpxml_export.parse_send_url(invalid)


def test_shared_resolve_asset_path_exact_moved_and_missing(tmp_path):
    assets_root = tmp_path / "projects" / "demo" / "assets"
    exact = assets_root / "video" / "clip.mov"
    exact.parent.mkdir(parents=True)
    exact.write_bytes(b"video")
    moved = assets_root / "archive" / "old-name.mov"
    moved.parent.mkdir(parents=True)
    moved.write_bytes(b"video")

    assert resolve_asset_path("demo", "video/clip.mov", tmp_path / "projects") == (
        exact,
        "video/clip.mov",
    )
    assert resolve_asset_path("demo", "old-folder/old-name.mov", tmp_path / "projects") == (
        moved,
        "archive/old-name.mov",
    )
    missing, relative = resolve_asset_path(
        "demo", "missing/absent.mov", tmp_path / "projects"
    )
    assert missing == assets_root / "missing" / "absent.mov"
    assert relative is None


def test_xml_structure_for_video_audio_and_still_with_dam_metadata(tmp_path, monkeypatch):
    assets_root = tmp_path / "projects" / "demo" / "assets"
    assets_root.mkdir(parents=True)
    video_path = assets_root / "cinema.mov"
    second_video_path = assets_root / "broadcast.mov"
    audio_path = assets_root / "mix.wav"
    still_path = assets_root / "frame.png"
    for path in (video_path, second_video_path, audio_path, still_path):
        path.write_bytes(b"fixture")

    probe_data = {
        video_path: {
            "streams": [{
                "codec_type": "video", "width": 1920, "height": 1080,
                "avg_frame_rate": "24000/1001", "r_frame_rate": "24000/1001",
                "duration_ts": 24000, "time_base": "1/24000",
                "tags": {"timecode": "01:00:00:00"},
            }, {
                "codec_type": "audio", "channels": 2, "sample_rate": "48000",
            }],
            "format": {"duration": "1.001"},
        },
        second_video_path: {
            "streams": [{
                "codec_type": "video", "width": 1920, "height": 1080,
                "avg_frame_rate": "30000/1001", "duration": "2.5",
            }],
            "format": {"duration": "2.5"},
        },
        audio_path: {
            "streams": [{
                "codec_type": "audio", "channels": 1, "sample_rate": "44100",
                "duration": "3.25",
            }],
            "format": {"duration": "3.25"},
        },
    }

    def fake_probe(path):
        return probe_data.get(Path(path), {})

    monkeypatch.setattr(fcpxml_export, "probe_media", fake_probe)
    assets = [
        {
            "id": 1, "project": "demo", "filepath": "cinema.mov",
            "file_type": "video/quicktime", "tags": "Scene 01,hero",
            "review_status": "favorite",
        },
        {
            "id": 2, "project": "demo", "filepath": "broadcast.mov",
            "file_type": "video/quicktime", "tags": "scene 02",
            "review_status": "rejected",
        },
        {
            "id": 3, "project": "demo", "filepath": "mix.wav",
            "file_type": "audio/wav", "tags": "score",
            "review_status": "needs review",
        },
        {
            "id": 4, "project": "demo", "filepath": "frame.png",
            "file_type": "image/png", "width": 2048, "height": 1024,
            "tags": "reference",
        },
    ]

    document, count, skipped = fcpxml_export.build_fcpxml(
        assets, projects_root=tmp_path / "projects"
    )
    xml_bytes = ET.tostring(document.getroot())
    parsed = ET.fromstring(xml_bytes)
    resources = parsed.find("resources")
    event = parsed.find("library/event")
    assert count == 4
    assert skipped == []
    assert len(resources.findall("format")) == 3
    assert len(resources.findall("asset")) == 4
    assert len(event.findall("asset-clip")) == 4

    resource_by_name = {
        item.get("name"): item for item in resources.findall("asset")
    }
    cinema = resource_by_name["cinema.mov"]
    assert cinema.find("media-rep").get("kind") == "original-media"
    assert cinema.find("media-rep").get("src").startswith("file:///")
    assert cinema.get("hasVideo") == "1"
    assert cinema.get("hasAudio") == "1"
    assert cinema.get("duration") == "1/1s"
    assert cinema.get("start") == "18018/5s"
    assert cinema.get("audioRate") == "48kHz"
    assert resource_by_name["mix.wav"].get("hasVideo") == "0"
    assert resource_by_name["mix.wav"].get("hasAudio") == "1"
    assert "format" not in resource_by_name["mix.wav"].attrib
    assert resource_by_name["mix.wav"].get("audioRate") == "44.1kHz"
    assert resource_by_name["frame.png"].get("format")

    clips = event.findall("asset-clip")
    assert [clip.get("name") for clip in clips] == [
        "cinema.mov", "broadcast.mov", "mix.wav", "frame.png"
    ]
    assert clips[0].find("rating").get("value") == "favorite"
    assert {node.get("value") for node in clips[0].findall("keyword")} == {
        "Scene 01", "hero",
    }
    assert clips[1].find("rating").get("value") == "reject"
    assert any(node.get("value") == "status:needs review" for node in clips[2].findall("keyword"))


def test_build_skips_bundle_and_missing_assets(tmp_path, monkeypatch):
    bundle_file = tmp_path / "projects" / "demo" / "assets" / "project.motn"
    bundle_file.parent.mkdir(parents=True)
    bundle_file.write_bytes(b"bundle")
    monkeypatch.setattr(
        fcpxml_export,
        "probe_media",
        lambda path: {"streams": [{
            "codec_type": "video", "width": 1280, "height": 720,
            "avg_frame_rate": "24/1", "duration": "1",
        }]},
    )
    document, count, skipped = fcpxml_export.build_fcpxml(
        [
            {
                "id": 10, "project": "demo", "filepath": "project.motn",
                "file_type": "application/x-motion", "is_bundle": 1,
            },
            {
                "id": 11, "project": "demo", "filepath": "missing.mov",
                "file_type": "video/quicktime",
            },
        ],
        projects_root=tmp_path / "projects",
    )
    assert count == 0
    assert len(skipped) == 2
    assert "bundle assets" in skipped[0]
    assert "missing on disk" in skipped[1]
    assert document.getroot().find("resources/asset") is None


def test_load_assets_uses_sqlite_database_and_preserves_requested_order(tmp_path):
    db_path = tmp_path / "assets.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE assets (id INTEGER PRIMARY KEY, project TEXT, filepath TEXT)"
        )
        connection.executemany(
            "INSERT INTO assets (id, project, filepath) VALUES (?, ?, ?)",
            [(15, "demo", "fifteen.mov"), (12, "demo", "twelve.mov")],
        )
        connection.commit()
    finally:
        connection.close()

    rows = fcpxml_export.load_assets([12, 15], db_path)
    assert [row["id"] for row in rows] == [12, 15]
    assert [row["filepath"] for row in rows] == ["twelve.mov", "fifteen.mov"]


def test_cli_open_uses_argument_vector_and_event_override(tmp_path, monkeypatch, capsys):
    output_path = tmp_path / "send.fcpxml"
    build_options = {}
    monkeypatch.setattr(
        fcpxml_export,
        "load_assets",
        lambda asset_ids: [{"id": 12, "project": "demo", "filepath": "clip.mov"}],
    )

    def fake_build(assets, event_name=None):
        build_options["event_name"] = event_name
        root = ET.Element("fcpxml", {"version": fcpxml_export.FCPXML_VERSION})
        return ET.ElementTree(root), 1, []

    monkeypatch.setattr(fcpxml_export, "build_fcpxml", fake_build)
    open_process = Mock(return_value=None)
    monkeypatch.setattr(fcpxml_export.subprocess, "run", open_process)

    result = fcpxml_export.main([
        "--ids", "12", "--event", "Selected Event", "--output", str(output_path), "--open"
    ])

    assert result == 0
    assert build_options["event_name"] == "Selected Event"
    assert output_path.is_file()
    open_process.assert_called_once_with(
        ["open", "-a", "Final Cut Pro", str(output_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    captured = capsys.readouterr()
    assert "Sent 1 clips to Final Cut Pro" in captured.out
