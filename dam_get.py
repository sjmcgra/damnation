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
#
# dam_get.py - download a file from search results
#
# Usage: python dam_get.py <project> <filepath>
#   project   - project name (e.g. hokai_ep1)
#   filepath  - path relative to project assets dir

import os
import sys
import subprocess

from config import get_repo_url, GIT_SSH_COMMAND


def get_file(project, filepath):
    repo_url = get_repo_url(project)
    env = os.environ.copy()
    env["GIT_SSH_COMMAND"] = GIT_SSH_COMMAND
    subprocess.run([
        "dvc", "get",
        repo_url,
        filepath
    ], env=env)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python dam_get.py <project> <filepath>")
        sys.exit(1)
    get_file(sys.argv[1], sys.argv[2])
