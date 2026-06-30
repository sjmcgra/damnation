import sqlite3
import tempfile
import unittest
from pathlib import Path

from dam_index import DAMIndexer


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


if __name__ == "__main__":
    unittest.main()
