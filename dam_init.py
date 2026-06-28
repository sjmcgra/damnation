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
"""
dam_init.py -- Initialize a new DAMnation project

Creates the opinionated directory structure, initializes git and DVC,
creates (or reuses) an S3 bucket, configures the DVC remote, creates
a private GitHub repo, and writes a post-add hook script.

DAMnation is opinionated toward S3-compatible object storage.
Backblaze B2 is supported via its S3-compatible API endpoint -- no
extra dependencies required, just set STORAGE_PROVIDER=backblaze and
supply your B2 endpoint and credentials in .env.

Usage:
    python dam_init.py <project_name>
    python dam_init.py <project_name> --projects-root /path/to/projects
    python dam_init.py <project_name> --bucket my-bucket --provider backblaze

Prerequisites:
    - git
    - dvc[s3]  (pip install dvc[s3])
    - gh CLI   (https://cli.github.com) authenticated via gh auth login
    - aws CLI  (AWS S3 only -- not required for Backblaze)
    - DAMnation .env configured (or pass --bucket / --projects-root)
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from config import PROJECTS_ROOT, GH_ORG

# ---------------------------------------------------------------------------
# Directory tree
# ---------------------------------------------------------------------------

ASSET_DIRS = [
    "3d_models", "audacity", "audio", "character_reference",
    "final_cut_exports", "garageband", "generated_audio",
    "generated_images", "generated_video", "images", "lip_sync_out",
    "location_reference", "motion", "motion_out", "photoshop",
    "photoshop_export", "upscaled_video", "video",
]

FINAL_CUT_DIRS = [
    "final_cut/FCP_Cache",
    "final_cut/FCP_Libraries",
    "final_cut/FCP_Media",
]

OTHER_DIRS = ["master"]

# ---------------------------------------------------------------------------
# .gitignore written into the project root
# ---------------------------------------------------------------------------

PROJECT_GITIGNORE = """\
# DAMnation project -- git tracks only .dvc pointer files and config.
# All actual asset content is managed by DVC and stored in S3-compatible storage.

# Ignore asset content inside each subdirectory
assets/*/

# Keep .dvc pointer files at the assets/ level (e.g. assets/generated_images.dvc)
!assets/*.dvc

# Keep .gitkeep files so empty dirs are tracked
!assets/*/.gitkeep

# Final Cut Pro -- cache and media can be enormous, never commit
final_cut/

# DVC internal cache (local only)
.dvc/cache/
.dvc/tmp/

# OS noise
.DS_Store
Thumbs.db

# Python
__pycache__/
*.py[cod]
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(cmd, cwd=None, check=True, capture=False):
    """Run a shell command, print it, and return CompletedProcess."""
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, check=check,
                          capture_output=capture, text=True)


def run_silent(cmd, cwd=None):
    """Run a command silently, return (returncode, stdout, stderr)."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def check_prerequisites(provider="aws"):
    """Abort early if required tools are missing."""
    required = ["git", "dvc", "gh"]
    if provider == "aws":
        required.append("aws")
    missing = [t for t in required if shutil.which(t) is None]
    if missing:
        print(f"\n[x] Missing required tools: {', '.join(missing)}")
        print("  Install them before running dam_init.py")
        print("  - dvc:  pip install dvc[s3]")
        print("  - gh:   https://cli.github.com")
        if provider == "aws":
            print("  - aws:  https://aws.amazon.com/cli/")
        sys.exit(1)


def ensure_s3_bucket(bucket, region, provider="aws"):
    """Create S3 bucket if it does not already exist.

    Backblaze B2 does not support bucket creation via the S3-compatible API.
    For B2, create the bucket manually in the Backblaze console first.
    """
    if provider == "backblaze":
        print(f"  [i] Backblaze: bucket creation via API not supported.")
        print(f"      Create s3://{bucket} manually at backblaze.com if it does not exist.")
        return
    rc, _, _ = run_silent(["aws", "s3", "ls", f"s3://{bucket}"])
    if rc == 0:
        print(f"  [ok] S3 bucket already exists: s3://{bucket}")
        return
    print(f"  Creating S3 bucket: s3://{bucket} in {region}")
    cmd = ["aws", "s3", "mb", f"s3://{bucket}", "--region", region]
    if region != "us-east-1":
        cmd += ["--create-bucket-configuration", f"LocationConstraint={region}"]
    run(cmd)


def init_git(project_path, project_name, gh_org, github_private, adopt=False):
    """git init, initial commit, create GitHub repo, push."""
    git_dir = project_path / ".git"
    if adopt and git_dir.exists():
        print("  [ok] Git already initialized -- skipping git init")
    else:
        run(["git", "init"], cwd=project_path)
        run(["git", "checkout", "-b", "main"], cwd=project_path)

    gitignore_path = project_path / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(PROJECT_GITIGNORE)
        print("  [ok] Wrote .gitignore")
    else:
        print("  [ok] .gitignore already exists -- leaving untouched")

    rc, remotes, _ = run_silent(["git", "remote"], cwd=project_path)
    if adopt and "origin" in remotes.split():
        print("  [ok] Git remote already configured -- skipping GitHub repo creation")
        return

    run(["git", "add", "-A"], cwd=project_path)
    rc, _, _ = run_silent(["git", "diff", "--cached", "--quiet"], cwd=project_path)
    if rc != 0:
        run(["git", "commit", "-m", "chore: init project"], cwd=project_path)

    visibility = "--private" if github_private else "--public"
    run(["gh", "repo", "create", f"{gh_org}/{project_name}",
         visibility, "--source", str(project_path), "--remote", "origin", "--push"],
        cwd=project_path)
    print(f"  [ok] GitHub repo created: github.com/{gh_org}/{project_name}")


def init_dvc(project_path, project_name, bucket, region,
             provider="aws", endpoint_url="", adopt=False):
    """dvc init, configure S3-compatible remote, commit config."""
    dvc_dir = project_path / ".dvc"
    if adopt and dvc_dir.exists():
        print("  [ok] DVC already initialized -- checking remote...")
        rc, out, _ = run_silent(["dvc", "remote", "list"], cwd=project_path)
        if out.strip():
            print("  [ok] DVC remote already configured -- skipping")
            return
    else:
        run(["dvc", "init"], cwd=project_path)

    remote_name = "s3remote"
    remote_url  = f"s3://{bucket}/{project_name}"
    run(["dvc", "remote", "add", "-d", remote_name, remote_url], cwd=project_path)
    run(["dvc", "remote", "modify", remote_name, "region", region], cwd=project_path)

    if provider == "backblaze" and endpoint_url:
        run(["dvc", "remote", "modify", remote_name,
             "endpointurl", endpoint_url], cwd=project_path)
        print(f"  [ok] Backblaze endpoint: {endpoint_url}")

    commit_msg = f"chore: init dvc with {'backblaze' if provider == 'backblaze' else 's3'} remote"
    run(["git", "add", ".dvc/config", ".dvcignore"], cwd=project_path)
    run(["git", "commit", "-m", commit_msg], cwd=project_path)
    run(["git", "push", "origin", "main"], cwd=project_path)
    print(f"  [ok] DVC remote: {remote_url}")


def write_dam_sync(project_path, project_name, dam_dir):
    pass  # dam_sync.sh lives in the damnation repo root


def write_post_add_hook(project_path, project_name, dam_dir):
    pass  # dam_post_add.sh lives in the damnation repo root


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    dam_dir = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(
        description="Initialize a new DAMnation-managed project."
    )
    parser.add_argument("project_name",
                        help="Short project name, e.g. hokai_ep2")
    parser.add_argument("--projects-root", default=str(PROJECTS_ROOT),
                        help=f"Root directory for all projects (default: {PROJECTS_ROOT})")
    parser.add_argument("--bucket", default=os.getenv("DVC_S3_BUCKET", ""),
                        help="Storage bucket name (or set DVC_S3_BUCKET in .env)")
    parser.add_argument("--region", default=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
                        help="Storage region (default: us-east-1)")
    parser.add_argument("--provider",
                        choices=["aws", "backblaze"],
                        default=os.getenv("STORAGE_PROVIDER", "aws"),
                        help="Storage provider: aws (default) or backblaze. "
                             "Both use the S3-compatible API. "
                             "Backblaze requires --endpoint-url or B2_ENDPOINT_URL in .env.")
    parser.add_argument("--endpoint-url",
                        default=os.getenv("B2_ENDPOINT_URL", ""),
                        help="S3-compatible endpoint URL (Backblaze only, "
                             "e.g. https://s3.us-west-004.backblazeb2.com)")
    parser.add_argument("--gh-org", default=GH_ORG,
                        help=f"GitHub org or username (default: {GH_ORG})")
    parser.add_argument("--adopt", action="store_true",
                        help="Adopt an existing project directory -- skips dir creation, "
                             "wires up git, DVC, and GitHub non-destructively.")
    parser.add_argument("--public", action="store_true",
                        help="Create GitHub repo as public (default: private)")
    args = parser.parse_args()

    if not args.bucket:
        print("\n[x] Storage bucket name required.")
        print("  Set DVC_S3_BUCKET in your .env or pass --bucket <name>")
        sys.exit(1)

    if args.provider == "backblaze" and not args.endpoint_url:
        print("\n[x] Backblaze requires an endpoint URL.")
        print("  Set B2_ENDPOINT_URL in your .env or pass --endpoint-url")
        print("  Example: https://s3.us-west-004.backblazeb2.com")
        sys.exit(1)

    project_name   = args.project_name
    projects_root  = Path(args.projects_root).expanduser()
    project_path   = projects_root / project_name
    github_private = not args.public
    provider       = args.provider

    print(f"\n[dam] DAMnation project init")
    print(f"   Project  : {project_name}")
    print(f"   Path     : {project_path}")
    print(f"   GitHub   : github.com/{args.gh_org}/{project_name} "
          f"({'private' if github_private else 'public'})")
    print(f"   Storage  : s3://{args.bucket}/{project_name}/  [{provider}]")
    if provider == "backblaze":
        print(f"   Endpoint : {args.endpoint_url}")
    print(f"   Region   : {args.region}")
    print()

    # --- Preflight ---
    check_prerequisites(provider=provider)

    if args.adopt:
        if not project_path.exists():
            print(f"[x] Directory not found: {project_path}")
            print("  Use without --adopt to create a new project.")
            sys.exit(1)
        print(f"  Adopting existing directory: {project_path}")
    else:
        if project_path.exists():
            print(f"[x] Directory already exists: {project_path}")
            print("  Use --adopt to wire up an existing project directory.")
            sys.exit(1)

    # --- Directory tree ---
    all_dirs = [f"assets/{d}" for d in ASSET_DIRS] + FINAL_CUT_DIRS + OTHER_DIRS
    if not args.adopt:
        print("\n[ 1 / 5 ] Creating directory tree...")
        for d in all_dirs:
            dir_path = project_path / d
            dir_path.mkdir(parents=True, exist_ok=True)
            (dir_path / ".gitkeep").touch()
        print(f"  [ok] {len(all_dirs)} directories created")
    else:
        print("\n[ 1 / 5 ] Directory tree -- skipped (adopting existing)")
        created = []
        for d in all_dirs:
            dir_path = project_path / d
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
                (dir_path / ".gitkeep").touch()
                created.append(d)
        if created:
            print(f"  [ok] Added {len(created)} missing directories")
        else:
            print("  [ok] All expected directories already present")

    # --- S3 bucket ---
    print("\n[ 2 / 5 ] Storage bucket...")
    ensure_s3_bucket(args.bucket, args.region, provider=provider)

    # --- Git ---
    print("\n[ 3 / 5 ] Git + GitHub...")
    init_git(project_path, project_name, args.gh_org, github_private, adopt=args.adopt)

    # --- DVC ---
    print("\n[ 4 / 5 ] DVC...")
    init_dvc(project_path, project_name, args.bucket, args.region,
             provider=provider, endpoint_url=args.endpoint_url, adopt=args.adopt)

    # --- Done ---
    print("\n[ 5 / 5 ] Done.")
    print(f"""
[ok] Project ready: {project_path}

To sync assets into DAMnation, run from the damnation directory:

  ./dam_sync.sh {project_name}
  ./dam_sync.sh {project_name} "Add sc01 hero shots"

To index only (after manual dvc add/push/commit):

  ./dam_post_add.sh {project_name}
  ./dam_post_add.sh {project_name} generated_images
""")


if __name__ == "__main__":
    main()
