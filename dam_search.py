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

# dam_search.py - enhanced version
import sys
import sqlite3
from pathlib import Path

from config import DB_PATH


def search(query, project=None, file_type=None):
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    
    sql = "SELECT * FROM assets WHERE (tags LIKE ? OR filename LIKE ?)"
    params = [f"%{query}%", f"%{query}%"]
    
    if project:
        sql += " AND project = ?"
        params.append(project)
    
    if file_type:
        sql += " AND file_type LIKE ?"
        params.append(f"{file_type}%")
    
    results = db.execute(sql, params).fetchall()
    
    print(f"\nFound {len(results)} results for '{query}':\n")
    
    for i, row in enumerate(results, 1):
        print(f"{i}. {row['filename']}")
        print(f"   Project: {row['project']}")
        print(f"   Path: {row['filepath']}")
        if row['width']:
            print(f"   Size: {row['width']}x{row['height']}")
        print(f"   Thumbnail: {row['thumbnail_path']}")
        print()
    
    return results

if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    project = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not query:
        print("Usage: python dam_search.py <search_term> [project]")
        sys.exit(1)
    
    search(query, project)