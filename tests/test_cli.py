import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omni_mem import cli

WRAPPER = Path("/wrapper")  # overridden in setUp


class InstallStartupTriggerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.wrapper = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    @mock.patch("omni_mem.cli.WRAPPER_DIR", Path("/wrapper"))
    def test_opencode_path_writes_plugin_and_registers(self):
        with mock.patch("omni_mem.cli.write_opencode_startup_plugin") as write_plugin, \
                mock.patch("omni_mem.cli.register_opencode_plugin") as register:
            write_plugin.return_value = Path("/opencode/omni-mem.js")
            result = cli.install_startup_trigger("opencode")
        write_plugin.assert_called_once()
        register.assert_called_once()
        self.assertEqual(result, "")

    @mock.patch("omni_mem.cli.WRAPPER_DIR", Path("/wrapper"))
    def test_deepseek_path_installs_dsh_plugin_and_returns_profile(self):
        with mock.patch("omni_mem.cli.find_dsh_command", return_value="/bin/dsh"), \
                mock.patch("omni_mem.cli.choose_deepseek_profile", return_value="web"), \
                mock.patch("omni_mem.cli.install_dsh_plugin") as install, \
                mock.patch("omni_mem.cli.plugin_is_installed", return_value=True):
            install.return_value = Path("/home/.dsh/profiles/web")
            result = cli.install_startup_trigger("deepseek")
        install.assert_called_once_with("web", Path("/wrapper"), "/bin/dsh")
        self.assertEqual(result, "web")

    @mock.patch("omni_mem.cli.WRAPPER_DIR", Path("/wrapper"))
    def test_deepseek_path_raises_when_bundle_not_registered(self):
        with mock.patch("omni_mem.cli.find_dsh_command", return_value="/bin/dsh"), \
                mock.patch("omni_mem.cli.choose_deepseek_profile", return_value="web"), \
                mock.patch("omni_mem.cli.install_dsh_plugin"), \
                mock.patch("omni_mem.cli.plugin_is_installed", return_value=False):
            with self.assertRaises(RuntimeError):
                cli.install_startup_trigger("deepseek")


if __name__ == "__main__":
    unittest.main()
