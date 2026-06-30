import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
