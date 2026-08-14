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

    normalize_min_release_age_exclude(target)
    _run([dsh, "plugin", "--profile", profile, "add", str(source)])

    if not plugin_is_installed(profile):
        raise RuntimeError(
            f"the plugin was added but the bundle is not listed in {target / 'package.json'}"
        )
    return target


def _package_name_from_spec(spec: str) -> str:
    """Bare package name from a `name@version` spec (scoped names included)."""
    spec = spec.strip().strip("'\"")
    at_index = spec.find("@", 1) if spec.startswith("@") else spec.find("@")
    return spec[:at_index] if at_index > 0 else spec


def _quote_spec(spec: str, quote: str) -> str:
    return f"{quote}{spec}{quote}"


def normalize_min_release_age_exclude(profile_dir: Path) -> None:
    """Collapse duplicate per-package `minimumReleaseAgeExclude` entries.

    pnpm only honors the FIRST `minimumReleaseAgeExclude` rule matching a
    package name. When the strict-approval flow auto-collects two versions of
    the same package (e.g. `@bleed00/dsh-claude-mem@0.1.1` and `@0.1.5`) the
    older rule shadows the newer one, so lockfile supply-chain verification
    still rejects the current version and every `dsh plugin` pnpm run fails.
    Replacing all version-specific rules for a package with a single name-only
    rule keeps the approval intent (trust this package regardless of release
    age) while unblocking installs. No-op when the list is already consistent.
    """
    path = profile_dir / "pnpm-workspace.yaml"
    if not path.is_file():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    block_start = None
    items: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if block_start is None:
            if stripped == "minimumReleaseAgeExclude:":
                block_start = index
            continue
        if stripped.startswith("- "):
            items.append((index, stripped[2:].strip()))
            continue
        if stripped == "" or stripped.startswith("#"):
            continue
        break
    if block_start is None or not items:
        return

    version_specific_by_package: dict[str, set[str]] = {}
    for _, spec in items:
        name = _package_name_from_spec(spec)
        if not name:
            continue
        if spec == name:
            continue
        version_specific_by_package.setdefault(name, set()).add(spec)

    collapse = {name for name, specs in version_specific_by_package.items() if len(specs) > 1}
    if not collapse:
        return

    quote = "'"
    for _, spec in items:
        stripped = spec.strip()
        if stripped.startswith("'"):
            quote = "'"
            break
        if stripped.startswith('"'):
            quote = '"'
            break

    indent = lines[items[0][0]][: len(lines[items[0][0]]) - len(lines[items[0][0]].lstrip())]
    seen: set[str] = set()
    rewritten: list[str] = []
    for _, spec in items:
        name = _package_name_from_spec(spec)
        if not name or name in seen:
            continue
        seen.add(name)
        if name in collapse:
            rewritten.append(f"{indent}- {_quote_spec(name, quote)}")
        else:
            rewritten.append(f"{indent}- {spec}")

    last_item = max(index for index, _ in items)
    new_lines = lines[: block_start + 1] + rewritten + lines[last_item + 1 :]
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def remove_plugin(profile: str, dsh: str) -> None:
    """Remove the omni-mem bundle from a DSH profile (no-op when absent)."""
    if not plugin_is_installed(profile):
        return
    try:
        normalize_min_release_age_exclude(profile_dir(profile))
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
