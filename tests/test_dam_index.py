import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dam_index import DAMIndexer
import app as dam_app


class DAMIndexerStoreAssetTest(unittest.TestCase):
    def test_store_asset_accepts_used_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "assets.db"
            projects_root = tmp_path / "projects"
            projects_root.mkdir(parents=True, exist_ok=True)

            indexer = DAMIndexer(db_path=db_path, projects_root=projects_root)
            metadata = {
                "project": "demo",
                "filepath": "assets/test.jpg",
                "filename": "test.jpg",
                "file_type": "image/jpeg",
                "file_size": 123,
                "created_date": "2026-06-30T00:00:00",
                "indexed_date": "2026-06-30T00:00:01",
                "git_commit": "abc123",
                "tags": "demo,test",
                "used": True,
            }

            indexer.store_asset(metadata)

            conn = sqlite3.connect(db_path)
            try:
                row = conn.execute("SELECT used FROM assets WHERE project=? AND filepath=?", ("demo", "assets/test.jpg")).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], 1)
            finally:
                conn.close()

    def test_update_asset_status_endpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "assets.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("CREATE TABLE assets (id INTEGER PRIMARY KEY AUTOINCREMENT, review_status TEXT)")
                conn.execute("INSERT INTO assets (review_status) VALUES (?)", ("",))
                conn.commit()
            finally:
                conn.close()

            original_db_path = dam_app.DB_PATH
            original_thumbnail_dir = dam_app.THUMBNAIL_DIR
            dam_app.DB_PATH = db_path
            dam_app.THUMBNAIL_DIR = Path(tmpdir) / "thumbnails"
            dam_app.THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
            try:
                client = dam_app.app.test_client()
                response = client.post('/api/assets/1/status', json={'status': 'approved'})
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertTrue(payload['success'])
                self.assertEqual(payload['review_status'], 'approved')

                conn = sqlite3.connect(db_path)
                try:
                    row = conn.execute("SELECT review_status FROM assets WHERE id = 1").fetchone()
                    self.assertEqual(row[0], 'approved')
                finally:
                    conn.close()
            finally:
                dam_app.DB_PATH = original_db_path
                dam_app.THUMBNAIL_DIR = original_thumbnail_dir

    def test_restore_command_endpoint_quotes_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "assets.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("CREATE TABLE assets (id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT, filepath TEXT)")
                conn.execute(
                    "INSERT INTO assets (project, filepath) VALUES (?, ?)",
                    ("demo", "motion/return to hokai prime 360-4/file.motn"),
                )
                conn.commit()
            finally:
                conn.close()

            original_db_path = dam_app.DB_PATH
            dam_app.DB_PATH = db_path
            try:
                client = dam_app.app.test_client()
                response = client.get('/api/assets/1/restore-command?commit=abc123&mode=copy')
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                expected = "./dam_restore.sh demo 'motion/return to hokai prime 360-4/file.motn' abc123 --copy"
                self.assertEqual(payload['command'], expected)
            finally:
                dam_app.DB_PATH = original_db_path

    def test_dvc_history_endpoint_includes_subdir_for_matching_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "assets.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("CREATE TABLE assets (id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT, filepath TEXT)")
                conn.execute(
                    "INSERT INTO assets (project, filepath) VALUES (?, ?)",
                    ("demo", "motion/return to hokai prime 360-4/file.motn"),
                )
                conn.commit()
            finally:
                conn.close()

            original_db_path = dam_app.DB_PATH
            original_projects_root = dam_app.PROJECTS_ROOT
            dam_app.DB_PATH = db_path
            projects_root = Path(tmpdir) / "projects"
            repo_path = projects_root / "demo"
            repo_path.mkdir(parents=True, exist_ok=True)
            (repo_path / ".dvc" / "cache" / "files" / "md5" / "ab").mkdir(parents=True, exist_ok=True)
            manifest_path = repo_path / ".dvc" / "cache" / "files" / "md5" / "ab" / "cdef1234.dir"
            manifest_path.write_text(json.dumps([{"relpath": "return to hokai prime 360-4/file.motn", "md5": "12345678"}]))
            file_cache_path = repo_path / ".dvc" / "cache" / "files" / "md5" / "12" / "345678"
            file_cache_path.parent.mkdir(parents=True, exist_ok=True)
            file_cache_path.write_bytes(b"test")

            class FakeDataStream:
                def __init__(self, data):
                    self._data = data

                def read(self):
                    return self._data.encode()

            class FakeBlob:
                def __init__(self, data):
                    self.data_stream = FakeDataStream(data)

            class FakeDirectory:
                def __init__(self, content):
                    self._content = content

                def __truediv__(self, part):
                    if part == "assets":
                        return FakeAssetsDir(self._content)
                    raise KeyError(part)

            class FakeAssetsDir:
                def __init__(self, content):
                    self._content = content

                def __truediv__(self, part):
                    if part == "motion.dvc":
                        return FakeBlob(self._content)
                    raise KeyError(part)

            class FakeCommit:
                def __init__(self, hexsha, message, committed_date):
                    self.hexsha = hexsha
                    self.message = message
                    self.author = SimpleNamespace(name="Test Author")
                    self.committed_date = committed_date
                    self.tree = FakeDirectory("outs:\n- md5: abcdef1234.dir\n")

            class FakeRepo:
                def __init__(self, repo_path):
                    self.repo_path = repo_path

                def iter_commits(self, paths=None):
                    return [FakeCommit("abc123def456", "Test commit", 1710000000)]

            try:
                dam_app.PROJECTS_ROOT = projects_root
                with patch.object(dam_app.git, "Repo", return_value=FakeRepo(repo_path)):
                    client = dam_app.app.test_client()
                    response = client.get('/api/assets/1/dvc-history')
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertEqual(payload['subdir'], 'motion')
                self.assertEqual(len(payload['history']), 1)
                self.assertEqual(payload['history'][0]['subdir'], 'motion')
            finally:
                dam_app.DB_PATH = original_db_path
                dam_app.PROJECTS_ROOT = original_projects_root


if __name__ == "__main__":
    unittest.main()
