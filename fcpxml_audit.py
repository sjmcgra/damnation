#!/usr/bin/env python3
"""
fcpxml_audit.py — Final Cut Pro Library Clip Usage Auditor
Part of the DAMnation toolchain

Parses an FCPXML (or Info.fcpxml inside a .fcpxmld bundle) and reports:
  • Clips in the event browser NOT used in any project timeline
  • Clips that ARE used, and in which projects
  • Usage ratio/percentage breakdown
  • Keyword tags (sc01, sc10, etc.) shown alongside each clip

No DAMnation database or .env required — this tool is self-contained.

Usage:
    python fcpxml_audit.py <path/to/Info.fcpxml>
    python fcpxml_audit.py <path/to/library.fcpxmld>
    python fcpxml_audit.py <path/to/Info.fcpxml> --csv out.csv --unused-only
    python fcpxml_audit.py <path/to/Info.fcpxml> --video-only
"""

import sys
import csv
import argparse
from pathlib import Path
from xml.etree import ElementTree as ET
from collections import defaultdict
from urllib.parse import unquote


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def strip_ns(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def src_to_filename(src):
    """Convert file:///Volumes/... URL to just the filename."""
    if not src:
        return ""
    path = unquote(src.replace("file://", ""))
    return Path(path).name


def format_duration(dur_str):
    """Convert FCPXML rational duration like '74240/12288s' to seconds string."""
    if not dur_str or not dur_str.endswith("s"):
        return dur_str or ""
    frac = dur_str[:-1]
    if "/" in frac:
        num, den = frac.split("/")
        try:
            secs = int(num) / int(den)
            return f"{secs:.2f}s"
        except (ValueError, ZeroDivisionError):
            return dur_str
    return dur_str


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def collect_resources(root):
    """Build id -> asset_info dict from <resources>."""
    resources = {}
    res_elem = root.find("resources")
    if res_elem is None:
        for elem in root.iter("resources"):
            res_elem = elem
            break

    if res_elem is not None:
        for child in res_elem:
            tag = strip_ns(child.tag)
            if tag == "asset":
                rid = child.get("id")
                if rid:
                    src = ""
                    media_rep = child.find("media-rep")
                    if media_rep is not None:
                        src = media_rep.get("src", "")
                    resources[rid] = {
                        "id":       rid,
                        "name":     child.get("name", "(unnamed)"),
                        "src":      src,
                        "filename": src_to_filename(src),
                        "duration": child.get("duration", ""),
                        "hasVideo": child.get("hasVideo", "0"),
                        "hasAudio": child.get("hasAudio", "0"),
                    }
    return resources


def collect_browser_clips(root):
    """
    Collect asset-clip elements that are DIRECT children of <event>
    (clips in the browser, not on a timeline).
    """
    browser_clips = {}

    for event in root.iter("event"):
        event_name = event.get("name", "(unnamed event)")
        for child in event:
            tag = strip_ns(child.tag)
            if tag != "asset-clip":
                continue
            ref = child.get("ref")
            if not ref:
                continue
            keywords = set()
            for kw in child.iter("keyword"):
                val = kw.get("value", "")
                if val:
                    keywords.add(val)
            has_rating = child.find("rating") is not None
            if ref not in browser_clips:
                browser_clips[ref] = {
                    "ref":        ref,
                    "name":       child.get("name", ""),
                    "event":      event_name,
                    "keywords":   keywords,
                    "has_rating": has_rating,
                    "mod_date":   child.get("modDate", ""),
                }
            else:
                browser_clips[ref]["keywords"].update(keywords)
                if has_rating:
                    browser_clips[ref]["has_rating"] = True

    return browser_clips


MEDIA_TIMELINE_TAGS = {"asset-clip", "video", "audio", "ref-clip", "mc-clip", "sync-clip"}


def collect_timeline_refs(root):
    """
    Walk every <sequence> inside every <project> inside every <event>.
    Only count refs from MEDIA tags to prevent effect assets being marked used.
    """
    used = defaultdict(set)

    for event in root.iter("event"):
        for project in event.iter("project"):
            proj_name = project.get("name", "(unnamed project)")
            for sequence in project.iter("sequence"):
                for elem in sequence.iter():
                    tag = strip_ns(elem.tag)
                    if tag in MEDIA_TIMELINE_TAGS:
                        ref = elem.get("ref")
                        if ref:
                            used[ref].add(proj_name)

    return {ref: sorted(projs) for ref, projs in used.items()}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

BAR_WIDTH = 32

def bar(ratio, width=BAR_WIDTH):
    filled = round(ratio * width)
    return "█" * filled + "░" * (width - filled)


def media_type(ref, resources):
    res = resources.get(ref, {})
    has_v = res.get("hasVideo", "0") == "1"
    has_a = res.get("hasAudio", "0") == "1"
    if has_v and has_a:
        return "both"
    if has_v:
        return "video"
    if has_a:
        return "audio"
    return "unknown"


def print_report(resources, browser_clips, timeline_refs, unused_only=False, video_only=False):
    if video_only:
        clip_ids = {ref for ref in browser_clips
                    if resources.get(ref, {}).get("hasVideo", "0") == "1"}
        filter_label = "  (video clips only)"
    else:
        clip_ids = set(browser_clips.keys())
        filter_label = ""

    total      = len(clip_ids)
    used_ids   = {ref for ref in clip_ids if ref in timeline_refs}
    unused_ids = clip_ids - used_ids
    n_used     = len(used_ids)
    n_unused   = len(unused_ids)
    pct_used   = n_used   / total * 100 if total else 0
    pct_unused = n_unused / total * 100 if total else 0

    all_video   = sum(1 for r in browser_clips if resources.get(r, {}).get("hasVideo", "0") == "1")
    all_audio   = sum(1 for r in browser_clips if resources.get(r, {}).get("hasVideo", "0") != "1"
                                               and resources.get(r, {}).get("hasAudio", "0") == "1")
    all_unknown = len(browser_clips) - all_video - all_audio

    def sort_key(ref):
        clip = browser_clips.get(ref, {})
        kws  = sorted(clip.get("keywords", set()))
        return (kws[0] if kws else "zzz", clip.get("name", ""))

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║        FCPXML CLIP USAGE AUDIT  ·  DAMnation                ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    print(f"  All browser clips    : {len(browser_clips)}")
    print(f"    ├─ video           : {all_video}")
    print(f"    ├─ audio only      : {all_audio}")
    print(f"    └─ unknown type    : {all_unknown}")
    if filter_label:
        print(f"\n  Filtered scope{filter_label} : {total}")
    else:
        print(f"\n  Auditing scope       : {total} clips")
    print()
    print(f"  Used in timeline     : {n_used}  ({pct_used:.1f}%)")
    print(f"  Unused               : {n_unused}  ({pct_unused:.1f}%)")
    print()
    print(f"  Used    [{bar(pct_used/100)}] {pct_used:.1f}%")
    print(f"  Unused  [{bar(pct_unused/100)}] {pct_unused:.1f}%")
    print()

    print("-" * 64)
    print(f"  UNUSED CLIPS  ({n_unused})")
    print("-" * 64)

    if not unused_ids:
        print("  ✓ All browser clips appear in at least one project timeline.")
    else:
        for ref in sorted(unused_ids, key=sort_key):
            clip  = browser_clips[ref]
            res   = resources.get(ref, {})
            fname = res.get("filename") or clip.get("name", ref)
            kws   = ", ".join(sorted(clip["keywords"])) or "—"
            rated = " ★" if clip["has_rating"] else ""
            dur   = format_duration(res.get("duration", ""))
            mod   = clip.get("mod_date", "")[:10]
            mtype = media_type(ref, resources)
            print(f"\n  ✗  {fname}{rated}  [{mtype}]")
            if kws != "—":
                print(f"      Scene tags : {kws}")
            if dur:
                print(f"      Duration   : {dur}")
            if mod:
                print(f"      Modified   : {mod}")

    if not unused_only:
        print()
        print("-" * 64)
        print(f"  USED CLIPS  ({n_used})")
        print("-" * 64)
        if not used_ids:
            print("  (none)")
        else:
            for ref in sorted(used_ids, key=sort_key):
                clip  = browser_clips[ref]
                res   = resources.get(ref, {})
                fname = res.get("filename") or clip.get("name", ref)
                kws   = ", ".join(sorted(clip["keywords"])) or "—"
                rated = " ★" if clip["has_rating"] else ""
                projs = ", ".join(timeline_refs.get(ref, []))
                dur   = format_duration(res.get("duration", ""))
                mtype = media_type(ref, resources)
                print(f"\n  ✓  {fname}{rated}  [{mtype}]")
                if kws != "—":
                    print(f"      Scene tags : {kws}")
                print(f"      Projects   : {projs}")
                if dur:
                    print(f"      Duration   : {dur}")

    print()
    print("-" * 64)
    print(f"  RATIO  used:{n_used}  unused:{n_unused}  total:{total}")
    print(f"  {pct_used:.1f}% of browser clips are on the timeline  |  "
          f"{pct_unused:.1f}% are sitting unused")
    print()


def write_csv(output_path, resources, browser_clips, timeline_refs, video_only=False):
    if video_only:
        clip_ids = [ref for ref in browser_clips
                    if resources.get(ref, {}).get("hasVideo", "0") == "1"]
    else:
        clip_ids = sorted(browser_clips)

    used_ids = {ref for ref in clip_ids if ref in timeline_refs}
    rows = []
    for ref in clip_ids:
        clip  = browser_clips[ref]
        res   = resources.get(ref, {})
        rows.append({
            "ref":        ref,
            "filename":   res.get("filename") or clip.get("name", ref),
            "status":     "USED" if ref in used_ids else "UNUSED",
            "scene_tags": "; ".join(sorted(clip["keywords"])),
            "favorited":  "yes" if clip["has_rating"] else "no",
            "duration":   format_duration(res.get("duration", "")),
            "projects":   "; ".join(timeline_refs.get(ref, [])),
            "event":      clip.get("event", ""),
            "mod_date":   clip.get("mod_date", "")[:10],
            "src":        res.get("src", ""),
        })
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys() if rows else [])
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✓ CSV written → {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Audit an FCPXML for unused library clips."
    )
    parser.add_argument("fcpxml",
                        help="Path to Info.fcpxml or .fcpxmld bundle")
    parser.add_argument("--csv",         metavar="FILE",
                        help="Also write results to CSV")
    parser.add_argument("--unused-only", action="store_true",
                        help="Show only unused clips in terminal output")
    parser.add_argument("--video-only",  action="store_true",
                        help="Limit audit to video-bearing clips")
    args = parser.parse_args()

    fcpxml_path = Path(args.fcpxml).expanduser().resolve()

    # Allow pointing at the .fcpxmld bundle directly
    if fcpxml_path.is_dir() and fcpxml_path.suffix == ".fcpxmld":
        candidate = fcpxml_path / "Info.fcpxml"
        if candidate.exists():
            fcpxml_path = candidate
        else:
            print(f"Error: no Info.fcpxml inside {fcpxml_path}", file=sys.stderr)
            sys.exit(1)

    if not fcpxml_path.exists():
        print(f"Error: file not found: {fcpxml_path}", file=sys.stderr)
        sys.exit(1)

    print(f"\n  Parsing {fcpxml_path.name} ...", end=" ", flush=True)
    try:
        tree = ET.parse(fcpxml_path)
    except ET.ParseError as e:
        print(f"\nError: XML parse failure — {e}", file=sys.stderr)
        sys.exit(1)

    root = tree.getroot()
    print("done.")

    resources     = collect_resources(root)
    browser_clips = collect_browser_clips(root)
    timeline_refs = collect_timeline_refs(root)

    print(f"  <asset> records in <resources> : {len(resources)}")
    print(f"  Clips in event browser         : {len(browser_clips)}")
    print(f"  Unique asset refs on timelines : {len(timeline_refs)}")

    if not browser_clips:
        print("\n  Warning: no browser clips found. Check that the FCPXML contains")
        print("  <asset-clip> elements as direct children of <event>.\n")
        sys.exit(0)

    print_report(resources, browser_clips, timeline_refs,
                 unused_only=args.unused_only, video_only=args.video_only)

    if args.csv:
        write_csv(args.csv, resources, browser_clips, timeline_refs,
                  video_only=args.video_only)


if __name__ == "__main__":
    main()
