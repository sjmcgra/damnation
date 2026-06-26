import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)


def _expand_path(value):
    return Path(value).expanduser() if value else None


FLASK_ENV = os.getenv("FLASK_ENV", "production")
DB_PATH = _expand_path(os.getenv("DB_PATH", "~/.dvc_dam/assets.db"))
THUMBNAIL_DIR = _expand_path(os.getenv("THUMBNAIL_DIR", "")) or DB_PATH.parent / "thumbnails"
PROJECTS_ROOT = _expand_path(os.getenv("PROJECTS_ROOT", "/projects"))
GH_ORG = os.getenv("GH_ORG", "user")
DVC_REPO_URL_TEMPLATE = os.getenv("DVC_REPO_URL_TEMPLATE", "https://github.com/{org}/{project}.git")
GIT_BRANCH = os.getenv("GIT_BRANCH", "main")
GIT_SSH_COMMAND = os.getenv("GIT_SSH_COMMAND", "ssh -o StrictHostKeyChecking=no")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
WEB_PORT = os.getenv("WEB_PORT", "5500")
RESULTS_CACHE = DB_PATH.parent / "last_search.json"


def get_repo_url(project):
    return DVC_REPO_URL_TEMPLATE.format(org=GH_ORG, project=project)
