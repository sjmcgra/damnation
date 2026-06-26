#!/usr/bin/env python3
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
