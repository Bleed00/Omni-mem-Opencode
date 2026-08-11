import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from omni_mem.config import AutoSyncConfig, Config, load_config, save_config


class ConfigTests(unittest.TestCase):
    def test_config_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            config_dir = Path(directory) / "config"
            config = Config(
                wrapper_dir=directory,
                data_repo_dir=str(Path(directory) / "data"),
                data_repo_url="https://github.com/example/data.git",
                auto_sync=AutoSyncConfig(True, 10, 2.0, 3.0),
            )
            with patch("omni_mem.config.config_dir", return_value=config_dir):
                save_config(config)
                loaded = load_config()
            self.assertEqual(loaded.data_repo_url, config.data_repo_url)
            self.assertEqual(loaded.auto_sync.observations_per_push, 10)
            self.assertEqual((config_dir / "config.json").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
