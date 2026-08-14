"""DeepSeek Harness integration: discover profiles and mount the omni-mem plugin.

The "deepseek" install path makes DSH a full peer of the omni-mem sync by
installing the `@bleed00/dsh-omni-mem` bundle (the `dsh-plugin/` checkout next
to this package) into a DSH profile. The bundle pulls the data repository into
the claude-mem worker when a DSH session starts and pushes new memory back on
"put" events, mirroring the OpenCode startup plugin.

Only the *startup-pull trigger* differs between platforms here: the watcher
service and the git sync core are shared, because the watcher's push trigger
already reads claude-mem's own rows regardless of which coding tool writes them.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


PLUGIN_PACKAGE = "@bleed00/dsh-omni-mem"
DEFAULT_PROFILE = "web"


def dsh_home() -> Path:
    base = os.environ.get("DSH_HOME")
    return Path(base).expanduser() if base else Path.home() / ".dsh"


def dsh_profiles_dir() -> Path:
    return dsh_home() / "profiles"


def find_dsh_command() -> str | None:
    """Absolute path to `dsh` on PATH, if any."""
    return shutil.which("dsh")


def list_profiles() -> list[str]:
    """Profile names under the DSH home that look like real profiles."""
    base = dsh_profiles_dir()
    if not base.is_dir():
        return []
    names = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir() or entry.name == "node_modules":
            continue
        if (entry / "package.json").is_file():
            names.append(entry.name)
    return names


def plugin_source_dir(wrapper_dir: Path) -> Path:
    """Absolute path to the bundled DSH plugin checkout inside the wrapper."""
    return Path(wrapper_dir).expanduser().resolve() / "dsh-plugin"


def _profile_manifest(profile_dir: Path) -> dict:
    path = profile_dir / "package.json"
    if not path.exists():
        return {}
    try:
        with path.open() as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError):
        return {}


def profile_dir(profile: str) -> Path:
    return dsh_profiles_dir() / profile


def plugin_is_installed(profile: str) -> bool:
    manifest = _profile_manifest(profile_dir(profile))
    bundles = manifest.get("dsh", {}).get("profile", {}).get("bundles", [])
    return PLUGIN_PACKAGE in bundles


def _run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
    # `dsh plugin` forwards to pnpm. Because we capture output (no TTY), pnpm
    # aborts with ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY whenever it needs to
    # rebuild the profile's node_modules to add a plugin. Force a non-interactive
    # run so pnpm proceeds instead of asking for confirmation.
    env = dict(os.environ)
    env.setdefault("CI", "1")
    env.setdefault("npm_config_confirm_modules_purge", "false")
    result = subprocess.run(
        command, text=True, capture_output=True, creationflags=flags, env=env
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"{' '.join(command)} failed: {detail}")
    return result


def install_plugin(profile: str, wrapper_dir: Path, dsh: str) -> Path:
    """Mount the omni-mem bundle into the given DSH profile via `dsh plugin add`.

    Returns the profile directory. Raises RuntimeError on failure.
    """
    target = profile_dir(profile)
    if not (target / "package.json").is_file():
        raise RuntimeError(f"DSH profile not found: {target}")

    source = plugin_source_dir(wrapper_dir)
    if not (source / "package.json").is_file():
        raise RuntimeError(f"omni-mem DSH plugin checkout not found: {source}")

    _run([dsh, "plugin", "--profile", profile, "add", str(source)])

    if not plugin_is_installed(profile):
        raise RuntimeError(
            f"the plugin was added but the bundle is not listed in {target / 'package.json'}"
        )
    return target


def remove_plugin(profile: str, dsh: str) -> None:
    """Remove the omni-mem bundle from a DSH profile (no-op when absent)."""
    if not plugin_is_installed(profile):
        return
    try:
        _run([dsh, "plugin", "--profile", profile, "remove", PLUGIN_PACKAGE])
    except RuntimeError:
        # Best-effort: the profile may already be gone or dsh may be missing.
        pass


def status(profile: str) -> dict:
    target = profile_dir(profile)
    return {
        "profile_dir": str(target),
        "plugin": PLUGIN_PACKAGE,
        "installed": plugin_is_installed(profile),
    }
