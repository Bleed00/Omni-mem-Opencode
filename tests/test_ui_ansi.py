import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from anywhere_claude_mem import ui_ansi as ui
from anywhere_claude_mem import __version__


class AnsiOutputTests(unittest.TestCase):
    def _capture(self, func) -> str:
        buffer = io.StringIO()
        with patch("anywhere_claude_mem.ui_ansi._color_enabled", return_value=False), redirect_stdout(buffer):
            func()
        return buffer.getvalue()

    def test_banner_box(self):
        out = self._capture(ui.banner)
        self.assertIn(f"anywhere-claude-mem v{__version__}", out)
        self.assertIn("╭", out)
        self.assertIn("╮", out)
        self.assertIn("╰", out)
        self.assertIn("╯", out)

    def test_section(self):
        out = self._capture(lambda: ui.section("Checks"))
        self.assertIn("Checks", out)

    def test_ok(self):
        out = self._capture(lambda: ui.ok("git", "found"))
        self.assertIn("✓ git  found", out)

    def test_fail(self):
        out = self._capture(lambda: ui.fail("opencode", "not found"))
        self.assertIn("✗ opencode  not found", out)

    def test_warn(self):
        out = self._capture(lambda: ui.warn("gh", "optional"))
        self.assertIn("⚠ gh  optional", out)

    def test_error_box(self):
        out = self._capture(lambda: ui.error("boom"))
        self.assertIn("Error", out)
        self.assertIn("boom", out)

    def test_summary_box(self):
        out = self._capture(lambda: ui.summary("Done", [("worker", "active")]))
        self.assertIn("Done", out)
        self.assertIn("worker  active", out)

    def test_color_codes_when_enabled(self):
        buffer = io.StringIO()
        with patch("anywhere_claude_mem.ui_ansi._color_enabled", return_value=True), redirect_stdout(buffer):
            ui.ok("git", "found")
        out = buffer.getvalue()
        self.assertIn("\x1b[32m✓\x1b[0m", out)
        self.assertNotIn("[green]", out)

    def test_no_color_env_disables_ansi(self):
        with patch.dict("os.environ", {"NO_COLOR": "1"}), patch(
            "sys.stdout.isatty", return_value=True
        ):
            ui.reset_cache()
            self.assertFalse(ui._color_enabled())


class AnsiSpinnerTests(unittest.TestCase):
    def test_spinner_plain_runs_func(self):
        def _work():
            return 42

        with patch("anywhere_claude_mem.ui_ansi._color_enabled", return_value=False):
            self.assertEqual(ui.spinner("Working", _work), 42)

    def test_spinner_marks_success(self):
        buffer = io.StringIO()
        with patch("anywhere_claude_mem.ui_ansi._color_enabled", return_value=True), patch(
            "anywhere_claude_mem.ui_ansi._width", return_value=8
        ), redirect_stdout(buffer):
            self.assertEqual(ui.spinner("Working", lambda: "ok"), "ok")
        self.assertIn("\x1b[32m✓\x1b[0m Working", buffer.getvalue())


class AnsiPromptTests(unittest.TestCase):
    def test_ask_confirm_line_input(self):
        with patch("anywhere_claude_mem.ui_ansi._is_interactive", return_value=False), patch(
            "builtins.input", return_value="y"
        ):
            self.assertTrue(ui.ask_confirm("Enable?", False))

    def test_ask_confirm_interactive_key(self):
        with patch("anywhere_claude_mem.ui_ansi._is_interactive", return_value=True), patch(
            "anywhere_claude_mem.ui_ansi._read_key", return_value="n"
        ):
            self.assertFalse(ui.ask_confirm("Enable?", True))

    def test_ask_confirm_enter_uses_default(self):
        with patch("anywhere_claude_mem.ui_ansi._is_interactive", return_value=True), patch(
            "anywhere_claude_mem.ui_ansi._read_key", return_value="\n"
        ):
            self.assertTrue(ui.ask_confirm("Enable?", True))

    def test_ask_text_uses_default_when_empty(self):
        with patch("builtins.input", return_value=""):
            self.assertEqual(ui.ask_text("URL?", "https://x"), "https://x")

    def test_ask_text_validates(self):
        with patch("builtins.input", side_effect=["abc", "7"]):
            self.assertEqual(ui.ask_text("Count?", "", ui._positive_int), "7")

    def test_ask_int(self):
        with patch("builtins.input", return_value="7"):
            self.assertEqual(ui.ask_int("Count?", 1), 7)

    def test_ask_float(self):
        with patch("builtins.input", return_value="2.5"):
            self.assertEqual(ui.ask_float("Interval?", 5), 2.5)

    def test_ask_select_line_input_by_number(self):
        choices = ["Attach EXISTING", "Create NEW"]
        with patch("anywhere_claude_mem.ui_ansi._is_interactive", return_value=False), patch(
            "builtins.input", return_value="2"
        ):
            self.assertEqual(ui.ask_select("Setup?", choices, "Attach EXISTING"), "Create NEW")

    def test_ask_select_interactive_arrow_keys(self):
        choices = ["Attach EXISTING", "Create NEW"]
        with patch("anywhere_claude_mem.ui_ansi._is_interactive", return_value=True), patch(
            "anywhere_claude_mem.ui_ansi._read_key", side_effect=["down", "\n"]
        ):
            self.assertEqual(ui.ask_select("Setup?", choices, "Attach EXISTING"), "Create NEW")


class AnsiValidatorTests(unittest.TestCase):
    def test_positive_int(self):
        self.assertIs(ui._positive_int("5"), True)
        self.assertIsInstance(ui._positive_int("0"), str)
        self.assertIsInstance(ui._positive_int("abc"), str)

    def test_positive_float(self):
        self.assertIs(ui._positive_float("2.5"), True)
        self.assertIsInstance(ui._positive_float("-1"), str)
        self.assertIsInstance(ui._positive_float("x"), str)


if __name__ == "__main__":
    unittest.main()
