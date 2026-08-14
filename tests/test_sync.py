import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from anywhere_claude_mem.config import AutoSyncConfig, Config, StartupPullConfig
from anywhere_claude_mem.data import stable_key
from anywhere_claude_mem.sync import SyncEngine


class FakeWorker:
    """In-memory stand-in for the claude-mem worker API.

    Dedupes imports by stable key, mirroring the worker's documented contract,
    so idempotency assertions at the engine level stay meaningful.
    """

    def __init__(self):
        self.observations: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.summaries: dict[str, dict] = {}
        self.prompts: dict[str, dict] = {}
        self._next_id = 1
        self.delete_calls: list[tuple[str, int]] = []
        self.import_calls: list[dict] = []

    def check(self) -> None:
        return None

    def fetch_all(self, endpoint: str) -> list[dict]:
        kind = endpoint.rstrip("/").split("/")[-1]
        store = {"observations": self.observations, "sessions": self.sessions,
                 "summaries": self.summaries, "prompts": self.prompts}[kind]
        return list(store.values())

    def import_data(self, payload: dict) -> dict:
        self.import_calls.append(payload)
        for kind in ("sessions", "observations", "summaries", "prompts"):
            store = {"sessions": self.sessions, "observations": self.observations,
                     "summaries": self.summaries, "prompts": self.prompts}[kind]
            for item in payload.get(kind, []):
                key = stable_key(kind, item)
                if key not in store:
                    item = dict(item)
                    if "id" not in item or item["id"] is None:
                        item["id"] = self._next_id
                        self._next_id += 1
                    store[key] = item
        return {"imported": len(payload.get("observations", []))}

    def delete(self, kind: str, record_id: int) -> bool:
        self.delete_calls.append((kind, record_id))
        store = {"observations": self.observations, "sessions": self.sessions,
                 "summaries": self.summaries, "prompts": self.prompts}[kind]
        for key, item in list(store.items()):
            if item.get("id") == record_id:
                del store[key]
        return True

    def seed_observation(self, title: str, text: str, epoch: int, session_id: str) -> None:
        item = {
            "id": self._next_id,
            "memory_session_id": session_id,
            "title": title,
            "text": text,
            "created_at_epoch": epoch,
        }
        self._next_id += 1
        self.observations[stable_key("observations", item)] = item


def _make_config(data_dir: Path) -> Config:
    return Config(
        wrapper_dir=str(data_dir.parent),
        data_repo_dir=str(data_dir),
        data_repo_url="origin",
        auto_sync=AutoSyncConfig(enabled=False),
        startup_pull=StartupPullConfig(enabled=False),
    )


class GitRepoTestCase(unittest.TestCase):
    """Helpers to build a local bare origin plus a clone, no network needed."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        self.data_dir = self.root / "data"
        subprocess.run(["git", "clone", str(self.remote), str(self.data_dir)],
                       check=True, capture_output=True)
        for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
            subprocess.run(["git", "-C", str(self.data_dir), "config", key, value],
                           check=True, capture_output=True)
        self._config = _make_config(self.data_dir)

        self._patchers = [
            mock.patch("anywhere_claude_mem.sync.WorkerClient", return_value=self.worker),
            mock.patch("anywhere_claude_mem.sync.observation_fingerprints", return_value=set()),
            mock.patch("anywhere_claude_mem.data.load_sessions", return_value=[]),
            mock.patch("anywhere_claude_mem.data.delete_local_sessions", return_value=0),
            mock.patch("anywhere_claude_mem.config.config_dir", return_value=self.root / "cfg"),
        ]
        for patcher in self._patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self._patchers):
            patcher.stop()
        self._tmp.cleanup()


class FirstPushTests(GitRepoTestCase):
    def setUp(self):
        self.worker = FakeWorker()
        super().setUp()

    def test_first_push_on_empty_clone_succeeds(self):
        self.worker.seed_observation("hello", "first memory", 1, "ses-1")
        engine = SyncEngine(self._config)
        engine.push()

        self.assertTrue((self.data_dir / ".git").is_dir())
        self.assertTrue((self.data_dir / "observations.json").exists())
        remote_branches = subprocess.run(
            ["git", "--git-dir", str(self.remote), "branch", "-a"],
            capture_output=True, text=True, check=True,
        ).stdout
        self.assertIn("main", remote_branches)

    def test_push_with_nothing_new_produces_no_commit(self):
        self.worker.seed_observation("hello", "first memory", 1, "ses-1")
        engine = SyncEngine(self._config)
        engine.push()
        before = subprocess.run(
            ["git", "-C", str(self.data_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        engine.push()
        after = subprocess.run(
            ["git", "-C", str(self.data_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(before, after)

    def test_push_recovers_when_first_push_committed_but_never_set_upstream(self):
        # Simulate a first push whose network step failed: local commit exists,
        # but the branch still has no upstream configured.
        (self.data_dir / "seed.json").write_text("[]\n")
        subprocess.run(["git", "-C", str(self.data_dir), "add", "-A", "--", "*.json"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.data_dir), "commit", "-m", "partial", "-q"],
                       check=True, capture_output=True)

        self.worker.seed_observation("hello", "first memory", 1, "ses-1")
        SyncEngine(self._config).push()

        remote_branches = subprocess.run(
            ["git", "--git-dir", str(self.remote), "branch", "-a"],
            capture_output=True, text=True, check=True,
        ).stdout
        self.assertIn("main", remote_branches)
        upstream = subprocess.run(
            ["git", "-C", str(self.data_dir), "rev-parse", "--abbrev-ref", "@{u}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(upstream, "origin/main")


class RoundTripTests(GitRepoTestCase):
    def setUp(self):
        self.worker = FakeWorker()
        super().setUp()

    def test_push_then_pull_on_fresh_worker_imports_records(self):
        self.worker.seed_observation("note", "body", 1, "ses-1")
        engine = SyncEngine(self._config)
        engine.push()

        fresh = FakeWorker()
        with mock.patch("anywhere_claude_mem.sync.WorkerClient", return_value=fresh):
            engine.pull()
        self.assertEqual(len(fresh.observations), 1)
        self.assertEqual(list(fresh.observations.values())[0]["title"], "note")

    def test_second_pull_is_idempotent(self):
        self.worker.seed_observation("note", "body", 1, "ses-1")
        engine = SyncEngine(self._config)
        engine.push()

        fresh = FakeWorker()
        with mock.patch("anywhere_claude_mem.sync.WorkerClient", return_value=fresh):
            engine.pull()
            engine.pull()

        self.assertEqual(len(fresh.observations), 1)
        self.assertEqual(fresh.delete_calls, [])


class MergeRemoteJsonTests(unittest.TestCase):
    def test_merge_unions_local_and_remote_records(self):
        from anywhere_claude_mem import data as data_module

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            local = [
                {"title": "a", "created_at_epoch": 1, "text": "local"},
                {"title": "shared", "created_at_epoch": 2, "text": "local-wins"},
            ]
            remote = [
                {"title": "b", "created_at_epoch": 3, "text": "remote"},
                {"title": "shared", "created_at_epoch": 2, "text": "remote-loses"},
            ]
            for kind, records in (("observations", local),):
                data_module.write_records(path / f"{kind}.json", records)

            git = mock.patch("anywhere_claude_mem.sync.git.run")
            fake_run = git.start()
            self.addCleanup(git.stop)
            ref_patch = mock.patch("anywhere_claude_mem.sync.git.ref")
            fake_ref = ref_patch.start()
            self.addCleanup(ref_patch.stop)

            def run_side_effect(repo, *args, check=True):
                if args and args[0] == "show":
                    target = args[1].split(":")[1]
                    if target == "observations.json":
                        return json.dumps(remote)
                return ""

            fake_run.side_effect = run_side_effect
            fake_ref.side_effect = lambda repo, name: (
                "local-head" if name == "HEAD" else "remote-head"
            )

            config = _make_config(path)
            SyncEngine(config).merge_remote_json()

            merged = data_module.read_records(path / "observations.json")
            self.assertEqual(len(merged), 3)
            shared = next(item for item in merged if item["title"] == "shared")
            self.assertEqual(shared["text"], "local-wins")


class PullRecoveryTests(unittest.TestCase):
    def test_rebase_conflict_falls_back_to_merge_remote_json(self):
        from anywhere_claude_mem.git import GitError

        config = _make_config(Path(tempfile.mkdtemp()))
        engine = SyncEngine(config)

        with mock.patch("anywhere_claude_mem.sync.git.run") as run:
            def fake_run(repo, *args, check=True):
                if args[:2] == ("pull", "--rebase"):
                    raise GitError("conflict")
                return ""

            run.side_effect = fake_run
            with mock.patch.object(engine, "merge_remote_json") as merged:
                engine.pull_with_recovery()
            merged.assert_called_once()
            abort_calls = [c for c in run.call_args_list if c.args[1:3] == ("rebase", "--abort")]
            self.assertEqual(len(abort_calls), 1)

    def test_recover_incomplete_operation_aborts_rebase_and_merge(self):
        config = _make_config(Path(tempfile.mkdtemp()))
        engine = SyncEngine(config)
        with mock.patch("anywhere_claude_mem.sync.git.run") as run:
            engine.recover_incomplete_git_operation()
            commands = [c.args[1:3] for c in run.call_args_list]
            self.assertIn(("rebase", "--abort"), commands)
            self.assertIn(("merge", "--abort"), commands)


if __name__ == "__main__":
    unittest.main()
