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
cleanup_duplicates.py — Remove duplicate asset entries from the DAMnation database.

Keeps only the most recently indexed entry for each (project, filepath) pair.
Safe to run at any time; rolls back on error.

Usage:
    python cleanup_duplicates.py
    python cleanup_duplicates.py --db-path /custom/path/assets.db
    python cleanup_duplicates.py --dry-run
"""

import sqlite3
import argparse
from pathlib import Path

from config import DB_PATH


def cleanup_duplicates(db_path, dry_run=False):
    """Remove duplicate entries, keeping the latest one for each (project, filepath)."""
    db_path = Path(db_path).expanduser()

    if not db_path.exists():
        print(f"✗ Database not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    try:
        c.execute('''
            SELECT project, filepath, COUNT(*) as count
            FROM assets
            GROUP BY project, filepath
            HAVING count > 1
            ORDER BY count DESC
        ''')
        duplicates = c.fetchall()

        if not duplicates:
            print("✓ No duplicates found.")
            conn.close()
            return

        print(f"Found {len(duplicates)} filepath(s) with duplicate entries:")
        total_to_delete = 0

        for project, filepath, count in duplicates:
            print(f"\n  {project}/{filepath}  ({count} entries)")

            c.execute('''
                SELECT id, indexed_date, git_commit
                FROM assets
                WHERE project = ? AND filepath = ?
                ORDER BY indexed_date DESC
            ''', (project, filepath))
            entries = c.fetchall()

            for entry_id, indexed_date, git_commit in entries[1:]:
                print(f"    {'[dry-run] ' if dry_run else ''}Deleting id={entry_id}"
                      f"  indexed={indexed_date}  commit={git_commit}")
                if not dry_run:
                    c.execute('DELETE FROM assets WHERE id = ?', (entry_id,))
                total_to_delete += 1

        if dry_run:
            print(f"\n  [dry-run] Would delete {total_to_delete} duplicate entries — no changes written.")
            conn.rollback()
        else:
            conn.commit()
            print(f"\n✓ Deleted {total_to_delete} duplicate entries.")
            print(f"✓ Database: {db_path}")

    except Exception as e:
        print(f"✗ Error: {e}")
        conn.rollback()
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Remove duplicate asset entries from the DAMnation database."
    )
    parser.add_argument(
        '--db-path',
        default=str(DB_PATH),
        help=f'Path to the assets database (default: {DB_PATH})'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be deleted without making any changes'
    )
    args = parser.parse_args()

    print(f"🧹 Scanning for duplicate entries...")
    print(f"   Database: {args.db_path}\n")
    cleanup_duplicates(args.db_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
