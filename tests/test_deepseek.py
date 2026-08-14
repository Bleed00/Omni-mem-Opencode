import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omni_mem import deepseek


class ProfileDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.profiles = self.home / "profiles"
        self.profiles.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _patch_home(self):
        return mock.patch("omni_mem.deepseek.dsh_home", return_value=self.home)

    def test_dsh_home_from_dsh_home_env(self):
        with mock.patch.dict("omni_mem.deepseek.os.environ", {"DSH_HOME": "/custom/dsh"}, clear=True):
            self.assertEqual(str(deepseek.dsh_home()), "/custom/dsh")

    def test_dsh_home_defaults_to_home_dot_dsh(self):
        with mock.patch.dict("omni_mem.deepseek.os.environ", {}, clear=True):
            with mock.patch("omni_mem.deepseek.Path.home", return_value=Path("/root")):
                self.assertEqual(str(deepseek.dsh_home()), "/root/.dsh")

    def test_list_profiles_skips_node_modules_and_non_profiles(self):
        with self._patch_home():
            (self.profiles / "web" / "package.json").parent.mkdir(parents=True, exist_ok=True)
            (self.profiles / "web" / "package.json").write_text("{}")
            (self.profiles / "empty").mkdir(parents=True, exist_ok=True)
            (self.profiles / "node_modules").mkdir(parents=True, exist_ok=True)
            names = deepseek.list_profiles()
        self.assertEqual(names, ["web"])

    def test_plugin_is_installed_checks_bundle_list(self):
        with self._patch_home():
            (self.profiles / "web" / "package.json").parent.mkdir(parents=True, exist_ok=True)
            manifest = {
                "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base", "@bleed00/dsh-omni-mem"]}}
            }
            (self.profiles / "web" / "package.json").write_text(json.dumps(manifest))
            self.assertTrue(deepseek.plugin_is_installed("web"))
            self.assertFalse(deepseek.plugin_is_installed("missing"))


class InstallRemoveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.home = self.root
        self.profiles = self.root / "profiles"
        (self.profiles / "web").mkdir(parents=True, exist_ok=True)
        (self.profiles / "web" / "package.json").write_text(
            json.dumps({"dsh": {"profile": {"bundles": []}}})
        )
        self.profile_dir = self.profiles / "web"
        self.wrapper = self.root / "wrapper"
        self.source = self.wrapper / "dsh-plugin"
        self.source.mkdir(parents=True)
        (self.source / "package.json").write_text("{}")

    def tearDown(self):
        self._tmp.cleanup()

    def _patch_home(self):
        return mock.patch("omni_mem.deepseek.dsh_home", return_value=self.home)

    def test_install_plugin_runs_dsh_add_and_marks_installed(self):
        with self._patch_home():
            new_manifest = {
                "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base", "@bleed00/dsh-omni-mem"]}}
            }
            self.profile_dir.joinpath("package.json").write_text(json.dumps(new_manifest))

            ran: list[list[str]] = []
            with mock.patch(
                "omni_mem.deepseek._run",
                side_effect=lambda command, check=True: ran.append(command) or _ok(),
            ):
                result = deepseek.install_plugin("web", self.wrapper, "/bin/dsh")

            self.assertEqual(result, self.profile_dir)
            self.assertIn("/bin/dsh", ran[0])
            self.assertIn("add", ran[0])
            self.assertIn(str(self.source), ran[0])
            self.assertTrue(deepseek.plugin_is_installed("web"))

    def test_install_plugin_raises_when_bundle_not_registered(self):
        with self._patch_home():
            with mock.patch("omni_mem.deepseek._run", return_value=_ok()):
                with self.assertRaises(RuntimeError):
                    deepseek.install_plugin("web", self.wrapper, "/bin/dsh")

    def test_install_plugin_raises_when_profile_missing(self):
        with self._patch_home():
            with mock.patch("omni_mem.deepseek._run") as run:
                with self.assertRaises(RuntimeError):
                    deepseek.install_plugin("nope", self.wrapper, "/bin/dsh")
            run.assert_not_called()

    def test_remove_plugin_is_noop_when_not_installed(self):
        with self._patch_home():
            with mock.patch("omni_mem.deepseek._run") as run:
                deepseek.remove_plugin("web", "/bin/dsh")
            run.assert_not_called()

    def test_remove_plugin_calls_dsh_remove(self):
        with self._patch_home():
            self.profile_dir.joinpath("package.json").write_text(
                json.dumps({"dsh": {"profile": {"bundles": ["@bleed00/dsh-omni-mem"]}}})
            )
            ran: list[list[str]] = []
            with mock.patch(
                "omni_mem.deepseek._run",
                side_effect=lambda command, check=True: ran.append(command) or _ok(),
            ):
                deepseek.remove_plugin("web", "/bin/dsh")
            self.assertIn("remove", ran[0])
            self.assertIn("@bleed00/dsh-omni-mem", ran[0])


def _ok():
    class Result:
        returncode = 0
        stdout = ""
        stderr = ""
    return Result()


if __name__ == "__main__":
    unittest.main()
