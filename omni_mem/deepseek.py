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


def _is_executable(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def _dsh_works(path: str) -> bool:
    """True when invoking `path --version` succeeds (exit 0).

    A ``dsh`` may exist as a file yet be broken — e.g. a launcher script whose
    hardcoded checkout directory does not exist on this machine. A real
    invocation is the only reliable proof that the candidate actually runs, so
    every candidate below is validated this way before being accepted. The
    probe is run with a short timeout so a hung tool cannot stall the install.
    """
    try:
        result = subprocess.run(
            [path, "--version"],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _npx_dsh_candidates() -> list[Path]:
    """`dsh` binaries from previous ``npx @deepseek-ai/dsh web`` runs.

    npx keeps each resolved package in ``~/.npm/_npx/<hash>/node_modules`` and
    does NOT place ``dsh`` onto any stable PATH. The ``.bin/dsh`` shim and the
    package's own ``lib/bin.js`` are both valid entry points, so both are
    collected. Newest cache entries are tried first.
    """
    root = Path.home() / ".npm" / "_npx"
    if not root.is_dir():
        return []
    candidates: list[Path] = []
    for entry in sorted(root.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        shim = entry / "node_modules" / ".bin" / "dsh"
        if shim.exists():
            candidates.append(shim)
        pkg_bin = entry / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
        if pkg_bin.exists():
            candidates.append(pkg_bin)
    return candidates


def _git_clone_dirs() -> list[Path]:
    """Common locations of a ``git clone`` of deepseek-harness.

    An arbitrary clone cannot be found by scanning the entire filesystem, so we
    probe the conventional spots plus the DSH-managed ``source/current``
    symlink. Anything outside these is covered by the ``OMNI_MEM_DSH_BIN``
    explicit override.
    """
    home = Path.home()
    dirs: list[Path] = []

    # Managed installer layout: ~/.dsh/source/current -> active checkout.
    managed = home / ".dsh" / "source" / "current"
    if managed.exists():
        dirs.append(managed)

    explicit = os.environ.get("OMNI_MEM_DSH_BIN")
    if explicit:
        p = Path(explicit).expanduser()
        dirs.append(p if p.is_dir() else p.parent)

    for name in (
        "deepseek-harness",
        "dsh",
        "deepseek",
    ):
        for base in (home, home / "src", home / "dev", home / "devel", home / "code",
                     home / "repos", home / "Scrivania"):
            dirs.append(base / name)

    return dirs


def _entry_points_in(checkout: Path) -> list[Path]:
    """Executable `dsh` entry points inside a checkout directory."""
    return [
        p for p in (
            checkout / "bin" / "dsh",
            checkout / "bin" / "dsh.exe",
            checkout / "apps" / "cli" / "lib" / "bin.js",
            checkout / "lib" / "bin.js",
        ) if _is_executable(p)
    ]


def find_dsh_command() -> str | None:
    """Locate a working ``dsh`` executable and put its directory on PATH.

    Discovery order:

    1. ``dsh`` already on the ambient PATH.
    2. ``OMNI_MEM_DSH_BIN`` override, then the npx cache
       (``~/.npm/_npx/*/node_modules/.bin/dsh`` and the package ``bin.js``).
    3. Conventional ``git clone`` directories and the DSH-managed
       ``~/.dsh/source/current`` symlink.
    4. ``~/.local/bin``, DSH profile ``node_modules/.bin``, and the npm global
       bin.

    Every candidate is verified by actually running ``<candidate> --version``;
    a stale launcher whose checkout is missing is rejected rather than trusted.
    On success the winning directory is prepended to ``os.environ["PATH"]`` so
    later subprocesses (``_run`` copies the environment) resolve ``dsh`` too.
    """
    # 1. Already on PATH — still verify it actually runs (it may be a stale
    #    launcher left over from a moved checkout).
    on_path = shutil.which("dsh")
    if on_path and _dsh_works(on_path):
        return on_path

    # 2. Build the ordered pool of candidates (directories and explicit files).
    candidate_dirs = _git_clone_dirs()
    candidate_dirs += [
        home_dir for home_dir in [
            Path.home() / ".local" / "bin",
        ]
    ]
    for profile_bin in _profile_bin_dirs():
        candidate_dirs.append(profile_bin)
    npm_global = _npm_global_bin()
    if npm_global:
        candidate_dirs.append(npm_global)

    checked: set[str] = set()
    for d in candidate_dirs:
        for entry in _files_to_try(d):
            key = str(entry)
            if key in checked:
                continue
            checked.add(key)
            if _is_executable(entry) and _dsh_works(str(entry)):
                if entry.name in ("dsh", "dsh.exe"):
                    _prepend_to_path(entry.parent)
                return str(entry)

    # 3. npx cache (bin shims live under a .bin, package bins are explicit files).
    for candidate in _npx_dsh_candidates():
        key = str(candidate)
        if key in checked:
            continue
        checked.add(key)
        if _is_executable(candidate) and _dsh_works(str(candidate)):
            if candidate.name in ("dsh", "dsh.exe"):
                _prepend_to_path(candidate.parent)
            return str(candidate)

    return None


def _files_to_try(d: Path) -> list[Path]:
    """Candidates to probe inside directory `d` (dir shim, then checkout)."""
    candidates: list[Path] = [d / "dsh", d / "dsh.exe"]
    for repo_candidate in _entry_points_in(d):
        candidates.append(repo_candidate)
    return candidates


def _profile_bin_dirs() -> list[Path]:
    """``node_modules/.bin`` dirs under every DSH profile."""
    out: list[Path] = []
    profiles = dsh_profiles_dir()
    if profiles.is_dir():
        for entry in profiles.iterdir():
            if entry.is_dir() and (entry / "package.json").is_file():
                out.append(entry / "node_modules" / ".bin")
    return out


def _npm_global_bin() -> Path | None:
    try:
        prefix = subprocess.run(
            ["npm", "prefix", "-g"],
            text=True,
            capture_output=True,
            check=False,
        ).stdout.strip()
    except (OSError, FileNotFoundError):
        return None
    if not prefix:
        return None
    p = Path(prefix)
    # npm/Windows keeps shims directly in the prefix; POSIX uses prefix/bin.
    return p if (p / "dsh").exists() or (p / "dsh.cmd").exists() else p / "bin"


def _prepend_to_path(d: Path) -> None:
    entries = os.environ.get("PATH", "").split(os.pathsep)
    entry = str(d)
    entries = [e for e in entries if e and e != entry]
    os.environ["PATH"] = os.pathsep.join([entry, *entries])


def resolve_dsh_in_folder(folder: str) -> str | None:
    """Find a working ``dsh`` entry point inside ``folder``, or None.

    Accepts either a checkout root (``deepseek-harness``), a directory that
    directly contains a ``dsh`` shim, or the path to a single executable. Every
    candidate is validated with a real ``--version`` run, so a copied, stale
    checkout that cannot execute is rejected.
    """
    p = Path(folder).expanduser()
    if p.is_file():
        candidates = [p]
    else:
        candidates = [
            p / "dsh",
            p / "dsh.exe",
            p / "bin" / "dsh",
            p / "bin" / "dsh.exe",
            p / "apps" / "cli" / "lib" / "bin.js",
            p / "lib" / "bin.js",
        ]
    for candidate in candidates:
        if _is_executable(candidate) and _dsh_works(str(candidate)):
            return str(candidate)
    return None


def put_dsh_on_path(dsh_path: str) -> None:
    """Prepend the directory containing ``dsh_path`` to ``os.environ["PATH"]``.

    Only meaningful when the entry point file itself is named ``dsh``/``dsh.exe``
    (so ``which dsh`` resolves to it); callers that found a ``bin.js`` style
    entry point invoke the returned absolute path directly instead.
    """
    p = Path(dsh_path)
    if p.name in ("dsh", "dsh.exe"):
        _prepend_to_path(p.parent)


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
