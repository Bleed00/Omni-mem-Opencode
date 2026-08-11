import unittest
from pathlib import Path
from unittest.mock import patch

from omni_mem.config import Config
from omni_mem.service_windows import (
    RUN_KEY,
    TASK_NAME,
    install,
    remove,
    run_command_line,
    status,
)


class RunCommandLineTests(unittest.TestCase):
    def test_command_line_quotes_pythonw_and_log(self):
        with patch(
            "omni_mem.service_windows.pythonw_path",
            return_value="C:\\Python314\\pythonw.exe",
        ), patch(
            "omni_mem.service_windows.config_dir",
            return_value=Path("C:\\AppData\\omni-mem"),
        ):
            line = run_command_line()
        expected_log = str(Path("C:\\AppData\\omni-mem") / "watch.log")
        self.assertEqual(
            line,
            f'"C:\\Python314\\pythonw.exe" -m omni_mem watch --log "{expected_log}"',
        )


class RunKeyRegistryTests(unittest.TestCase):
    def _config(self) -> Config:
        return Config(wrapper_dir="C:\\repo", data_repo_dir="C:\\repo\\data")

    def test_install_writes_run_value(self):
        with patch("omni_mem.service_windows.winreg") as mock_winreg:
            mock_key = mock_winreg.OpenKey.return_value.__enter__.return_value
            with patch(
                "omni_mem.service_windows.run_command_line",
                return_value="the-command",
            ):
                install(self._config(), None)
            mock_winreg.OpenKey.assert_called_once_with(
                mock_winreg.HKEY_CURRENT_USER, RUN_KEY, 0, mock_winreg.KEY_SET_VALUE
            )
            mock_winreg.SetValueEx.assert_called_once_with(
                mock_key, TASK_NAME, 0, mock_winreg.REG_SZ, "the-command"
            )

    def test_remove_deletes_run_value(self):
        with patch("omni_mem.service_windows.winreg") as mock_winreg:
            with patch("omni_mem.service_windows.subprocess.run") as mock_run:
                remove()
        mock_winreg.DeleteValue.assert_called_once_with(
            mock_winreg.OpenKey.return_value.__enter__.return_value, TASK_NAME
        )
        self.assertEqual(mock_run.call_count, 1)

    def test_remove_ignores_missing_value(self):
        with patch("omni_mem.service_windows.winreg") as mock_winreg:
            mock_winreg.DeleteValue.side_effect = FileNotFoundError
            with patch("omni_mem.service_windows.subprocess.run") as mock_run:
                remove()
        mock_winreg.DeleteValue.assert_called_once()
        self.assertEqual(mock_run.call_count, 1)

    def test_status_enabled_when_value_present(self):
        with patch("omni_mem.service_windows.winreg") as mock_winreg:
            self.assertEqual(status(), "enabled")

    def test_status_inactive_when_value_missing(self):
        with patch("omni_mem.service_windows.winreg") as mock_winreg:
            mock_winreg.QueryValueEx.side_effect = FileNotFoundError
            self.assertEqual(status(), "inactive")


if __name__ == "__main__":
    unittest.main()
