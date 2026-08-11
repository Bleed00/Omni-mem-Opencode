import unittest
from pathlib import Path
from unittest.mock import patch

from omni_mem.service_windows import TASK_NAME, schtasks_command_line


class SchtasksCommandLineTests(unittest.TestCase):
    def test_command_line_escapes_embedded_paths(self):
        with patch(
            "omni_mem.service_windows.pythonw_path",
            return_value="C:\\Python314\\pythonw.exe",
        ), patch(
            "omni_mem.service_windows.config_dir",
            return_value=Path("C:\\AppData\\omni-mem"),
        ):
            line = schtasks_command_line()
        expected_log = str(Path("C:\\AppData\\omni-mem") / "watch.log")
        self.assertIn(
            f'/TR "\\"C:\\Python314\\pythonw.exe\\" -m omni_mem watch --log \\"{expected_log}\\""',
            line,
        )
        self.assertIn(f'/TN "{TASK_NAME}"', line)
        self.assertIn("/SC ONLOGON", line)
        self.assertIn("/RL LIMITED", line)
        self.assertIn("/F", line)


if __name__ == "__main__":
    unittest.main()
