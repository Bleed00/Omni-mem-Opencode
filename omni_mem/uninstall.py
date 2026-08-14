"""Uninstall Omni-mem: service, launchers, startup trigger and config."""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from .config import config_dir, load_config
from .deepseek import find_dsh_command, remove_plugin as remove_dsh_plugin
from .service import remove as remove_service


def launchers() -> list[Path]:
    if sys.platform.startswith("win"):
        return []
    bin_dir = Path.home() / ".local" / "bin"
    return [bin_dir / name for name in ("omni-mem", "omni-push", "omni-pull")]


def remove_launchers() -> None:
    for path in launchers():
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)


def remove_opencode_plugin() -> None:
    plugin = Path.home() / ".config" / "opencode" / "plugins" / "omni-mem.js"
    plugin.unlink(missing_ok=True)

    config_path = Path.home() / ".config" / "opencode" / "opencode.json"
    if not config_path.exists():
        return
    with config_path.open() as stream:
        config = json.load(stream)
    plugins = config.get("plugin", [])
    if isinstance(plugins, str):
        plugins = [plugins]
    plugins = [entry for entry in plugins if entry != "./plugins/omni-mem.js"]
    if plugins:
        config["plugin"] = plugins
    else:
        config.pop("plugin", None)
    config_path.write_text(json.dumps(config, indent=2) + "\n")


def remove_config() -> None:
    shutil.rmtree(config_dir(), ignore_errors=True)


def uninstall(remove_data: bool = False, data_dir: Path | None = None) -> None:
    print("==> Stopping and removing automatic watcher service")
    remove_service()
    print("==> Removing launchers")
    remove_launchers()
    _remove_startup_trigger()
    print("==> Removing Omni-mem configuration")
    remove_config()
    if remove_data and data_dir is not None:
        print(f"==> Removing local data clone {data_dir}")
        shutil.rmtree(data_dir, ignore_errors=True)
    print("Omni-mem uninstalled.")


def _remove_startup_trigger() -> None:
    """Remove whichever startup-pull trigger this install registered.

    Uses the saved config to know which platform (and DSH profile) was chosen
    before the config file is deleted; falls back to both triggers so a partial
    or manual install still cleans up.
    """
    platform, dsh_profile = _saved_platform()
    if platform == "deepseek":
        print("==> Removing DeepSeek startup plugin")
        dsh = find_dsh_command()
        profile = dsh_profile or ""
        if dsh:
            if profile:
                remove_dsh_plugin(profile, dsh)
            else:
                print("==>   (no profile saved; run 'dsh plugin remove @bleed00/dsh-omni-mem')")
        else:
            print("==>   dsh not found; remove @bleed00/dsh-omni-mem from the profile manually")
        return
    print("==> Removing OpenCode startup plugin")
    remove_opencode_plugin()


def _saved_platform() -> tuple[str, str]:
    try:
        config = load_config()
        return config.platform, config.dsh_profile
    except Exception:
        return "", ""


def reinstall(install: Callable[[], int]) -> int:
    uninstall()
    return install()
