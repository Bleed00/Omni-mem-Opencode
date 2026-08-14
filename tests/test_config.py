import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anywhere_claude_mem.config import AutoSyncConfig, Config, config_dir, load_config, save_config


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
            with patch("anywhere_claude_mem.config.config_dir", return_value=config_dir):
                save_config(config)
                loaded = load_config()
            self.assertEqual(loaded.data_repo_url, config.data_repo_url)
            self.assertEqual(loaded.auto_sync.observations_per_push, 10)
            if os.name == "posix":
                self.assertEqual((config_dir / "config.json").stat().st_mode & 0o777, 0o600)

    def test_config_round_trip_default_platform_is_opencode(self):
        with tempfile.TemporaryDirectory() as directory:
            config_dir = Path(directory) / "config"
            config = Config(
                wrapper_dir=directory,
                data_repo_dir=str(Path(directory) / "data"),
            )
            with patch("anywhere_claude_mem.config.config_dir", return_value=config_dir):
                save_config(config)
                loaded = load_config()
            self.assertEqual(loaded.platform, "opencode")
            self.assertEqual(loaded.dsh_profile, "")

    def test_config_round_trip_deepseek_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            config_dir = Path(directory) / "config"
            config = Config(
                wrapper_dir=directory,
                data_repo_dir=str(Path(directory) / "data"),
                platform="deepseek",
                dsh_profile="web",
            )
            with patch("anywhere_claude_mem.config.config_dir", return_value=config_dir):
                save_config(config)
                loaded = load_config()
            self.assertEqual(loaded.platform, "deepseek")
            self.assertEqual(loaded.dsh_profile, "web")

    def test_unknown_platform_normalizes_to_opencode(self):
        import json as _json

        with tempfile.TemporaryDirectory() as directory:
            config_dir = Path(directory) / "config"
            cfg = Config(
                wrapper_dir=directory,
                data_repo_dir=str(Path(directory) / "data"),
                platform="unknown",
            )
            with patch("anywhere_claude_mem.config.config_dir", return_value=config_dir):
                save_config(cfg)
                path = config_dir / "config.json"
                with path.open() as stream:
                    raw = _json.load(stream)
                raw["platform"] = "bogus"
                path.write_text(_json.dumps(raw))
                loaded = load_config()
            self.assertEqual(loaded.platform, "opencode")

    def test_config_dir_uses_apdata_on_windows(self):
        with patch("anywhere_claude_mem.config.sys.platform", "win32"), patch.dict(
            os.environ, {"APPDATA": "C:\\Users\\test\\AppData\\Roaming"}
        ):
            self.assertEqual(
                str(config_dir()),
                os.path.join("C:\\Users\\test\\AppData\\Roaming", "anywhere-claude-mem"),
            )


if __name__ == "__main__":
    unittest.main()
