# DAMnation

DAMnation is a self-hosted digital asset management system for media projects tracked with Git and DVC. It provides a searchable web UI for browsing, previewing, and downloading assets, with version history pulled from Git.

## How it works

DAMnation has two distinct sides:

```
┌─────────────────────────────────────┐     ┌──────────────────────────────────┐
│           HOST SYSTEM               │     │         DOCKER CONTAINER         │
│                                     │     │                                  │
│  dam_index.py   ← you run this      │     │  app.py  (Flask web UI)          │
│  dvc add / push ← your workflow     │     │                                  │
│  fcpxml_audit.py                    │     │  Reads: /projects  (read-only)   │
│  cleanup_duplicates.py              │     │          /dam_data/assets.db     │
│                                     │     │          /dam_data/thumbnails/   │
│  Your project files live here       │     │                                  │
│  e.g. /Volumes/CYBERMAN/Projects/   │     │  Serves: localhost:5500          │
└────────────────┬────────────────────┘     └──────────────┬───────────────────┘
                 │                                         │
                 │        Docker volume mounts             │
                 │  PROJECTS_ROOT  ──────────►  /projects  │
                 │  DB_DATA_PATH   ──────────►  /dam_data  │
                 └─────────────────────────────────────────┘
```

**The host side** is where your actual work happens: running the indexer after adding assets, issuing DVC commands, and using the CLI tools. These tools write to the shared database and thumbnail cache.

**The container side** is read-only with respect to your project files. It serves the web UI and reads whatever the host-side tools have written to the shared database. The container never needs to touch your actual project files directly.

The database (`assets.db`) and thumbnails are the shared state between the two sides, stored in `DB_DATA_PATH` on the host and mounted into the container at `/dam_data`.

## Requirements

- Patience
- Python 3.10+
- Docker and Docker Compose (for the web UI)
- DVC with S3 support: `pip install dvc[s3]`
- ffmpeg (for video thumbnails, host-side indexing)
- Git

## Setup

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env`. The key values:

```bash
# Where your project repos live on the HOST
PROJECTS_ROOT=/Volumes/CYBERMAN/Projects

# Where the database and thumbnails are stored on the HOST
# This directory is mounted into the container at /dam_data
DB_DATA_PATH=./data

# Your GitHub org or username (used to build DVC repo URLs)
GH_ORG=your-github-username
```

See `.env.example` for all options with descriptions.

### 2. Install host-side tools

```bash
chmod +x install.sh
./install.sh
source .venv/bin/activate
```

This installs the Python dependencies into a local `.venv` for the host-side CLI tools (indexer, search, utilities). The container uses its own separate environment.

### 3. Start the web UI

```bash
docker compose up --build -d
```

Open http://localhost:5500 (or the port set in `WEB_PORT`).

## Storage backends

DAMnation is opinionated toward S3-compatible object storage. Both AWS S3 and Backblaze B2 are supported with no extra dependencies -- they use the same `dvc[s3]` package via B2's S3-compatible API.

**AWS S3** (default):
```bash
STORAGE_PROVIDER=aws
DVC_S3_BUCKET=your-bucket
AWS_DEFAULT_REGION=us-east-1
```

**Backblaze B2** (significantly cheaper at $6/TB/month vs $23/TB for S3):
```bash
STORAGE_PROVIDER=backblaze
DVC_S3_BUCKET=your-b2-bucket
B2_ENDPOINT_URL=https://s3.us-west-004.backblazeb2.com
AWS_ACCESS_KEY_ID=your-b2-keyID
AWS_SECRET_ACCESS_KEY=your-b2-applicationKey
```

For Backblaze, create the bucket manually in the [Backblaze console](https://www.backblaze.com) first -- bucket creation via the S3-compatible API is not supported by B2. The endpoint URL region must match your bucket's region.

Then init your project normally:
```bash
python dam_init.py my_project --provider backblaze
```

## Initializing a new project

Run `dam_init.py` once per project to set up the directory tree, git repo, DVC, and S3:

```bash
source .venv/bin/activate

# New project — creates everything from scratch
python dam_init.py <project_name>

# Existing project — wires up git, DVC, GitHub, and writes scripts non-destructively
python dam_init.py <project_name> --adopt

# Examples
python dam_init.py hokai_ep2
python dam_init.py hokai --adopt
python dam_init.py hokai_ep2 --projects-root /Volumes/CYBERMAN/Projects --bucket my-dam-bucket
```

Use `--adopt` whenever the project directory already exists (e.g. you've been working in it before DAMnation was set up). It will leave existing files and any existing `.gitignore` untouched, add any missing asset subdirectories, and wire up git/DVC/GitHub from where things stand.

After init, two scripts are written to the project root:

| Script | Purpose |
|---|---|
| `dam_sync.sh` | Full workflow — `dvc add` new files, push to S3, git commit, index into DAMnation |
| `dam_post_add.sh` | Index only — use when you've already run `dvc add` and `git commit` manually |

Typical day-to-day workflow:

```bash
# From anywhere — always run from the damnation directory
cd /path/to/damnation

# Drop new assets into the project's assets/ subdirectory, then:
./dam_sync.sh hokai_ep2

# Or with a commit message:
./dam_sync.sh hokai_ep2 "Add sc01 hero shots"

# Or to sync just one subdirectory:
./dam_sync.sh hokai_ep2 "Add sc01 hero shots" generated_images
```

**Tip:** Add a shell alias so you can run DAMnation scripts from anywhere without `cd`-ing first:

```bash
# Add to ~/.zshrc or ~/.bashrc
export DAMNATION_DIR=/path/to/damnation
alias dam='cd $DAMNATION_DIR && source .venv/bin/activate'
```

Then from any terminal:

```bash
dam && ./dam_sync.sh hokai_ep2
```

## Indexing assets

The indexer runs **on the host**, not inside the container. It reads your project files, generates thumbnails, and writes metadata into the shared database.

```bash
# Activate the host-side environment first
source .venv/bin/activate

# Index an asset directory within a project
python dam_index.py index <project_name> <asset_subdirectory>

# Examples
python dam_index.py index hokai_ep1 generated_images/
python dam_index.py index hokai_ep1 generated_video/sc01/
python dam_index.py index hokai_ep2 assets/
```

The `project_name` is matched against subdirectories under `PROJECTS_ROOT`. The `asset_subdirectory` is relative to `<project>/assets/`.

After indexing, the web UI reflects the new assets immediately — no container restart needed.

## DVC workflow

DVC commands also run **on the host** where your data lives:

```bash
# Track new files
dvc add assets/generated_images/

# Push to remote storage (S3)
dvc push

# Then index the new files
python dam_index.py index my_project generated_images/
```

## CLI tools (host-side)

All CLI tools are meant to be run on the host with the `.venv` activated.

```bash
# Search assets
python dam.py search <query> [project]
python dam.py search village hokai_ep1

# View thumbnail from last search result
python dam.py view <result_number>

# Download a file from last search result via DVC
python dam.py get <result_number>

# Direct download by project and path
python dam_get.py <project> <filepath>
```

### Utilities

```bash
# Audit an FCP library for unused clips
python fcpxml_audit.py path/to/library.fcpxmld
python fcpxml_audit.py path/to/Info.fcpxml --unused-only --csv report.csv

Run audit with extra DAM update:

python fcpxml_audit.py /path/to/Info.fcpxml --mark-used-in-dam
Optionally restrict to a project:
python fcpxml_audit.py /path/to/Info.fcpxml --mark-used-in-dam --dam-project hokai_ep1

# Clean up duplicate database entries
python cleanup_duplicates.py
python cleanup_duplicates.py --dry-run   # preview first
```

## Configuration reference

| Variable | Default | Description |
|---|---|---|
| `FLASK_ENV` | `production` | `development` enables debug mode and reloader |
| `DB_PATH` | `~/.dvc_dam/assets.db` | SQLite database path (host-side tools) |
| `THUMBNAIL_DIR` | next to DB | Thumbnail cache directory (host-side tools) |
| `PROJECTS_ROOT` | `/projects` | Root directory of your project repos |
| `GH_ORG` | `user` | GitHub org/username for DVC repo URLs |
| `DVC_REPO_URL_TEMPLATE` | `https://github.com/{org}/{project}.git` | URL template; `{org}` and `{project}` are substituted |
| `GIT_BRANCH` | `main` | Branch used for version restore |
| `GIT_SSH_COMMAND` | `ssh -o StrictHostKeyChecking=no` | SSH command for private repo access |
| `AWS_DEFAULT_REGION` | `us-east-1` | AWS region for DVC S3 remote |
| `WEB_PORT` | `5500` | Port the web UI listens on |
| `DB_DATA_PATH` | `./data` | Host path for database and thumbnails (Docker only) |
| `SSH_PATH` | `~/.ssh` | Host SSH directory mounted into container (Docker only) |
| `AWS_CREDENTIALS_PATH` | `~/.aws` | Host AWS credentials directory mounted into container (Docker only) |

### Path note: host tools vs container

The host-side tools (`dam_index.py`, `dam.py`, etc.) read `DB_PATH` and `PROJECTS_ROOT` from `.env` and use your actual host filesystem paths.

The container **overrides** `DB_PATH`, `THUMBNAIL_DIR`, and `PROJECTS_ROOT` with its internal mount paths (`/dam_data/...`, `/projects`) regardless of what `.env` says for those values. This is intentional — the container always uses consistent internal paths, and the volume mounts in `docker-compose.yml` connect them to wherever the data lives on your host.

You do not need to change `docker-compose.yml` unless you want to customize the mount structure. Setting `PROJECTS_ROOT` and `DB_DATA_PATH` in `.env` is enough.

## Docker notes

The container mounts:
- `DB_DATA_PATH` → `/dam_data` (read-write: database and thumbnails)
- `PROJECTS_ROOT` → `/projects` (read-only: your actual asset files)
- `SSH_PATH` → `/root/.ssh` (read-only: for private Git/DVC repos)
- `AWS_CREDENTIALS_PATH` → `/root/.aws` (read-only: for S3 access)

The container does **not** run the indexer or DVC. It only serves the web UI and reads the database produced by the host-side tools.

## Notes

- `.env` is gitignored. Never commit it.
- Use `python -m venv .venv` to isolate host-side dependencies.
- The database path used by host tools (`DB_PATH` in `.env`) must point to the same physical location as `DB_DATA_PATH` — they are two names for the same directory, one used by the host tools, one by Docker.
- If you use private repositories, provide SSH keys and AWS credentials via `SSH_PATH` and `AWS_CREDENTIALS_PATH`.
- S3 has no real directories. The per-project prefix (e.g. `s3://your-bucket/hokai_ep2/`) does not need to be created manually — it appears automatically on the first `dvc push`.
