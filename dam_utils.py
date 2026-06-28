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
