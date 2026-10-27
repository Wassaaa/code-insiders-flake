import json
import io
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import updater


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.metafile = Path(self.tmpdir.name) / "meta.json"
        self.old = {"version": "old", "sha256": "old-hash", "url": "old-url"}
        self.new = {"version": "new", "sha256": "new-hash", "url": "new-url"}
        self.metafile.write_text(json.dumps(self.old), encoding="utf-8")

    def run_update(self):
        updater.main(str(self.metafile), self.tmpdir.name, "owner/repo", "123")

    def test_reads_version_from_archive_with_dot_prefix(self):
        archive_path = Path(self.tmpdir.name) / "sample.tar.gz"
        data = json.dumps({"version": "1.2.3-insider"}).encode()
        with tarfile.open(archive_path, "w:gz") as archive:
            info = tarfile.TarInfo("./" + updater.PACKAGE_JSON)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))

        with patch("updater.urlretrieve", return_value=(str(archive_path), None)), \
                patch("updater.subprocess.check_output", return_value="hash\n"):
            meta, filename = updater.download_insiders(self.tmpdir.name, "owner/repo", "123")
        self.assertEqual(meta["version"], "1.2.3-insider")
        self.assertEqual(meta["sha256"], "hash")
        self.assertEqual(filename, str(archive_path))

    @patch("updater.subprocess.run")
    def test_git_failure_stops_the_commit(self, run):
        run.side_effect = subprocess.CalledProcessError(1, ["git"])
        with self.assertRaises(subprocess.CalledProcessError):
            updater.commit("meta.json", "message")
        self.assertEqual(run.call_count, 1)

    @patch("updater.commit")
    @patch("updater.create_github_release")
    @patch("updater.download_insiders")
    def test_unchanged_snapshot_is_not_published(self, download, release, commit):
        download.return_value = (self.old, "archive")
        self.run_update()
        release.assert_not_called()
        commit.assert_not_called()
        self.assertEqual(json.loads(self.metafile.read_text(encoding="utf-8")), self.old)

    @patch("updater.commit")
    @patch("updater.create_github_release")
    @patch("updater.download_insiders")
    def test_upload_failure_does_not_change_metadata(self, download, release, commit):
        download.return_value = (self.new, "archive")
        release.side_effect = RuntimeError("upload failed")
        with self.assertRaisesRegex(RuntimeError, "upload failed"):
            self.run_update()
        commit.assert_not_called()
        self.assertEqual(json.loads(self.metafile.read_text(encoding="utf-8")), self.old)

    @patch("updater.commit")
    @patch("updater.create_github_release")
    @patch("updater.download_insiders")
    def test_release_is_uploaded_before_metadata_is_written(self, download, release, commit):
        download.return_value = (self.new, "archive")

        def verify_before_upload(*args):
            self.assertEqual(json.loads(self.metafile.read_text(encoding="utf-8")), self.old)

        release.side_effect = verify_before_upload
        self.run_update()
        release.assert_called_once_with("archive", self.new, "owner/repo", "123")
        self.assertEqual(json.loads(self.metafile.read_text(encoding="utf-8")), self.new)
        commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
