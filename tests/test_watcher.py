import unittest

from anywhere_claude_mem.watcher import pending_observations


class WatcherTests(unittest.TestCase):
    def test_pending_observation_count(self):
        self.assertEqual(pending_observations({"a", "b", "c"}, {"a"}), 2)

    def test_seen_observations_do_not_trigger_push(self):
        self.assertEqual(pending_observations({"a", "b"}, {"a", "b"}), 0)


if __name__ == "__main__":
    unittest.main()
