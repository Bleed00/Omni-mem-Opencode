"""Terminal UI for Anywhere-claude-mem.

On Windows the UI uses ``rich`` + ``questionary`` (installed by
``pip install -e .``). On Linux and other platforms it uses a zero-dependency
ANSI implementation, so the CLI runs without any pip package or virtual
environment.
"""

from __future__ import annotations

import sys

if sys.platform.startswith("win"):
    from .ui_rich import (  # noqa: F401
        ask_confirm,
        ask_float,
        ask_int,
        ask_select,
        ask_text,
        banner,
        error,
        fail,
        note,
        ok,
        reset_cache,
        section,
        spinner,
        summary,
        warn,
    )
else:
    from .ui_ansi import (  # noqa: F401
        ask_confirm,
        ask_float,
        ask_int,
        ask_select,
        ask_text,
        banner,
        error,
        fail,
        note,
        ok,
        reset_cache,
        section,
        spinner,
        summary,
        warn,
    )


if __name__ == "__main__":  # pragma: no cover
    banner()
    section("Checks")
    ok("git", "found")
    fail("opencode", "not found")
    warn("gh", "optional")
    summary("Done", [("worker", "active"), ("repo", "/tmp/data")])
