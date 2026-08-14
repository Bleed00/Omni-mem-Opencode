import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from anywhere_claude_mem.data import (
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

    def test_observation_key_ignores_regenerated_session_ids(self):
        first = {
            "id": 1,
            "memory_session_id": "openrouter-opencode-ses_0145910a0ffeO8pjdXZgjmHv4J-1786443234938-1786456890955",
            "title": "same title",
            "created_at_epoch": 100,
        }
        second = {
            "id": 2,
            "memory_session_id": "openrouter-opencode-ses_0145910a0ffeO8pjdXZgjmHv4J-1786443234938-1786457075083",
            "title": "same title",
            "created_at_epoch": 100,
        }
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
        with mock.patch("anywhere_claude_mem.data.load_sessions", return_value=local):
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
        with mock.patch("anywhere_claude_mem.data.load_sessions", return_value=local):
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
        with mock.patch("anywhere_claude_mem.data.load_sessions", return_value=[]):
            result = reconcile_sessions_with_db(payload)
        self.assertEqual(result["sessions"][0]["memory_session_id"], "brand-new-id")

    def test_payload_sessions_sharing_memory_id_are_deduplicated_on_first_import(self):
        # A first import can receive a real session row plus its
        # add_placeholder_sessions twin, both carrying the SAME memory_session_id.
        # The UNIQUE constraint on sdk_sessions.memory_session_id would be violated
        # if both were forwarded, so only the first row must be kept.
        payload = {
            "sessions": [
                {
                    "platform_source": "claude",
                    "content_session_id": "openrouter-session-abc-1786",
                    "memory_session_id": "session-abc-1786",
                },
                {
                    "platform_source": "claude",
                    "content_session_id": "session-abc-1786",
                    "memory_session_id": "session-abc-1786",
                },
            ],
            "observations": [
                {
                    "memory_session_id": "session-abc-1786",
                    "title": "obs",
                    "created_at_epoch": 1,
                }
            ],
            "summaries": [],
        }
        with mock.patch("anywhere_claude_mem.data.load_sessions", return_value=[]):
            result = reconcile_sessions_with_db(payload)
        self.assertEqual(len(result["sessions"]), 1)
        self.assertEqual(result["sessions"][0]["content_session_id"], "openrouter-session-abc-1786")
        self.assertEqual(result["observations"][0]["memory_session_id"], "session-abc-1786")


class TombstoneTests(unittest.TestCase):
    def test_record_signature_ignores_id_and_memory_session_id(self):
        from anywhere_claude_mem.data import record_signature

        base = {
            "id": 1,
            "memory_session_id": "regenerated-a",
            "title": "same",
            "text": "same content",
            "created_at_epoch": 100,
        }
        same_elsewhere = {
            "id": 999,
            "memory_session_id": "regenerated-b",
            "title": "same",
            "text": "same content",
            "created_at_epoch": 100,
        }
        changed = {**base, "text": "different content"}
        self.assertEqual(record_signature("observations", base), record_signature("observations", same_elsewhere))
        self.assertNotEqual(record_signature("observations", base), record_signature("observations", changed))

    def test_tombstones_roundtrip_and_prune(self):
        from anywhere_claude_mem.data import read_tombstones, write_tombstones, prune_tombstoned

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            tombstones = {
                "sessions": {"claude\0content-a"},
                "observations": {stable_key("observations", {"title": "x", "created_at_epoch": 1})},
                "summaries": set(),
                "prompts": set(),
            }
            write_tombstones(path, tombstones)
            self.assertEqual(len(read_tombstones(path)["observations"]), 1)
            records = [
                {"title": "x", "created_at_epoch": 1},
                {"title": "y", "created_at_epoch": 2},
            ]
            pruned = prune_tombstoned(
                "observations",
                records,
                {"sessions": set(), "observations": tombstones["observations"], "summaries": set(), "prompts": set()},
            )
            self.assertEqual(len(pruned), 1)
            self.assertEqual(pruned[0]["title"], "y")

    def test_merge_tombstones_returns_union(self):
        from anywhere_claude_mem.data import merge_tombstones

        merged = merge_tombstones(
            {"sessions": {"a"}, "observations": {"b"}, "summaries": set(), "prompts": set()},
            {"sessions": {"a", "c"}, "observations": set(), "summaries": set(), "prompts": set()},
        )
        self.assertEqual(merged["sessions"], {"a", "c"})

    def test_plan_deletions_detects_modification_and_tombstone(self):
        from anywhere_claude_mem.data import plan_deletions

        payload_obs = {
            "id": 10, "memory_session_id": "m", "title": "same",
            "text": "new", "created_at_epoch": 100,
        }
        local_old = {
            "id": 1, "memory_session_id": "m", "title": "same",
            "text": "old", "created_at_epoch": 100,
        }
        local_same = {
            "id": 2, "memory_session_id": "m", "title": "other",
            "text": "same", "created_at_epoch": 200,
        }
        payload = {"sessions": [], "observations": [payload_obs], "summaries": [], "prompts": []}
        local = {"sessions": [], "observations": [local_old, local_same], "summaries": [], "prompts": []}
        tombstones = {"sessions": set(), "observations": set(), "summaries": set(), "prompts": set()}
        plan = plan_deletions(payload, local, tombstones)
        # same key (title+epoch) but different content -> local id deleted and re-imported
        self.assertEqual(plan["observations"], [1])

    def test_plan_deletions_skips_identical_records(self):
        from anywhere_claude_mem.data import plan_deletions

        obs = {"id": 1, "memory_session_id": "m", "title": "same", "text": "same", "created_at_epoch": 100}
        payload = {"sessions": [], "observations": [obs], "summaries": [], "prompts": []}
        local = {"sessions": [], "observations": [obs], "summaries": [], "prompts": []}
        tombstones = {"sessions": set(), "observations": set(), "summaries": set(), "prompts": set()}
        plan = plan_deletions(payload, local, tombstones)
        self.assertEqual(plan["observations"], [])

    def test_plan_deletions_tombstoned_key_is_removed(self):
        from anywhere_claude_mem.data import plan_deletions

        obs = {"id": 1, "memory_session_id": "m", "title": "gone", "created_at_epoch": 100}
        payload = {"sessions": [], "observations": [], "summaries": [], "prompts": []}
        local = {"sessions": [], "observations": [obs], "summaries": [], "prompts": []}
        tombstones = {
            "sessions": set(),
            "observations": {stable_key("observations", obs)},
            "summaries": set(),
            "prompts": set(),
        }
        plan = plan_deletions(payload, local, tombstones)
        self.assertEqual(plan["observations"], [1])


if __name__ == "__main__":
    unittest.main()
