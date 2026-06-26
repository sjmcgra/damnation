#!/usr/bin/env python3
"""
dam_init.py — Initialize a new DAMnation project

Creates the opinionated directory structure, initializes git and DVC,
creates (or reuses) an S3 bucket, configures the DVC remote, creates
a private GitHub repo, and writes a post-add hook script.

Usage:
    python dam_init.py <project_name>
    python dam_init.py <project_name> --projects-root /path/to/projects
    python dam_init.py <project_name> --bucket my-damnation-bucket

Prerequisites:
    - git
    - dvc[s3]  (pip install dvc[s3])
    - gh CLI   (https://cli.github.com) authenticated via gh auth login
    - aws CLI  authenticated with sufficient S3 permissions
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
    "3d_models",
    "audacity",
    "audio",
    "character_reference",
    "final_cut_exports",
    "garageband",
    "generated_audio",
    "generated_images",
    "generated_video",
    "images",
    "lip_sync_out",
    "location_reference",
    "motion",
    "motion_out",
    "photoshop",
    "photoshop_export",
    "upscaled_video",
    "video",
]

# final_cut/ is created but fully gitignored — FCP cache/media can be enormous
FINAL_CUT_DIRS = [
    "final_cut/FCP_Cache",
    "final_cut/FCP_Libraries",
    "final_cut/FCP_Media",
]

OTHER_DIRS = ["master"]

# ---------------------------------------------------------------------------
# .gitignore written into the project root
# ---------------------------------------------------------------------------

PROJECT_GITIGNORE = """# DAMnation project — git tracks only .dvc pointer files and config.
# All actual asset content is managed by DVC and stored in S3.

# Ignore asset content inside each subdirectory
assets/*/

# Keep .dvc pointer files at the assets/ level (e.g. assets/generated_images.dvc)
!assets/*.dvc

# Keep .gitkeep files so empty dirs are tracked
!assets/*/.gitkeep

# Final Cut Pro — cache and media can be enormous, never commit
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
    return subprocess.run(
        cmd, cwd=cwd, check=check,
        capture_output=capture, text=True
    )


def run_silent(cmd, cwd=None):
    """Run a command, return (returncode, stdout, stderr) without printing output."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def check_prerequisites():
    """Abort early if required tools are missing."""
    missing = []
    for tool in ["git", "dvc", "gh", "aws"]:
        if shutil.which(tool) is None:
            missing.append(tool)
    if missing:
        print(f"\n✗ Missing required tools: {', '.join(missing)}")
        print("  Install them before running dam_init.py")
        print("  - dvc:  pip install dvc[s3]")
        print("  - gh:   https://cli.github.com")
        print("  - aws:  https://aws.amazon.com/cli/")
        sys.exit(1)


def ensure_s3_bucket(bucket, region):
    """Create S3 bucket if it doesn't already exist."""
    rc, _, _ = run_silent(["aws", "s3", "ls", f"s3://{bucket}"])
    if rc == 0:
        print(f"  ✓ S3 bucket already exists: s3://{bucket}")
        return
    print(f"  Creating S3 bucket: s3://{bucket} in {region}")
    cmd = ["aws", "s3", "mb", f"s3://{bucket}", "--region", region]
    # us-east-1 does not accept a LocationConstraint
    if region != "us-east-1":
        cmd += ["--create-bucket-configuration", f"LocationConstraint={region}"]
    run(cmd)


def init_git(project_path, project_name, gh_org, github_private, adopt=False):
    """git init, initial commit, create GitHub repo, push."""
    git_dir = project_path / ".git"
    if adopt and git_dir.exists():
        print(f"  ✓ Git already initialized — skipping git init")
    else:
        run(["git", "init"], cwd=project_path)
        run(["git", "checkout", "-b", "main"], cwd=project_path)

    # Write .gitignore (always — may be missing in adopted projects)
    gitignore_path = project_path / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(PROJECT_GITIGNORE)
        print(f"  ✓ Wrote .gitignore")
    else:
        print(f"  ✓ .gitignore already exists — leaving untouched")

    # Check if remote already exists
    rc, remotes, _ = run_silent(["git", "remote"], cwd=project_path)
    if adopt and "origin" in remotes.split():
        print(f"  ✓ Git remote already configured — skipping GitHub repo creation")
        return

    run(["git", "add", "-A"], cwd=project_path)
    rc, _, _ = run_silent(["git", "diff", "--cached", "--quiet"], cwd=project_path)
    if rc != 0:  # there are staged changes
        run(["git", "commit", "-m", "chore: init project"], cwd=project_path)

    # Create GitHub repo
    visibility = "--private" if github_private else "--public"
    run(["gh", "repo", "create", f"{gh_org}/{project_name}",
         visibility, "--source", str(project_path), "--remote", "origin", "--push"],
        cwd=project_path)
    print(f"  ✓ GitHub repo created: github.com/{gh_org}/{project_name}")


def init_dvc(project_path, project_name, bucket, region, adopt=False):
    """dvc init, configure S3 remote, initial dvc push of config."""
    dvc_dir = project_path / ".dvc"
    if adopt and dvc_dir.exists():
        print(f"  ✓ DVC already initialized — checking remote...")
        rc, out, _ = run_silent(["dvc", "remote", "list"], cwd=project_path)
        if out.strip():
            print(f"  ✓ DVC remote already configured — skipping")
            return
    else:
        run(["dvc", "init"], cwd=project_path)

    remote_name = "s3remote"
    remote_url  = f"s3://{bucket}/{project_name}"
    run(["dvc", "remote", "add", "-d", remote_name, remote_url], cwd=project_path)
    run(["dvc", "remote", "modify", remote_name, "region", region], cwd=project_path)

    # Commit DVC config into git
    run(["git", "add", ".dvc/config", ".dvcignore"], cwd=project_path)
    run(["git", "commit", "-m", "chore: init dvc with s3 remote"], cwd=project_path)
    run(["git", "push", "origin", "main"], cwd=project_path)
    print(f"  ✓ DVC remote: {remote_url}")


def write_dam_sync(project_path, project_name, dam_dir):
    pass  # removed — dam_sync.sh now lives in the damnation repo root


def write_post_add_hook(project_path, project_name, dam_dir):
    pass  # removed — dam_post_add.sh now lives in the damnation repo root


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    dam_dir = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(
        description="Initialize a new DAMnation-managed project."
    )
    parser.add_argument("project_name",
                        help="Short project name, e.g. hokai_ep2 (used as directory name, GitHub repo name, and S3 prefix)")
    parser.add_argument("--projects-root",
                        default=str(PROJECTS_ROOT),
                        help=f"Root directory for all projects (default: {PROJECTS_ROOT})")
    parser.add_argument("--bucket",
                        default=os.getenv("DVC_S3_BUCKET", ""),
                        help="S3 bucket name (or set DVC_S3_BUCKET in .env)")
    parser.add_argument("--region",
                        default=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
                        help="AWS region (default: us-east-1)")
    parser.add_argument("--gh-org",
                        default=GH_ORG,
                        help=f"GitHub org or username (default: {GH_ORG})")
    parser.add_argument("--adopt",
                        action="store_true",
                        help="Adopt an existing project directory instead of creating a new one. "
                             "Skips directory creation, wires up git, DVC, GitHub, and writes the post-add hook.")
    parser.add_argument("--public",
                        action="store_true",
                        help="Create GitHub repo as public (default: private)")
    args = parser.parse_args()

    if not args.bucket:
        print("\n✗ S3 bucket name required.")
        print("  Set DVC_S3_BUCKET in your .env or pass --bucket <name>")
        sys.exit(1)

    project_name  = args.project_name
    projects_root = Path(args.projects_root).expanduser()
    project_path  = projects_root / project_name
    github_private = not args.public

    print(f"\n🎬 DAMnation project init")
    print(f"   Project : {project_name}")
    print(f"   Path    : {project_path}")
    print(f"   GitHub  : github.com/{args.gh_org}/{project_name} ({'private' if github_private else 'public'})")
    print(f"   S3      : s3://{args.bucket}/{project_name}/")
    print(f"   Region  : {args.region}")
    print()

    # --- Preflight ---
    check_prerequisites()

    if args.adopt:
        if not project_path.exists():
            print(f"✗ Directory not found: {project_path}")
            print(f"  Use without --adopt to create a new project.")
            sys.exit(1)
        print(f"  Adopting existing directory: {project_path}")
    else:
        if project_path.exists():
            print(f"✗ Directory already exists: {project_path}")
            print(f"  Use --adopt to wire up an existing project directory.")
            sys.exit(1)

    # --- Create directory tree (new projects only) ---
    if not args.adopt:
        print("\n[ 1 / 5 ] Creating directory tree...")
        all_dirs = (
            [f"assets/{d}" for d in ASSET_DIRS]
            + FINAL_CUT_DIRS
            + OTHER_DIRS
        )
        for d in all_dirs:
            dir_path = project_path / d
            dir_path.mkdir(parents=True, exist_ok=True)
            (dir_path / ".gitkeep").touch()
        print(f"  ✓ {len(all_dirs)} directories created")
    else:
        print("\n[ 1 / 5 ] Directory tree — skipped (adopting existing)")
        # Still ensure all expected asset subdirs exist, non-destructively
        created = []
        all_dirs = (
            [f"assets/{d}" for d in ASSET_DIRS]
            + FINAL_CUT_DIRS
            + OTHER_DIRS
        )
        for d in all_dirs:
            dir_path = project_path / d
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
                (dir_path / ".gitkeep").touch()
                created.append(d)
        if created:
            print(f"  ✓ Added {len(created)} missing directories: {', '.join(created)}")
        else:
            print(f"  ✓ All expected directories already present")

    # --- S3 bucket ---
    print("\n[ 2 / 5 ] S3 bucket...")
    ensure_s3_bucket(args.bucket, args.region)

    # --- Git ---
    print("\n[ 3 / 5 ] Git + GitHub...")
    init_git(project_path, project_name, args.gh_org, github_private, adopt=args.adopt)

    # --- DVC ---
    print("\n[ 4 / 5 ] DVC...")
    init_dvc(project_path, project_name, args.bucket, args.region, adopt=args.adopt)

    # --- Done ---
    print("\n[ 5 / 5 ] Done.")

    # --- Summary ---
    dam_dir_str = str(Path(__file__).resolve().parent)
    print(f"""
✓ Project ready: {project_path}

To sync assets into DAMnation, run from the damnation directory:

  ./dam_sync.sh {project_name}
  ./dam_sync.sh {project_name} "Add sc01 hero shots"

To index only (after manual dvc add/push/commit):

  ./dam_post_add.sh {project_name}
  ./dam_post_add.sh {project_name} generated_images
""")


if __name__ == "__main__":
    main()
