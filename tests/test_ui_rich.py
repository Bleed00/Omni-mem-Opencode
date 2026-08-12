import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from omni_mem import ui_rich as ui


class RichPlainOutputTests(unittest.TestCase):
    def _capture(self, func) -> str:
        buffer = io.StringIO()
        with patch("omni_mem.ui_rich._get_console", return_value=None), redirect_stdout(buffer):
            func()
        return buffer.getvalue()

    def test_banner_plain(self):
        self.assertIn("omni-mem v0.3.0", self._capture(ui.banner))

    def test_section_plain(self):
        self.assertIn("== Checks ==", self._capture(lambda: ui.section("Checks")))

    def test_ok_plain_strips_markup(self):
        out = self._capture(lambda: ui.ok("git", "found"))
        self.assertIn("✓ git  found", out)
        self.assertNotIn("[green]", out)

    def test_fail_plain_strips_markup(self):
        out = self._capture(lambda: ui.fail("opencode", "not found"))
        self.assertIn("✗ opencode  not found", out)
        self.assertNotIn("[red]", out)

    def test_warn_plain_strips_markup(self):
        out = self._capture(lambda: ui.warn("gh", "optional"))
        self.assertIn("⚠ gh  optional", out)
        self.assertNotIn("[yellow]", out)

    def test_summary_plain(self):
        out = self._capture(lambda: ui.summary("Done", [("worker", "active")]))
        self.assertIn("== Done ==", out)
        self.assertIn("worker: active", out)

    def test_error_plain(self):
        out = self._capture(lambda: ui.error("boom"))
        self.assertIn("ERROR: boom", out)


class RichFallbackPromptTests(unittest.TestCase):
    def test_fallback_confirm_yes(self):
        with patch("builtins.input", return_value="y"):
            self.assertTrue(ui._fallback_confirm("Enable?", False))

    def test_fallback_confirm_default_when_empty(self):
        with patch("builtins.input", return_value=""):
            self.assertTrue(ui._fallback_confirm("Enable?", True))
            self.assertFalse(ui._fallback_confirm("Enable?", False))

    def test_fallback_confirm_retries_until_valid(self):
        with patch("builtins.input", side_effect=["maybe", "n"]):
            self.assertFalse(ui._fallback_confirm("Enable?", True))

    def test_fallback_text_uses_default_when_empty(self):
        with patch("builtins.input", return_value=""):
            self.assertEqual(ui._fallback_text("URL?", "https://x", None), "https://x")

    def test_fallback_text_validates(self):
        with patch("builtins.input", side_effect=["abc", "7"]):
            self.assertEqual(ui._fallback_text("Count?", "", ui._positive_int), "7")

    def test_fallback_select_by_number(self):
        choices = ["Attach EXISTING", "Create NEW"]
        with patch("builtins.input", return_value="2"):
            self.assertEqual(ui._fallback_select("Setup?", choices, None), "Create NEW")

    def test_fallback_select_default_when_empty(self):
        choices = ["Attach EXISTING", "Create NEW"]
        with patch("builtins.input", return_value=""):
            self.assertEqual(
                ui._fallback_select("Setup?", choices, "Attach EXISTING"), "Attach EXISTING"
            )


class RichQuestionaryPathTests(unittest.TestCase):
    def test_ask_int_uses_questionary_with_validate(self):
        mock_q = MagicMock()
        with patch.dict(sys.modules, {"questionary": mock_q}):
            mock_q.text.return_value.ask.return_value = "42"
            self.assertEqual(ui.ask_int("Count?", 1), 42)
        call = mock_q.text.call_args
        self.assertEqual(call.kwargs["default"], "1")
        self.assertIsNotNone(call.kwargs["validate"])

    def test_ask_float_uses_questionary(self):
        mock_q = MagicMock()
        with patch.dict(sys.modules, {"questionary": mock_q}):
            mock_q.text.return_value.ask.return_value = "2.5"
            self.assertEqual(ui.ask_float("Interval?", 5), 2.5)

    def test_ask_confirm_uses_questionary(self):
        mock_q = MagicMock()
        with patch.dict(sys.modules, {"questionary": mock_q}):
            mock_q.confirm.return_value.ask.return_value = True
            self.assertTrue(ui.ask_confirm("Enable?", False))

    def test_ask_select_uses_questionary(self):
        mock_q = MagicMock()
        with patch.dict(sys.modules, {"questionary": mock_q}):
            mock_q.select.return_value.ask.return_value = "Create NEW"
            result = ui.ask_select("Setup?", ["Attach EXISTING", "Create NEW"], "Attach EXISTING")
        self.assertEqual(result, "Create NEW")

    def test_abort_raises_system_exit(self):
        mock_q = MagicMock()
        with patch.dict(sys.modules, {"questionary": mock_q}):
            mock_q.confirm.return_value.ask.return_value = None
            with self.assertRaises(SystemExit):
                ui.ask_confirm("Enable?")


class RichValidatorTests(unittest.TestCase):
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
