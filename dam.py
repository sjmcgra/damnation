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

# dam.py - unified interface
import os
import sys
import sqlite3
from pathlib import Path
import subprocess
import json
import platform

from config import DB_PATH, RESULTS_CACHE, get_repo_url, GIT_SSH_COMMAND

def search(query, project=None):
    """Search assets and cache results"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    
    sql = "SELECT * FROM assets WHERE (tags LIKE ? OR filename LIKE ?)"
    params = [f"%{query}%", f"%{query}%"]
    
    if project:
        sql += " AND project = ?"
        params.append(project)
    
    results = db.execute(sql, params).fetchall()
    
    # Convert to list of dicts for caching
    results_list = [dict(row) for row in results]
    
    # Cache results
    RESULTS_CACHE.parent.mkdir(exist_ok=True)
    with open(RESULTS_CACHE, 'w') as f:
        json.dump(results_list, f)
    
    # Display
    print(f"\nFound {len(results_list)} results for '{query}':\n")
    for i, row in enumerate(results_list, 1):
        print(f"{i}. {row['filename']}")
        print(f"   Project: {row['project']}")
        print(f"   Path: {row['filepath']}")
        if row.get('width'):
            print(f"   Size: {row['width']}x{row['height']}")
        print()
    
    db.close()
    return results_list

def view(index):
    """View thumbnail from last search"""
    if not RESULTS_CACHE.exists():
        print("No search results cached. Run 'search' first.")
        return
    
    with open(RESULTS_CACHE, 'r') as f:
        results = json.load(f)
    
    if index < 1 or index > len(results):
        print(f"Invalid index. Must be 1-{len(results)}")
        return
    
    result = results[index - 1]
    thumb_path = RESULTS_CACHE.parent / result['thumbnail_path']
    
    if not thumb_path.exists():
        print(f"Thumbnail not found: {thumb_path}")
        return
    
    # Open thumbnail
    if sys.platform == 'darwin':  # Mac
        subprocess.run(['open', str(thumb_path)])
    else:  # Linux
        subprocess.run(['xdg-open', str(thumb_path)])

def get_file(index):
    """Download file from DVC"""
    if not RESULTS_CACHE.exists():
        print("No search results cached. Run 'search' first.")
        return
    
    with open(RESULTS_CACHE, 'r') as f:
        results = json.load(f)
    
    if index < 1 or index > len(results):
        print(f"Invalid index. Must be 1-{len(results)}")
        return
    
    result = results[index - 1]
    project = result['project']
    filepath = result['filepath']
    
    print(f"Downloading {filepath} from {project}...")
    repo_url = get_repo_url(project)
    env = None
    try:
        env = {**os.environ, "GIT_SSH_COMMAND": GIT_SSH_COMMAND}
    except Exception:
        env = os.environ.copy()

    subprocess.run([
        'dvc', 'get',
        repo_url,
        filepath
    ], env=env)

def index_files(project, directory):
    """Index files"""
    from dam_index import DAMIndexer
    indexer = DAMIndexer()
    indexer.index_project_directory(project, directory)

def show_help():
    print("""
DAM - Digital Asset Management Tool

Usage:
    dam.py search <query> [project]    - Search for assets
    dam.py view <number>               - View thumbnail from last search
    dam.py get <number>                - Download file from last search
    dam.py index <project> <directory> - Index new files
    
Examples:
    dam.py search village hokai_ep1
    dam.py view 3
    dam.py get 5
    dam.py index hokai_ep1 assets/generated_images/
    """)

def main():
    if len(sys.argv) < 2:
        show_help()
        return
    
    cmd = sys.argv[1]
    
    if cmd == "search":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        project = sys.argv[3] if len(sys.argv) > 3 else None
        if not query:
            print("Error: search requires a query term")
            show_help()
            return
        search(query, project)
        
    elif cmd == "view":
        if len(sys.argv) < 3:
            print("Error: view requires a result number")
            return
        index = int(sys.argv[2])
        view(index)
        
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Error: get requires a result number")
            return
        index = int(sys.argv[2])
        get_file(index)
        
    elif cmd == "index":
        if len(sys.argv) < 4:
            print("Error: index requires project and directory")
            show_help()
            return
        project = sys.argv[2]
        directory = sys.argv[3]
        index_files(project, directory)
        
    else:
        print(f"Unknown command: {cmd}")
        show_help()

if __name__ == "__main__":
    main()