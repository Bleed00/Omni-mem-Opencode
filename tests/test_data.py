import json
import tempfile
import unittest
from pathlib import Path

from omni_mem.data import add_placeholder_sessions, merge_records, stable_key, write_records


class DataKeyTests(unittest.TestCase):
    def test_observation_key_does_not_use_local_numeric_id(self):
        first = {
            "id": 1,
            "memory_session_id": "session-a",
            "title": "same title",
            "created_at_epoch": 100,
        }
        second = {**first, "id": 999}
        self.assertEqual(stable_key("observations", first), stable_key("observations", second))

    def test_different_observations_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            first = {
                "id": 1,
                "memory_session_id": "session-a",
                "title": "first",
                "created_at_epoch": 100,
            }
            second = {
                "id": 1,
                "memory_session_id": "session-b",
                "title": "second",
                "created_at_epoch": 200,
            }
            write_records(path / "observations.json", [first])
            merged = merge_records(path, "observations", [second])
            self.assertEqual(len(merged), 2)

    def test_records_are_sorted_deterministically(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            records = [
                {"id": 2, "memory_session_id": "b", "title": "b", "created_at_epoch": 2},
                {"id": 1, "memory_session_id": "a", "title": "a", "created_at_epoch": 1},
            ]
            write_records(path / "observations.json", merge_records(path, "observations", records))
            loaded = json.loads((path / "observations.json").read_text())
            self.assertEqual([item["id"] for item in loaded], [1, 2])

    def test_orphan_observation_gets_placeholder_session(self):
        observations = [
            {
                "memory_session_id": "orphan-session",
                "project": "project",
                "platform_source": "claude",
                "created_at": "2026-01-01T00:00:00Z",
                "created_at_epoch": 1,
            }
        ]
        sessions = add_placeholder_sessions([], observations)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["memory_session_id"], "orphan-session")


if __name__ == "__main__":
    unittest.main()
