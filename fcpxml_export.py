#!/usr/bin/env python3
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

"""Build Final Cut Pro XML events from locally available DAMnation assets."""

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlsplit
from xml.etree import ElementTree as ET

from config import DB_PATH, PROJECTS_ROOT
from dam_utils import resolve_asset_path


FCPXML_VERSION = "1.10"
DEFAULT_OUTPUT_DIR = Path.home() / "Library" / "Caches" / "DAMnation" / "fcp"
FRAME_RATES = {
    Fraction(24000, 1001): "2398",
    Fraction(24, 1): "24",
    Fraction(25, 1): "25",
    Fraction(30000, 1001): "2997",
    Fraction(30, 1): "30",
    Fraction(60000, 1001): "5994",
    Fraction(60, 1): "60",
}
STILL_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".psd"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".mxf", ".webm"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".aif", ".aiff", ".flac", ".ogg"}
ID_PATTERN = re.compile(r"[0-9]+(?:,[0-9]+)*\Z")


def parse_asset_ids(value):
    """Parse comma-separated database IDs without accepting shell-like input."""
    if not value or not ID_PATTERN.fullmatch(value):
        raise ValueError("Asset IDs must be comma-separated integers (for example: 12,15,40)")
    return list(dict.fromkeys(int(part) for part in value.split(",")))


def parse_send_url(value):
    """Extract IDs from the one supported DAMnation custom URL."""
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise ValueError(f"Invalid DAMnation URL: {error}") from error
    if parsed.scheme != "damnation" or parsed.netloc != "send-to-fcp" or parsed.path or parsed.fragment:
        raise ValueError("URL must match damnation://send-to-fcp?ids=12,15,40")
    try:
        query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError as error:
        raise ValueError("URL query must contain only an ids parameter") from error
    if len(query) != 1 or query[0][0] != "ids":
        raise ValueError("URL must contain exactly one ids parameter")
    return parse_asset_ids(query[0][1])


def rational_time(value):
    """Format a seconds value as an FCPXML rational time string."""
    if isinstance(value, Fraction):
        seconds = value
    else:
        try:
            seconds = Fraction(str(value)).limit_denominator(1_000_000_000)
        except (ValueError, ZeroDivisionError) as error:
            raise ValueError(f"Invalid media duration: {value!r}") from error
    if seconds < 0:
        raise ValueError("Media time cannot be negative")
    return f"{seconds.numerator}/{seconds.denominator}s"


def parse_frame_rate(value):
    """Parse an ffprobe frame-rate fraction, returning None for unavailable rates."""
    try:
        rate = Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


def normalized_frame_rate(rate):
    """Normalize common NTSC rates despite minor ffprobe representation variance."""
    if rate is None:
        return None
    for known_rate in FRAME_RATES:
        if abs(float(rate) - float(known_rate)) < 0.001:
            return known_rate
    return rate


def frame_duration(rate):
    """Return the exact frame duration required by FCPXML."""
    normalized = normalized_frame_rate(rate)
    if normalized is None:
        raise ValueError("Video frame rate is unavailable")
    duration = 1 / normalized
    return rational_time(duration)


def timecode_to_seconds(timecode, rate):
    """Convert an ffprobe SMPTE timecode tag into a rational time value."""
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})[:;](\d{2})", timecode or "")
    if not match or rate is None:
        return None
    hours, minutes, seconds, frames = (int(value) for value in match.groups())
    normalized_rate = normalized_frame_rate(rate)
    nominal_rate = round(float(normalized_rate))
    frame_count = ((hours * 3600 + minutes * 60 + seconds) * nominal_rate) + frames
    if ";" in timecode and normalized_rate in {
        Fraction(30000, 1001),
        Fraction(60000, 1001),
    }:
        dropped_per_minute = 2 if nominal_rate == 30 else 4
        dropped_frames = dropped_per_minute * (hours * 60 + minutes - (hours * 60 + minutes) // 10)
        frame_count -= dropped_frames
    return Fraction(frame_count, 1) / normalized_rate


def file_url(path):
    """Create an absolute file URL with path characters encoded for XML consumers."""
    absolute_path = Path(path).expanduser().resolve()
    return "file://" + quote(absolute_path.as_posix(), safe="/")


def probe_media(path):
    """Return ffprobe stream and container metadata for a media file."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _fraction_from_probe(value):
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError, TypeError):
        return None


def _duration_from_probe(stream, probe):
    duration_ts = stream.get("duration_ts")
    time_base = _fraction_from_probe(stream.get("time_base"))
    if duration_ts not in (None, "N/A") and time_base:
        duration = int(duration_ts) * time_base
        if duration > 0:
            return duration
    for value in (stream.get("duration"), probe.get("format", {}).get("duration")):
        duration = _fraction_from_probe(value)
        if duration and duration > 0:
            return duration.limit_denominator(1_000_000_000)
    return None


def _classify_asset(asset, path):
    file_type = (asset.get("file_type") or "").lower()
    suffix = path.suffix.lower()
    if file_type.startswith("video/") or suffix in VIDEO_EXTENSIONS:
        return "video"
    if file_type.startswith("audio/") or suffix in AUDIO_EXTENSIONS:
        return "audio"
    if file_type.startswith("image/") or suffix in STILL_EXTENSIONS:
        return "still"
    return None


def _tags_for_asset(tags):
    if not tags:
        return []
    if isinstance(tags, (list, tuple, set)):
        values = tags
    else:
        raw = str(tags).strip()
        try:
            parsed = json.loads(raw)
            values = parsed if isinstance(parsed, list) else raw.replace(";", ",").split(",")
        except json.JSONDecodeError:
            values = raw.replace(";", ",").split(",")
    unique = []
    for value in values:
        tag = str(value).strip()
        if tag and tag not in unique:
            unique.append(tag)
    return unique


def _format_name(width, height, rate):
    normalized = normalized_frame_rate(rate)
    rate_label = FRAME_RATES.get(normalized)
    if rate_label is None:
        rate_label = str(round(float(normalized) * 100))
    return f"FFVideoFormat{height}p{rate_label}"


def _audio_rate(sample_rate):
    if not sample_rate:
        return None
    rate = int(sample_rate)
    khz = Fraction(rate, 1000)
    rate_text = str(float(khz)).rstrip("0").rstrip(".")
    return f"{rate_text}kHz"


def build_fcpxml(assets, projects_root=None, event_name=None, probe=None):
    """Build FCPXML and return (document, exported_count, skipped_messages)."""
    root_path = Path(projects_root) if projects_root is not None else PROJECTS_ROOT
    probe_file = probe or probe_media
    resources = ET.Element("resources")
    library = ET.Element("library")
    root = ET.Element("fcpxml", {"version": FCPXML_VERSION})
    root.append(resources)
    root.append(library)
    skipped = []
    exported_count = 0
    next_id = 1
    format_ids = {}
    events = OrderedDict()

    for asset in assets:
        asset_id = asset.get("id", "?")
        project = str(asset.get("project") or "")
        filepath = str(asset.get("filepath") or "")
        if asset.get("is_bundle"):
            skipped.append(f"Asset {asset_id} ({filepath}): bundle assets are not imported")
            continue
        path, resolved_relative = resolve_asset_path(project, filepath, root_path)
        if not path.is_file():
            skipped.append(f"Asset {asset_id} ({project}/{filepath}): file is missing on disk")
            continue
        media_kind = _classify_asset(asset, path)
        if media_kind is None:
            skipped.append(f"Asset {asset_id} ({filepath}): unsupported media type")
            continue

        try:
            metadata = probe_file(path)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            if media_kind != "still":
                skipped.append(f"Asset {asset_id} ({filepath}): ffprobe failed: {error}")
                continue
            metadata = {}

        streams = metadata.get("streams", [])
        video_stream = next(
            (stream for stream in streams
             if stream.get("codec_type") == "video" and not stream.get("disposition", {}).get("attached_pic")),
            None,
        )
        audio_stream = next(
            (stream for stream in streams if stream.get("codec_type") == "audio"),
            None,
        )
        if media_kind == "video" and video_stream is None:
            skipped.append(f"Asset {asset_id} ({filepath}): ffprobe found no video stream")
            continue
        if media_kind == "audio" and audio_stream is None:
            skipped.append(f"Asset {asset_id} ({filepath}): ffprobe found no audio stream")
            continue

        stream = video_stream if media_kind in {"video", "still"} else audio_stream
        duration = _duration_from_probe(stream or {}, metadata)
        if media_kind == "still":
            duration = Fraction(1, 1)
        if duration is None:
            skipped.append(f"Asset {asset_id} ({filepath}): media duration is unavailable")
            continue

        frame_rate = None
        width = None
        height = None
        if media_kind in {"video", "still"}:
            if video_stream:
                frame_rate = parse_frame_rate(video_stream.get("avg_frame_rate"))
                if frame_rate is None:
                    frame_rate = parse_frame_rate(video_stream.get("r_frame_rate"))
                width = video_stream.get("width")
                height = video_stream.get("height")
            if media_kind == "still":
                width = width or asset.get("width")
                height = height or asset.get("height")
                frame_rate = None
            if not width or not height:
                skipped.append(f"Asset {asset_id} ({filepath}): image/video resolution is unavailable")
                continue

        timecode = None
        timecode_rate = frame_rate
        if video_stream:
            timecode = (video_stream.get("tags") or {}).get("timecode")
        timecode = timecode or (metadata.get("format", {}).get("tags") or {}).get("timecode")
        start = timecode_to_seconds(timecode, timecode_rate) if timecode else None
        if start is None and stream:
            start = _fraction_from_probe(stream.get("start_time"))
        start = start if start is not None and start >= 0 else Fraction(0, 1)

        format_id = None
        if media_kind in {"video", "still"}:
            format_rate = frame_rate if media_kind == "video" else Fraction(1, 1)
            if format_rate is None:
                skipped.append(f"Asset {asset_id} ({filepath}): video frame rate is unavailable")
                continue
            format_key = (
                media_kind,
                int(width),
                int(height),
                normalized_frame_rate(format_rate),
            )
            if format_key not in format_ids:
                format_id = f"r{next_id}"
                next_id += 1
                format_ids[format_key] = format_id
                format_attrs = {
                    "id": format_id,
                    "name": (
                        "FFVideoFormatRateUndefined"
                        if media_kind == "still"
                        else _format_name(int(width), int(height), format_rate)
                    ),
                    "frameDuration": (
                        "1/1s" if media_kind == "still" else frame_duration(format_rate)
                    ),
                    "width": str(int(width)),
                    "height": str(int(height)),
                }
                if media_kind == "video":
                    format_attrs["colorSpace"] = "1-1-1 (Rec. 709)"
                ET.SubElement(resources, "format", format_attrs)
            else:
                format_id = format_ids[format_key]

        resource_id = f"r{next_id}"
        next_id += 1
        has_video = media_kind in {"video", "still"}
        has_audio = media_kind == "audio" or (media_kind == "video" and audio_stream is not None)
        asset_attrs = {
            "id": resource_id,
            "name": Path(resolved_relative or filepath).name,
            "uid": str(uuid.uuid4()).upper(),
            "start": rational_time(start),
            "duration": rational_time(duration),
            "hasVideo": "1" if has_video else "0",
            "hasAudio": "1" if has_audio else "0",
            "videoSources": "1" if has_video else "0",
            "audioSources": "1" if has_audio else "0",
        }
        if format_id is not None:
            asset_attrs["format"] = format_id
        if has_audio:
            channels = (audio_stream or {}).get("channels")
            sample_rate = (audio_stream or {}).get("sample_rate")
            if channels:
                asset_attrs["audioChannels"] = str(int(channels))
            formatted_rate = _audio_rate(sample_rate)
            if formatted_rate:
                asset_attrs["audioRate"] = formatted_rate
        asset_resource = ET.SubElement(resources, "asset", asset_attrs)
        ET.SubElement(
            asset_resource,
            "media-rep",
            {"kind": "original-media", "src": file_url(path)},
        )

        target_event_name = event_name or project
        event = events.get(target_event_name)
        if event is None:
            event = ET.SubElement(library, "event", {"name": target_event_name})
            events[target_event_name] = event
        clip_attrs = {
            "name": Path(resolved_relative or filepath).name,
            "ref": resource_id,
            "offset": "0s",
            "start": rational_time(start),
            "duration": rational_time(duration),
        }
        clip = ET.SubElement(event, "asset-clip", clip_attrs)
        for tag in _tags_for_asset(asset.get("tags")):
            ET.SubElement(
                clip,
                "keyword",
                {"start": "0s", "duration": rational_time(duration), "value": tag},
            )
        status = str(asset.get("review_status") or "").strip()
        if status == "favorite":
            ET.SubElement(clip, "rating", {"value": "favorite"})
        elif status == "rejected":
            ET.SubElement(clip, "rating", {"value": "reject"})
        elif status:
            ET.SubElement(
                clip,
                "keyword",
                {"start": "0s", "duration": rational_time(duration), "value": f"status:{status}"},
            )
        exported_count += 1

    return ET.ElementTree(root), exported_count, skipped


def load_assets(asset_ids, db_path=None):
    """Load selected asset records from the shared SQLite database."""
    database_path = Path(db_path) if db_path is not None else DB_PATH
    conn = sqlite3.connect(str(database_path))
    conn.row_factory = sqlite3.Row
    try:
        rows_by_id = {}
        for start in range(0, len(asset_ids), 900):
            batch = asset_ids[start:start + 900]
            placeholders = ",".join("?" for _ in batch)
            rows = conn.execute(
                f"SELECT * FROM assets WHERE id IN ({placeholders})",
                batch,
            ).fetchall()
            rows_by_id.update({row["id"]: dict(row) for row in rows})
    finally:
        conn.close()
    return [rows_by_id[asset_id] for asset_id in asset_ids if asset_id in rows_by_id]


def _default_output_path():
    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now().timestamp() - timedelta(days=7).total_seconds()
    for candidate in DEFAULT_OUTPUT_DIR.iterdir():
        if candidate.is_file() and candidate.stat().st_mtime < cutoff:
            candidate.unlink()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return DEFAULT_OUTPUT_DIR / f"DAMnation-{timestamp}-{uuid.uuid4().hex[:8]}.fcpxml"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export DAMnation assets as a Final Cut Pro event.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--ids", help="Comma-separated integer asset IDs")
    source.add_argument("--url", help="DAMnation send-to-FCP URL")
    parser.add_argument("--output", type=Path, help="FCPXML output file path")
    parser.add_argument("--event", help="Override the project name used for the event")
    parser.add_argument("--open", action="store_true", dest="open_after", help="Open the export in Final Cut Pro")
    parser.add_argument("--dry-run", action="store_true", help="Build and validate without writing or opening")
    args = parser.parse_args(argv)

    try:
        asset_ids = parse_send_url(args.url) if args.url is not None else parse_asset_ids(args.ids)
    except ValueError as error:
        parser.error(str(error))
    if args.open_after and args.dry_run:
        parser.error("--open cannot be used with --dry-run")

    assets = load_assets(asset_ids)
    found_ids = {asset["id"] for asset in assets}
    skipped = [
        f"Asset {asset_id}: no matching database record"
        for asset_id in asset_ids
        if asset_id not in found_ids
    ]
    document, exported_count, build_skips = build_fcpxml(assets, event_name=args.event)
    skipped.extend(build_skips)
    for message in skipped:
        print(f"Skipped: {message}", file=sys.stderr)
    if exported_count == 0:
        print("Error: no selected assets could be exported", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"Dry run: {exported_count} assets would be exported; {len(skipped)} skipped")
        return 0

    output_path = args.output.expanduser() if args.output else _default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.write(output_path, encoding="UTF-8", xml_declaration=True)

    if args.open_after:
        try:
            subprocess.run(
                ["open", "-a", "Final Cut Pro", str(output_path)],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            detail = getattr(error, "stderr", None) or str(error)
            print(f"Error opening Final Cut Pro: {detail.strip()}", file=sys.stderr)
            return 0
        print(f"Sent {exported_count} clips to Final Cut Pro")
    else:
        print(f"Exported {exported_count} assets to {output_path}")
    if skipped:
        print(f"Skipped {len(skipped)} assets; see stderr for details")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
