import os
import platform
from pathlib import Path

from config import DB_PATH, RESULTS_CACHE, PROJECTS_ROOT, get_repo_url, GIT_SSH_COMMAND


def get_default_db_path():
    return DB_PATH


def get_results_cache_path():
    return RESULTS_CACHE


def get_dvc_repo_url(project):
    return get_repo_url(project)


def get_env_for_dvc():
    env = os.environ.copy()
    env["GIT_SSH_COMMAND"] = GIT_SSH_COMMAND
    return env


def expand_local_path(path):
    return Path(path).expanduser()
