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
DVC DAM Foundation - Automatic Asset Indexing
Run this after 'dvc add' to build searchable index for future use

Usage:
  python dam_index.py hokai_ep1 generated_images/

This builds metadata in background while you continue your normal workflow.
"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime
from PIL import Image
import hashlib
import json
import yaml
import subprocess

from config import DB_PATH, PROJECTS_ROOT, THUMBNAIL_DIR


class DAMIndexer:
    def __init__(self, db_path=None, projects_root=None):
        if db_path is None:
            db_path = DB_PATH

        if projects_root is None:
            projects_root = PROJECTS_ROOT

        self.projects_root = Path(projects_root)
        self.db_path = Path(db_path).expanduser()
        self.thumbnail_dir = Path(THUMBNAIL_DIR).expanduser() if THUMBNAIL_DIR else self.db_path.parent / "thumbnails"

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def init_db(self):
        """Initialize SQLite database"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                filepath TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_type TEXT,
                file_size INTEGER,
                width INTEGER,
                height INTEGER,
                duration REAL,
                dvc_hash TEXT,
                thumbnail_path TEXT,
                tags TEXT,
                ai_description TEXT,
                created_date TEXT,
                indexed_date TEXT,
                git_commit TEXT,
                review_status TEXT,
                is_bundle INTEGER DEFAULT 0,
                bundle_path TEXT,
                bundle_files INTEGER,
                UNIQUE(project, filepath)
            )
        ''')
        
        # Add missing columns if they don't exist (migration)
        c.execute("PRAGMA table_info(assets)")
        existing_columns = {col[1] for col in c.fetchall()}
        
        columns_to_add = {
            'review_status': 'TEXT',
            'is_bundle': 'INTEGER DEFAULT 0',
            'bundle_path': 'TEXT',
            'bundle_files': 'INTEGER',
            'archived': 'INTEGER DEFAULT 0',
            'archive_source': 'TEXT',
            'used': 'INTEGER DEFAULT 0'
        }
        
        for col_name, col_type in columns_to_add.items():
            if col_name not in existing_columns:
                try:
                    c.execute(f"ALTER TABLE assets ADD COLUMN {col_name} {col_type}")
                    print(f"  ✓ Added column: {col_name}")
                except Exception as e:
                    print(f"  Warning: Could not add column {col_name}: {e}")
        
        c.execute("CREATE INDEX IF NOT EXISTS idx_project ON assets(project)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tags ON assets(tags)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_filename ON assets(filename)")

        conn.commit()
        conn.close()
        print(f"✓ Database initialized at {self.db_path}")

    def index_project_directory(self, project_name, asset_dir):
        """
        Index all files in a directory that was just added to DVC

        Args:
            project_name: e.g., "hokai_ep1"
            asset_dir: e.g., "generated_images/" or "3d_models/"
        """
        projects_root = self.projects_root
        project_path = projects_root / project_name / "assets"
        full_dir = project_path / asset_dir

        if not full_dir.exists():
            print(f"✗ Directory not found: {full_dir}")
            return

        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=project_path,
                capture_output=True,
                text=True,
            )
            git_commit = result.stdout.strip()
        except Exception:
            git_commit = None

        file_count = 0
        for file_path in full_dir.rglob("*"):
            # Skip .dvc files
            if file_path.suffix == ".dvc":
                continue
            
            # Handle .band packages (directories treated as bundles)
            if file_path.is_dir() and file_path.suffix == '.band':
                relative_path = file_path.relative_to(project_path)
                self.index_file(project_name, relative_path, file_path, git_commit)
                file_count += 1
                continue
            
            # Skip files inside .band packages
            if any(part.endswith('.band') for part in file_path.parts):
                continue
            
            # Handle .motn files
            if file_path.is_file() and file_path.suffix == '.motn':
                relative_path = file_path.relative_to(project_path)
                self.index_file(project_name, relative_path, file_path, git_commit)
                file_count += 1
                continue
            
            # Skip Media directory that's next to .motn files
            if file_path.is_file() and "Media" in file_path.parts:
                media_index = file_path.parts.index("Media")
                parent_dir = Path(*file_path.parts[:media_index])
                if any(p.suffix == '.motn' for p in parent_dir.glob("*.motn")):
                    continue
            
            # Process regular files (not inside bundles)
            if file_path.is_file() and not file_path.name.startswith("."):
                relative_path = file_path.relative_to(project_path)
                self.index_file(project_name, relative_path, file_path, git_commit)
                file_count += 1

        print(f"✓ Indexed {file_count} files from {asset_dir}")

    def index_file(self, project, relative_path, full_path, git_commit):
        """Index a single file"""
        stat = full_path.stat()
        file_type = self.get_file_type(full_path)
        
        metadata = {
            'project': project,
            'filepath': str(relative_path),
            'filename': full_path.name,
            'file_type': file_type,
            'file_size': stat.st_size,
            'created_date': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            'indexed_date': datetime.now().isoformat(),
            'git_commit': git_commit
        }
        
        # Handle Motion bundles
        if full_path.suffix == '.motn':
            metadata['is_bundle'] = True
            metadata['bundle_path'] = str(relative_path.parent)
            media_folder = full_path.parent / 'Media'
            if media_folder.exists():
                media_count = len(list(media_folder.iterdir()))
                metadata['bundle_files'] = media_count
        
        # Handle GarageBand bundles (.band is a directory/package)
        elif full_path.suffix == '.band' and full_path.is_dir():
            metadata['is_bundle'] = True
            metadata['bundle_path'] = str(relative_path.parent)
            # Count all files in subdirectories (full_path IS the .band directory)
            band_files = 0
            for subdir in ['Media', 'Alternatives', 'Resources']:
                subdir_path = full_path / subdir
                if subdir_path.exists():
                    band_files += len(list(subdir_path.rglob('*')))
            # Also count projectData if it exists
            project_data = full_path / 'projectData'
            if project_data.exists():
                band_files += 1
            metadata['bundle_files'] = band_files if band_files > 0 else None
            
            # Try to use WindowImage.jpg from Alternatives as thumbnail
            alternatives_dir = full_path / 'Alternatives'
            if alternatives_dir.exists():
                for window_image in alternatives_dir.rglob('WindowImage.jpg'):
                    print(f"    Found WindowImage at: {window_image}")
                    try:
                        thumb_path = self.create_thumbnail(window_image, project, relative_path)
                        if thumb_path:
                            metadata['thumbnail_path'] = thumb_path
                            print(f"    ✓ Created thumbnail: {thumb_path}")
                        else:
                            print(f"    ✗ Thumbnail creation returned None")
                    except Exception as e:
                        print(f"    ✗ Error creating thumbnail: {e}")
                    break  # Use the first WindowImage.jpg found
        
        dvc_file = full_path.parent / f"{full_path.name}.dvc"
        if dvc_file.exists():
            metadata['dvc_hash'] = self.get_dvc_hash(dvc_file)
        
        if file_type.startswith('image'):
            img_meta = self.extract_image_metadata(full_path)
            metadata.update(img_meta)
            thumb_path = self.create_thumbnail(full_path, project, relative_path)
            metadata['thumbnail_path'] = thumb_path
        
        elif file_type.startswith('video'):
            thumb_path = self.create_video_thumbnail(full_path, project, relative_path)
            metadata['thumbnail_path'] = thumb_path
        
        tags = self.auto_tag(project, relative_path, full_path.name)
        metadata['tags'] = self.normalize_tags(tags)
        
        self.store_asset(metadata)
        print(f"  • {relative_path}")

    def create_video_thumbnail(self, source_path, project, relative_path, size=(400, 400)):
        """Generate thumbnail from video file"""
        try:
            thumb_dir = self.thumbnail_dir / project
            thumb_dir.mkdir(exist_ok=True)

            path_hash = hashlib.md5(str(relative_path).encode()).hexdigest()[:8]
            thumb_path = thumb_dir / f"{path_hash}_{source_path.stem}.jpg"

            result = subprocess.run([
                'ffmpeg',
                '-i', str(source_path),
                '-ss', '00:00:01.000',
                '-vframes', '1',
                '-vf', f'scale={size[0]}:{size[1]}:force_original_aspect_ratio=decrease',
                '-y',
                str(thumb_path)
            ], capture_output=True, text=True)

            if result.returncode == 0 and thumb_path.exists():
                return str(thumb_path.relative_to(self.thumbnail_dir.parent))
            else:
                print(f"    Warning: Could not create video thumbnail")
                return None

        except Exception as e:
            print(f"    Warning: Could not create video thumbnail: {e}")
            return None

    def get_file_type(self, path):
        """Determine MIME type"""
        ext = path.suffix.lower()
        types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".avi": "video/x-msvideo",
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".blend": "model/blender",
            ".glb": "model/gltf-binary",
            ".gltf": "model/gltf+json",
            ".fbx": "model/fbx",
            ".obj": "model/obj",
            '.motn': 'application/x-motion',
            '.band': 'application/x-garageband'
        }
        return types.get(ext, "application/octet-stream")

    def extract_image_metadata(self, path):
        """Extract image dimensions"""
        try:
            with Image.open(path) as img:
                return {"width": img.width, "height": img.height}
        except Exception as e:
            print(f"    Warning: Could not extract image metadata: {e}")
            return {}

    def create_thumbnail(self, source_path, project, relative_path, size=(400, 400)):
        """Generate thumbnail for quick browsing"""
        try:
            thumb_dir = self.thumbnail_dir / project
            thumb_dir.mkdir(exist_ok=True)

            path_hash = hashlib.md5(str(relative_path).encode()).hexdigest()[:8]
            thumb_path = thumb_dir / f"{path_hash}_{source_path.stem}.jpg"

            with Image.open(source_path) as img:
                if img.mode in ("RGBA", "LA", "P"):
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    background.paste(
                        img, mask=img.split()[-1] if img.mode == "RGBA" else None
                    )
                    img = background

                img.thumbnail(size, Image.Resampling.LANCZOS)
                img.save(thumb_path, "JPEG", quality=85, optimize=True)

            return str(thumb_path.relative_to(self.thumbnail_dir.parent))
        except Exception as e:
            print(f"    Warning: Could not create thumbnail: {e}")
            return None

    def get_dvc_hash(self, dvc_file):
        """Extract MD5 hash from .dvc file"""
        try:
            with open(dvc_file, "r") as f:
                dvc_data = yaml.safe_load(f)
                return dvc_data.get("md5") or dvc_data.get("outs", [{}])[0].get("md5")
        except Exception:
            return None

    def normalize_tags(self, tags):
        """Normalize tags into a sorted comma-separated string."""
        if tags is None:
            return ''

        normalized = []
        if isinstance(tags, (list, tuple, set)):
            raw_tags = tags
        else:
            raw_tags = [str(tags)]

        for raw in raw_tags:
            if raw is None:
                continue
            if isinstance(raw, str):
                for tag in raw.replace(';', ',').split(','):
                    tag = tag.strip()
                    if tag and tag.lower() not in normalized:
                        normalized.append(tag.lower())
            else:
                tag = str(raw).strip()
                if tag and tag.lower() not in normalized:
                    normalized.append(tag.lower())

        return ','.join(normalized)

    def auto_tag(self, project, path, filename):
        """
        Automatically generate tags from path and filename
        Later can be enhanced with AI vision API
        """
        tags = []

        tags.append(project)

        path_parts = Path(path).parts
        for part in path_parts:
            if part not in [
                "assets",
                "generated_images",
                "generated_video",
                "generated_audio",
                "3d_models",
                "motion",
            ]:
                tags.append(part.lower())

        name_parts = filename.lower().replace("_", " ").replace("-", " ").split()
        for part in name_parts:
            tags.append(part)

        return tags

    def store_asset(self, metadata):
        """Store asset metadata in database.

        Uses INSERT OR IGNORE + selective UPDATE so that human-curated fields
        (tags, ai_description) are never overwritten by a reindex.
        Only system-derived fields that may legitimately change (file_size,
        dvc_hash, thumbnail_path, indexed_date, git_commit, dimensions, bundle
        info) are updated on subsequent runs.
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # First pass: insert if this (project, filepath) pair is new.
        # OR IGNORE means existing rows are left completely untouched here.
        c.execute('''
            INSERT OR IGNORE INTO assets
            (project, filepath, filename, file_type, file_size, width, height,
             dvc_hash, thumbnail_path, tags, created_date, indexed_date, git_commit,
             review_status, is_bundle, bundle_path, bundle_files, archived, archive_source, used)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                metadata['project'],
                metadata['filepath'],
                metadata['filename'],
                metadata['file_type'],
                metadata['file_size'],
                metadata.get('width'),
                metadata.get('height'),
                metadata.get('dvc_hash'),
                metadata.get('thumbnail_path'),
                metadata['tags'],
                metadata['created_date'],
                metadata['indexed_date'],
                metadata['git_commit'],
                metadata.get('review_status', ''),
                metadata.get('is_bundle', False),
                metadata.get('bundle_path'),
                metadata.get('bundle_files'),
                metadata.get('archived', False),
                metadata.get('archive_source'),
                metadata.get('used', False)
            ))
        # Also excludes: git_commit (keeps the commit when first indexed).
        if c.rowcount == 0:
            c.execute('''
                UPDATE assets SET
                    filename      = ?,
                    file_type     = ?,
                    file_size     = ?,
                    width         = ?,
                    height        = ?,
                    dvc_hash      = ?,
                    thumbnail_path = ?,
                    indexed_date  = ?,
                    is_bundle     = ?,
                    bundle_path   = ?,
                    bundle_files  = ?
                WHERE project = ? AND filepath = ?
            ''', (
                metadata['filename'],
                metadata['file_type'],
                metadata['file_size'],
                metadata.get('width'),
                metadata.get('height'),
                metadata.get('dvc_hash'),
                metadata.get('thumbnail_path'),
                metadata['indexed_date'],
                metadata.get('is_bundle', False),
                metadata.get('bundle_path'),
                metadata.get('bundle_files'),
                metadata['project'],
                metadata['filepath'],
            ))

        conn.commit()
        conn.close()

    def archive_project(self, project, archive_source):
        """Mark all assets in a project as archived"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        result = c.execute('UPDATE assets SET archived=1, archive_source=? WHERE project=?',
                          (archive_source, project))
        affected = result.rowcount
        
        conn.commit()
        conn.close()
        
        return affected

    def mark_assets_used(self, filenames, project=None):
        """Mark assets as used in the DAM database."""
        if not filenames:
            return 0

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        placeholders = ','.join('?' for _ in filenames)
        if project:
            query = f'UPDATE assets SET used=1 WHERE filename IN ({placeholders}) AND project=?'
            params = [*filenames, project]
        else:
            query = f'UPDATE assets SET used=1 WHERE filename IN ({placeholders})'
            params = [*filenames]

        result = c.execute(query, params)
        affected = result.rowcount

        conn.commit()
        conn.close()
        return affected


def main():
    if len(sys.argv) < 2:
        print("Usage: python dam_index.py [command] <project> [args]")
        print("Commands:")
        print("  index <project> <asset_directory>  - Index assets (default if no command)")
        print("  archive <project> <source>         - Mark project as archived")
        print("Examples:")
        print("  python dam_index.py hokai_ep1 generated_images/  # Old format (still works)")
        print("  python dam_index.py index hokai_ep1 generated_images/  # New format")
        print("  python dam_index.py archive hokai_ep1 's3://archive/hokai_ep1'")
        sys.exit(1)

    indexer = DAMIndexer()
    
    # Check if first arg is a command or a project name (backward compatibility)
    first_arg = sys.argv[1]
    
    if first_arg in ['index', 'archive']:
        # New format: explicit command
        command = first_arg
        if command == 'index':
            if len(sys.argv) < 4:
                print("Usage: python dam_index.py index <project> <asset_directory>")
                sys.exit(1)
            project = sys.argv[2]
            asset_dir = sys.argv[3]
            indexer.index_project_directory(project, asset_dir)
            print(f"\n✓ Indexing complete. Database: {indexer.db_path}")
            
        elif command == 'archive':
            if len(sys.argv) < 4:
                print("Usage: python dam_index.py archive <project> <archive_source>")
                print("Example: python dam_index.py archive hokai_ep1 's3://archive/hokai_ep1'")
                sys.exit(1)
            project = sys.argv[2]
            archive_source = sys.argv[3]
            affected = indexer.archive_project(project, archive_source)
            print(f"\n✓ Archived {affected} assets from {project}")
            print(f"  Archive source: {archive_source}")
    else:
        # Old format: assume first two args are project and directory
        # Maintain backward compatibility
        if len(sys.argv) < 3:
            print("Usage: python dam_index.py <project> <asset_directory>")
            print("       python dam_index.py index <project> <asset_directory>")
            print("       python dam_index.py archive <project> <source>")
            sys.exit(1)
        project = first_arg
        asset_dir = sys.argv[2]
        indexer.index_project_directory(project, asset_dir)
        print(f"\n✓ Indexing complete. Database: {indexer.db_path}")


if __name__ == "__main__":
    main()
