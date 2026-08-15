import subprocess
import tempfile
import unittest
from pathlib import Path

from anywhere_claude_mem import git


class CleanupTempArtifactsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_removes_stray_temp_and_backup_files(self):
        (self.repo / "tmp12345678").write_text("stray temp")
        (self.repo / "observations.json.bak").write_text("stray backup")
        (self.repo / "something.tmp").write_text("stray tmp")
        (self.repo / "observations.json").write_text("{}")  # real data kept

        removed = git.cleanup_temp_artifacts(self.repo)

        self.assertEqual(removed, 3)
        self.assertFalse((self.repo / "tmp12345678").exists())
        self.assertFalse((self.repo / "observations.json.bak").exists())
        self.assertFalse((self.repo / "something.tmp").exists())
        self.assertTrue((self.repo / "observations.json").exists())

    def test_returns_zero_when_nothing_to_clean(self):
        (self.repo / "observations.json").write_text("{}")
        self.assertEqual(git.cleanup_temp_artifacts(self.repo), 0)


class DirtyJsonTests(unittest.TestCase):
    def _init_repo(self):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "t@t.t"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.name", "Test"],
            check=True,
            capture_output=True,
        )

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self._init_repo()
        (self.repo / "sessions.json").write_text("[]")
        subprocess.run(
            ["git", "-C", str(self.repo), "add", "sessions.json"], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "init"],
            check=True,
            capture_output=True,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_stray_untracked_tmp_does_not_count_as_dirty(self):
        (self.repo / "tmp01234567").write_text("noise")
        self.assertFalse(git.dirty_json(self.repo))

    def test_tracked_json_change_counts_as_dirty(self):
        (self.repo / "sessions.json").write_text("[{}]")  # modified tracked json
        self.assertTrue(git.dirty_json(self.repo))

    def test_new_tracked_json_counts_as_dirty(self):
        (self.repo / "prompts.json").write_text("[]")  # new untracked json, not tmp/bak
        subprocess.run(
            ["git", "-C", str(self.repo), "add", "prompts.json"], check=True, capture_output=True
        )
        self.assertTrue(git.dirty_json(self.repo))


if __name__ == "__main__":
    unittest.main()
