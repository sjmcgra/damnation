import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dam_index import DAMIndexer
import app as dam_app


class DAMIndexerStoreAssetTest(unittest.TestCase):
    def test_startup_migrates_legacy_database_and_preserves_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "assets.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """CREATE TABLE assets (
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
                        UNIQUE(project, filepath)
                    )"""
                )
                conn.execute(
                    "INSERT INTO assets (project, filepath, filename, tags) VALUES (?, ?, ?, ?)",
                    ("demo", "images/kept.jpg", "kept.jpg", "favorite"),
                )
                conn.commit()
            finally:
                conn.close()

            with patch("dam_index.THUMBNAIL_DIR", root / "thumbnails"), \
                    patch.object(dam_app, "DB_PATH", db_path), \
                    patch.object(dam_app, "PROJECTS_ROOT", root / "projects"):
                dam_app.initialize_database()

            conn = sqlite3.connect(db_path)
            try:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(assets)")}
                self.assertTrue({
                    "review_status", "is_bundle", "bundle_path", "bundle_files",
                    "preview_path", "archived", "archive_source", "used",
                }.issubset(columns))
                row = conn.execute(
                    "SELECT project, filepath, tags FROM assets WHERE id = 1"
                ).fetchone()
                self.assertEqual(row, ("demo", "images/kept.jpg", "favorite"))
                self.assertIsNotNone(conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='review_statuses'"
                ).fetchone())
            finally:
                conn.close()

    def test_upload_image_asset_to_s3(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "assets.db"
            file_path = root / "projects" / "demo" / "assets" / "refs" / "character.jpg"
            file_path.parent.mkdir(parents=True)
            file_path.write_bytes(b"image data")
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "CREATE TABLE assets (id INTEGER PRIMARY KEY, project TEXT, filepath TEXT, "
                    "filename TEXT, file_type TEXT, file_size INTEGER)"
                )
                conn.execute(
                    "INSERT INTO assets (id, project, filepath, filename, file_type, file_size) "
                    "VALUES (1, 'demo', 'refs/character.jpg', 'character.jpg', 'image/jpeg', 10)"
                )
                conn.commit()
            finally:
                conn.close()

            upload_file = unittest.mock.Mock()
            boto3_module = SimpleNamespace(client=unittest.mock.Mock(return_value=SimpleNamespace(upload_file=upload_file)))
            original_values = {
                'DB_PATH': dam_app.DB_PATH,
                'PROJECTS_ROOT': dam_app.PROJECTS_ROOT,
                'S3_UPLOAD_BUCKET': dam_app.S3_UPLOAD_BUCKET,
                'S3_UPLOAD_PUBLIC_URL': dam_app.S3_UPLOAD_PUBLIC_URL,
                'S3_UPLOAD_ENDPOINT_URL': dam_app.S3_UPLOAD_ENDPOINT_URL,
                'S3_UPLOAD_KEY_PREFIX': dam_app.S3_UPLOAD_KEY_PREFIX,
            }
            dam_app.DB_PATH = db_path
            dam_app.PROJECTS_ROOT = root / "projects"
            dam_app.S3_UPLOAD_BUCKET = "default-bucket"
            dam_app.S3_UPLOAD_PUBLIC_URL = "https://cdn.example.test"
            dam_app.S3_UPLOAD_ENDPOINT_URL = ""
            dam_app.S3_UPLOAD_KEY_PREFIX = "references"
            try:
                with patch.dict(sys.modules, {'boto3': boto3_module}):
                    response = dam_app.app.test_client().post(
                        '/api/assets/1/upload-s3',
                        json={'bucket': 'video-bucket', 'public_url': 'https://media.example.test'},
                    )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()['key'], 'references/demo/refs/character.jpg')
                self.assertEqual(
                    response.get_json()['url'],
                    'https://media.example.test/references/demo/refs/character.jpg',
                )
                upload_file.assert_called_once_with(
                    str(file_path),
                    'video-bucket',
                    'references/demo/refs/character.jpg',
                    ExtraArgs={'ContentType': 'image/jpeg'},
                )
            finally:
                for name, value in original_values.items():
                    setattr(dam_app, name, value)

    def test_index_file_skips_unchanged_assets_and_reindexes_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "assets.db"
            projects_root = tmp_path / "projects"
            projects_root.mkdir(parents=True, exist_ok=True)
            source_path = tmp_path / "asset.bin"
            source_path.write_bytes(b"initial")
            relative_path = Path("assets/asset.bin")

            indexer = DAMIndexer(db_path=db_path, projects_root=projects_root)
            self.assertTrue(indexer.index_file("demo", relative_path, source_path, "abc123"))

            with patch.object(indexer, "store_asset", wraps=indexer.store_asset) as store_asset:
                self.assertFalse(indexer.index_file("demo", relative_path, source_path, "def456"))
                store_asset.assert_not_called()

            source_path.write_bytes(b"changed-size")
            self.assertTrue(indexer.index_file("demo", relative_path, source_path, "def456"))

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

    def test_custom_review_status_can_be_assigned_and_removed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "assets.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("CREATE TABLE assets (id INTEGER PRIMARY KEY, review_status TEXT)")
                conn.execute("INSERT INTO assets (id, review_status) VALUES (1, '')")
                conn.commit()
            finally:
                conn.close()

            original_db_path = dam_app.DB_PATH
            dam_app.DB_PATH = db_path
            try:
                client = dam_app.app.test_client()
                response = client.post('/api/review-statuses', json={'name': 'Needs Review'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()['name'], 'needs review')

                response = client.post('/api/assets/1/status', json={'status': 'needs review'})
                self.assertEqual(response.status_code, 200)

                response = client.delete('/api/review-statuses/needs%20review')
                self.assertEqual(response.status_code, 200)

                conn = sqlite3.connect(db_path)
                try:
                    row = conn.execute("SELECT review_status FROM assets WHERE id = 1").fetchone()
                    self.assertEqual(row[0], None)
                finally:
                    conn.close()

                response = client.delete('/api/review-statuses/approved')
                self.assertEqual(response.status_code, 400)
            finally:
                dam_app.DB_PATH = original_db_path

    def test_bulk_edit_assets_updates_tags_and_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "assets.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("CREATE TABLE assets (id INTEGER PRIMARY KEY, tags TEXT, review_status TEXT)")
                conn.executemany("INSERT INTO assets (id, tags, review_status) VALUES (?, ?, ?)", [(1, "old", ""), (2, "existing", "")])
                conn.commit()
            finally:
                conn.close()

            original_db_path = dam_app.DB_PATH
            dam_app.DB_PATH = db_path
            try:
                response = dam_app.app.test_client().post(
                    '/api/assets/bulk-edit',
                    json={'asset_ids': [1, 2], 'tags': 'New, tags', 'status': 'approved'},
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.get_json()['success'])

                conn = sqlite3.connect(db_path)
                try:
                    rows = conn.execute("SELECT tags, review_status FROM assets ORDER BY id").fetchall()
                    self.assertEqual(rows, [("old,new,tags", "approved"), ("existing,new,tags", "approved")])
                finally:
                    conn.close()
            finally:
                dam_app.DB_PATH = original_db_path

    def test_bulk_download_assets_returns_zip_and_missing_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "assets.db"
            file_path = root / "projects" / "demo" / "assets" / "images" / "one.jpg"
            file_path.parent.mkdir(parents=True)
            file_path.write_bytes(b"image")
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("CREATE TABLE assets (id INTEGER PRIMARY KEY, project TEXT, filepath TEXT)")
                conn.executemany("INSERT INTO assets (id, project, filepath) VALUES (?, ?, ?)", [(1, "demo", "images/one.jpg"), (2, "demo", "missing.jpg")])
                conn.commit()
            finally:
                conn.close()

            original_db_path = dam_app.DB_PATH
            original_projects_root = dam_app.PROJECTS_ROOT
            dam_app.DB_PATH = db_path
            dam_app.PROJECTS_ROOT = root / "projects"
            try:
                response = dam_app.app.test_client().post('/api/assets/bulk-download', json={'asset_ids': [1, 2]})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['X-DAM-Missing-Assets'], '1')
                with tempfile.NamedTemporaryFile(suffix='.zip') as archive_file:
                    Path(archive_file.name).write_bytes(response.data)
                    import zipfile
                    with zipfile.ZipFile(archive_file.name) as archive:
                        self.assertEqual(archive.namelist(), ['demo/images/one.jpg'])
            finally:
                dam_app.DB_PATH = original_db_path
                dam_app.PROJECTS_ROOT = original_projects_root

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

    def test_format_file_type_maps_photoshop_files(self):
        self.assertEqual(dam_app.format_file_type("image/vnd.adobe.photoshop"), "Photoshop")

    def test_create_thumbnail_falls_back_for_photoshop_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "assets.db"
            projects_root = tmp_path / "projects"
            projects_root.mkdir(parents=True, exist_ok=True)

            indexer = DAMIndexer(db_path=db_path, projects_root=projects_root)
            indexer.thumbnail_dir = tmp_path / "thumbnails"
            indexer.thumbnail_dir.mkdir(parents=True, exist_ok=True)
            source_path = tmp_path / "sample.psd"
            source_path.write_bytes(b"fake psd")

            def fake_run(command, capture_output=None, text=None, **kwargs):
                output_path = Path(command[-1])
                output_path.write_bytes(b"thumb")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("dam_index.Image.open", side_effect=Exception("unsupported")), patch("dam_index.subprocess.run", side_effect=fake_run):
                thumb = indexer.create_thumbnail(source_path, "demo", Path("assets/sample.psd"))

            self.assertIsNotNone(thumb)
            self.assertTrue((tmp_path / "thumbnails" / "demo").exists())

    def test_create_video_preview_generates_browser_compatible_mp4(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "assets.db"
            projects_root = tmp_path / "projects"
            projects_root.mkdir(parents=True, exist_ok=True)

            indexer = DAMIndexer(db_path=db_path, projects_root=projects_root)
            indexer.thumbnail_dir = tmp_path / "thumbnails"
            indexer.thumbnail_dir.mkdir(parents=True, exist_ok=True)
            source_path = tmp_path / "source.mov"
            source_path.write_bytes(b"fake mov")

            def fake_run(command, capture_output=None, text=None, **kwargs):
                output_path = Path(command[-1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"preview-video")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("dam_index.subprocess.run", side_effect=fake_run):
                preview = indexer.create_video_preview(source_path, "demo", Path("assets/source.mov"))

            self.assertIsNotNone(preview)
            self.assertTrue((tmp_path / "thumbnails" / "demo" / "previews").exists())
            self.assertTrue((tmp_path / "thumbnails" / "demo" / "previews" / Path(preview).name).exists())

    def test_create_video_preview_skips_existing_preview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "assets.db"
            projects_root = tmp_path / "projects"
            projects_root.mkdir(parents=True, exist_ok=True)

            indexer = DAMIndexer(db_path=db_path, projects_root=projects_root)
            indexer.thumbnail_dir = tmp_path / "thumbnails"
            indexer.thumbnail_dir.mkdir(parents=True, exist_ok=True)
            source_path = tmp_path / "source.mov"
            source_path.write_bytes(b"fake mov")

            relative_path = Path("assets/source.mov")
            path_hash = __import__("hashlib").md5(str(relative_path).encode()).hexdigest()[:8]
            preview_dir = indexer.thumbnail_dir / "demo" / "previews"
            preview_dir.mkdir(parents=True, exist_ok=True)
            expected_path = preview_dir / f"{path_hash}_source.mp4"
            expected_path.write_bytes(b"already-transcoded")

            with patch("dam_index.subprocess.run") as fake_run:
                preview = indexer.create_video_preview(source_path, "demo", relative_path)

            self.assertIsNotNone(preview)
            fake_run.assert_not_called()
            self.assertTrue(expected_path.exists())

    def test_view_file_prefers_preview_for_quicktime_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            projects_root = root / "projects"
            project_dir = projects_root / "demo" / "assets"
            project_dir.mkdir(parents=True, exist_ok=True)
            source_path = project_dir / "clip.mov"
            source_path.write_bytes(b"prores-mov")

            preview_dir = root / "thumbnails" / "demo" / "previews"
            preview_dir.mkdir(parents=True, exist_ok=True)
            preview_path = preview_dir / "preview.mp4"
            preview_path.write_bytes(b"converted-preview")

            original_db_path = dam_app.DB_PATH
            original_projects_root = dam_app.PROJECTS_ROOT
            original_thumbnail_dir = dam_app.THUMBNAIL_DIR
            dam_app.DB_PATH = root / "assets.db"
            dam_app.PROJECTS_ROOT = projects_root
            dam_app.THUMBNAIL_DIR = root / "thumbnails"
            try:
                db = dam_app.get_db()
                try:
                    db.execute("CREATE TABLE assets (id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT, filepath TEXT, preview_path TEXT)")
                    db.execute(
                        "INSERT INTO assets (project, filepath, preview_path) VALUES (?, ?, ?)",
                        ("demo", "assets/clip.mov", "thumbnails/demo/previews/preview.mp4"),
                    )
                    db.commit()
                finally:
                    db.close()

                response = dam_app.app.test_client().get('/view/demo/assets/clip.mov')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, 'video/mp4')
                self.assertEqual(response.data, b'converted-preview')
            finally:
                dam_app.DB_PATH = original_db_path
                dam_app.PROJECTS_ROOT = original_projects_root
                dam_app.THUMBNAIL_DIR = original_thumbnail_dir

    def test_index_template_prevents_review_status_select_from_triggering_card_navigation(self):
        template_path = Path(__file__).resolve().parents[1] / "templates" / "index.html"
        template_source = template_path.read_text()

        self.assertIn('class="card asset-card"', template_source)
        self.assertIn("document.addEventListener('DOMContentLoaded'", template_source)
        self.assertIn("button.addEventListener('click'", template_source)

    def test_index_template_includes_inline_media_preview_controls(self):
        template_path = Path(__file__).resolve().parents[1] / "templates" / "index.html"
        template_source = template_path.read_text()

        self.assertIn("preview-modal", template_source)
        self.assertIn("data-preview-url", template_source)
        self.assertIn("Preview", template_source)

    def test_asset_missing_and_moved_file_resolution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_root = Path(tmpdir) / "projects"
            project_assets = projects_root / "demo" / "assets"
            moved_path = project_assets / "archive" / "original.psd"
            moved_path.parent.mkdir(parents=True, exist_ok=True)
            moved_path.write_bytes(b"psd")

            original_db_path = dam_app.PROJECTS_ROOT
            dam_app.PROJECTS_ROOT = projects_root
            try:
                resolved_path, resolved_rel = dam_app.resolve_asset_path("demo", "images/original.psd")
                self.assertEqual(resolved_path, moved_path)
                self.assertEqual(resolved_rel, "archive/original.psd")
                self.assertFalse(dam_app.is_asset_missing("demo", "images/original.psd"))
            finally:
                dam_app.PROJECTS_ROOT = original_db_path

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
