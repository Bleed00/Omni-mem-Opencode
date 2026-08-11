import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omni_mem.data import (
    add_placeholder_sessions,
    merge_records,
    reconcile_sessions_with_db,
    stable_key,
    write_records,
)


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

    def test_stale_session_memory_id_is_rewritten_to_local(self):
        payload = {
            "sessions": [
                {
                    "platform_source": "claude",
                    "content_session_id": "content-a",
                    "memory_session_id": "stale-id",
                }
            ],
            "observations": [
                {
                    "memory_session_id": "stale-id",
                    "title": "obs",
                    "created_at_epoch": 1,
                }
            ],
            "summaries": [
                {"memory_session_id": "stale-id", "created_at_epoch": 1}
            ],
        }
        local = [
            {
                "platform_source": "claude",
                "content_session_id": "content-a",
                "memory_session_id": "local-id",
            }
        ]
        with mock.patch("omni_mem.data.load_sessions", return_value=local):
            result = reconcile_sessions_with_db(payload)
        session = result["sessions"][0]
        self.assertEqual(session["memory_session_id"], "local-id")
        self.assertEqual(result["observations"][0]["memory_session_id"], "local-id")
        self.assertEqual(result["summaries"][0]["memory_session_id"], "local-id")

    def test_payload_session_duplicating_local_memory_id_is_dropped(self):
        payload = {
            "sessions": [
                {
                    "platform_source": "claude",
                    "content_session_id": "content-b",
                    "memory_session_id": "shared-id",
                }
            ]
        }
        local = [
            {
                "platform_source": "claude",
                "content_session_id": "content-a",
                "memory_session_id": "shared-id",
            }
        ]
        with mock.patch("omni_mem.data.load_sessions", return_value=local):
            result = reconcile_sessions_with_db(payload)
        self.assertEqual(result["sessions"], [])

    def test_new_session_is_left_untouched(self):
        payload = {
            "sessions": [
                {
                    "platform_source": "claude",
                    "content_session_id": "content-c",
                    "memory_session_id": "brand-new-id",
                }
            ]
        }
        with mock.patch("omni_mem.data.load_sessions", return_value=[]):
            result = reconcile_sessions_with_db(payload)
        self.assertEqual(result["sessions"][0]["memory_session_id"], "brand-new-id")


if __name__ == "__main__":
    unittest.main()
