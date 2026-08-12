"""Command-line interface for Omni-mem."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .config import (
    AutoSyncConfig,
    Config,
    StartupPullConfig,
    config_path,
    load_config,
    save_config,
)
from .git import GitError, clone
from .service import install as install_service
from .service import remove as remove_service
from .service import status as service_status
from .sync import SyncEngine, status as sync_status
from .ui import (
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
from .uninstall import reinstall as reinstall_omni_mem
from .uninstall import uninstall as uninstall_omni_mem
from .watcher import watch
from .worker import WorkerClient


WRAPPER_DIR = Path(__file__).resolve().parent.parent
BIN_DIR = Path.home() / ".local" / "bin"


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def creationflags() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0


def run_command(command: list[str], check: bool = True) -> str:
    result = subprocess.run(command, text=True, capture_output=True, creationflags=creationflags())
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"{' '.join(command)} failed: {detail}")
    return result.stdout.strip()


def run_interactive(command: list[str]) -> None:
    """Run a command with terminal prompts/consent visible (winget, gh auth login)."""
    subprocess.run(command, check=False)


def normalize_remote(url: str) -> str:
    return url.rstrip("/").removesuffix(".git")


def ensure_bootstrap() -> None:
    """Install the editable package when UI dependencies (or the Windows launcher) are missing."""
    try:
        import rich  # noqa: F401
        import questionary  # noqa: F401
    except ImportError:
        missing = True
    else:
        missing = sys.platform.startswith("win") and not command_exists("omni-mem")

    if not missing:
        return

    if sys.platform.startswith("win") and not command_exists("omni-mem"):
        note("Installing the omni-mem commands...")
    else:
        note("Installing Omni-mem UI dependencies...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", str(WRAPPER_DIR)],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        warn("could not install UI dependencies; continuing in plain mode", detail)
        note(
            "To enable the full UI, install the package in a virtual environment "
            "(e.g. 'python -m venv .venv && .venv/bin/pip install -e .') and re-run."
        )
        return
    reset_cache()
    if sys.platform.startswith("win") and not command_exists("omni-mem"):
        raise RuntimeError(
            "pip install succeeded but omni-mem was not found; restart the terminal and re-run"
        )


def verify_prerequisites() -> tuple[str, bool]:
    if sys.platform.startswith("linux"):
        python_cmd = "python3"
    elif sys.platform.startswith("win"):
        python_cmd = "python"
    else:
        raise RuntimeError("unsupported platform")

    for command in ("git", python_cmd, "curl"):
        if not command_exists(command):
            fail(command, "not found")
            raise RuntimeError(f"required command not found: {command}")
        ok(command, "found")

    username = ""
    gh_ok = False
    if command_exists("gh"):
        gh_ok = True
        try:
            username = run_command(["gh", "api", "user", "-q", ".login"])
            ok("gh", f"authenticated ({username})")
        except RuntimeError as exc:
            fail("gh", "not authenticated")
            raise RuntimeError("gh is not authenticated; run 'gh auth login'") from exc
    else:
        warn("gh", "not found")
        if ask_confirm("Install gh now and start the login flow?"):
            install_gh()
            username = run_command([find_gh(), "api", "user", "-q", ".login"])
            gh_ok = True
            ok("gh", f"authenticated ({username})")
        else:
            note("Continuing without gh: only attaching an EXISTING data repo is available.")

    if not command_exists("opencode") and not (
        (Path.home() / ".config" / "opencode").is_dir()
        or (Path.home() / ".opencode").is_dir()
    ):
        fail("opencode", "not found")
        raise RuntimeError("opencode was not found")
    ok("opencode", "found")

    plugin = Path.home() / ".config" / "opencode" / "plugins" / "claude-mem.js"
    if not plugin.is_file():
        fail("claude-mem plugin", "not found")
        raise RuntimeError(f"claude-mem opencode plugin was not found: {plugin}")
    ok("claude-mem", "plugin found")

    try:
        worker = WorkerClient()
        spinner("Contacting claude-mem worker", worker.check)
        ok("claude-mem", f"worker running ({worker.base_url}/api/health)")
    except Exception as exc:
        fail("claude-mem", "worker unreachable")
        raise RuntimeError("claude-mem worker is unreachable; start it before installing") from exc
    return username, gh_ok


def install_gh() -> None:
    if sys.platform.startswith("win"):
        note("Installing gh with winget...")
        run_interactive(
            [
                "winget",
                "install",
                "--id",
                "GitHub.cli",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ]
        )
        gh_bin = find_gh()
        note("Starting gh authentication...")
        run_interactive([gh_bin, "auth", "login"])
        return
    raise RuntimeError(
        "Install gh with the package manager of your distribution, then re-run 'omni-mem install'."
    )


def find_gh() -> str:
    """Locate gh after a winget install (PATH is only refreshed in new processes)."""
    found = shutil.which("gh")
    if found:
        return found
    for base_name in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(base_name)
        if not base:
            continue
        candidate = Path(base) / "GitHub CLI" / "gh.exe"
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError(
        "gh was installed but could not be located; restart the terminal and re-run 'omni-mem install'"
    )


def create_or_select_data_repo(
    username: str, destination: Path, gh_ok: bool = True
) -> tuple[str, bool]:
    if gh_ok:
        mode = ask_select(
            "How do you want to set up the data repository?",
            ["Attach an EXISTING repository", "Create a NEW private repository"],
            default="Attach an EXISTING repository",
        )
        new_repo = "NEW" in mode.upper()
    else:
        note("gh is unavailable; attaching an existing data repository only.")
        new_repo = False

    if new_repo:
        name = ask_text("Name of the new private data repo")
        spinner(
            "Creating data repository",
            run_command,
            [
                "gh",
                "repo",
                "create",
                f"{username}/{name}",
                "--private",
                "--description",
                "Memory data for Omni-mem-Opencode",
            ],
        )
        url = f"https://github.com/{username}/{name}.git"
    else:
        url = ask_text("URL of the existing data repo")
        spinner("Verifying data repository", run_command, ["git", "ls-remote", url])

    if destination.exists():
        if (destination / ".git").is_dir():
            current = run_command(["git", "-C", str(destination), "remote", "get-url", "origin"])
            if normalize_remote(current) != normalize_remote(url):
                raise RuntimeError(
                    f"data directory already points to {current}, not the selected repo {url}"
                )
            spinner(
                "Refreshing local data repository",
                run_command,
                ["git", "-C", str(destination), "pull", "--rebase", "--quiet"],
                check=False,
            )
        elif any(destination.iterdir()):
            raise RuntimeError(f"data directory is not empty: {destination}")
    else:
        spinner("Cloning data repository", clone, url, destination)
    ok("data repository", str(destination))
    return url, new_repo


def write_launcher() -> Path | None:
    if sys.platform.startswith("win"):
        return None
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    launcher = BIN_DIR / "omni-mem"
    content = (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.path.insert(0, {str(WRAPPER_DIR)!r})\n"
        "from omni_mem.cli import main\n"
        "raise SystemExit(main())\n"
    )
    launcher.write_text(content)
    launcher.chmod(0o755)
    for alias in ("omni-push", "omni-pull"):
        alias_path = BIN_DIR / alias
        alias_path.unlink(missing_ok=True)
        alias_path.symlink_to(launcher)
    return launcher


def launcher_command() -> str:
    """Absolute path to the omni-mem executable for the OpenCode startup plugin."""
    if sys.platform.startswith("win"):
        resolved = shutil.which("omni-mem")
        if not resolved:
            raise RuntimeError("omni-mem command not found; run 'pip install -e .' first")
        return str(Path(resolved))
    return str(BIN_DIR / "omni-mem")


def write_opencode_startup_plugin() -> Path:
    plugin_dir = Path.home() / ".config" / "opencode" / "plugins"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    plugin = plugin_dir / "omni-mem.js"
    command_js = json.dumps(launcher_command())
    spawn_opts = "{\n    detached: true,\n    stdio: \"ignore\",\n    windowsHide: true,\n  }"
    plugin.write_text(
        "import { spawn } from \"node:child_process\";\n\n"
        "let started = false;\n\n"
        "export default async function OmniMemStartup() {\n"
        "  if (started) return {};\n"
        "  started = true;\n"
        f"  const command = {command_js};\n"
        f"  const child = spawn(command, [\"startup-pull\"], {spawn_opts});\n"
        "  child.on(\"error\", () => {});\n"
        "  child.unref();\n"
        "  return {};\n"
        "}\n"
    )
    return plugin


def register_opencode_plugin() -> None:
    config_path_ = Path.home() / ".config" / "opencode" / "opencode.json"
    if not config_path_.exists():
        return
    with config_path_.open() as stream:
        config = json.load(stream)
    plugins = config.get("plugin", [])
    if isinstance(plugins, str):
        plugins = [plugins]
    if "./plugins/omni-mem.js" not in plugins:
        plugins.append("./plugins/omni-mem.js")
    config["plugin"] = plugins
    config_path_.write_text(json.dumps(config, indent=2) + "\n")


def install() -> int:
    banner()
    ensure_bootstrap()
    section("Checking prerequisites")
    username, gh_ok = verify_prerequisites()
    if username:
        ok("prerequisites", f"ready as {username}")
    else:
        ok("prerequisites", "ready")

    data_dir = WRAPPER_DIR / "data"
    url, _ = create_or_select_data_repo(username, data_dir, gh_ok)

    section("Synchronization settings")
    enabled = ask_confirm("Enable automatic synchronization?")
    auto = AutoSyncConfig(enabled=enabled)
    if enabled:
        auto.observations_per_push = ask_int("Push after how many new observations?", 1)
        auto.poll_interval_seconds = ask_float("Polling interval in seconds", 5)
        auto.debounce_seconds = ask_float("Push debounce in seconds", 10)

    startup_enabled = ask_confirm("Pull memory automatically when OpenCode starts?")
    startup = StartupPullConfig(enabled=startup_enabled)
    if startup_enabled:
        startup.retry_attempts = ask_int("Startup pull retry attempts", 12)
        startup.retry_delay_seconds = ask_float("Startup pull retry delay in seconds", 5)

    section("Installing")
    config = Config(str(WRAPPER_DIR), str(data_dir), url, auto, startup)
    save_config(config)
    ok("configuration", str(config_path()))

    write_launcher()
    ok("commands", "omni-mem, omni-push, omni-pull")

    plugin = write_opencode_startup_plugin()
    ok("OpenCode startup plugin", str(plugin))
    register_opencode_plugin()

    if enabled:
        launcher = launcher_path()
        spinner("Installing automatic watcher service", install_service, config, launcher)
        ok("automatic watcher", service_status())
    else:
        remove_service()
        ok("automatic watcher", "disabled")

    summary(
        "Installation complete",
        [
            ("data repository", url),
            ("automatic watcher", "active" if enabled else "disabled"),
            ("startup pull", "enabled" if startup_enabled else "disabled"),
            ("commands", "omni-mem push | omni-mem pull"),
        ],
    )
    return 0


def print_status() -> int:
    config = load_config()
    data = sync_status(config)
    data["service"] = service_status()
    auto = data["auto_sync"]
    summary(
        "omni-mem status",
        [
            ("claude-mem worker", "running" if data["worker"] else "stopped"),
            ("data repository", "present" if data["data_repo"] else "missing"),
            ("data repo url", data["data_repo_url"] or "(none)"),
            (
                "auto-sync",
                "enabled"
                if auto["enabled"]
                else "disabled",
            ),
            (
                "auto-sync settings",
                f"{auto['observations_per_push']} obs / push, "
                f"poll {auto['poll_interval_seconds']}s, debounce {auto['debounce_seconds']}s",
            ),
            ("watcher service", data["service"]),
            ("state file", data["state_file"]),
        ],
    )
    return 0


def startup_pull() -> int:
    config = load_config()
    if not config.startup_pull.enabled:
        return 0
    last_error: Exception | None = None
    for attempt in range(1, config.startup_pull.retry_attempts + 1):
        try:
            result = SyncEngine(config).pull()
            print(json.dumps(result, indent=2))
            return 0
        except Exception as exc:
            last_error = exc
            if attempt < config.startup_pull.retry_attempts:
                time.sleep(config.startup_pull.retry_delay_seconds)
    print(f"ERROR: startup pull failed after retries: {last_error}", file=sys.stderr)
    return 1


def launcher_path() -> Path | None:
    if sys.platform.startswith("win"):
        found = shutil.which("omni-mem")
        return Path(found) if found else None
    return BIN_DIR / "omni-mem"


def _result_items(result) -> list[tuple[str, str]]:
    if not isinstance(result, dict):
        return [("result", str(result))]
    return [(str(key), str(value)) for key, value in result.items()]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    program = Path(sys.argv[0]).stem
    if not argv and program in {"omni-push", "omni-pull"}:
        argv = [program.removeprefix("omni-")]

    parser = argparse.ArgumentParser(prog="omni-mem")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("install")
    sub.add_parser("push")
    sub.add_parser("pull")
    watch_parser = sub.add_parser("watch")
    watch_parser.add_argument("--log", default=None, help="append watch output to this file")
    sub.add_parser("startup-pull")
    sub.add_parser("status")
    sub.add_parser("uninstall")
    sub.add_parser("reinstall")
    service = sub.add_parser("service")
    service.add_argument("action", choices=("install", "remove", "status"))
    args = parser.parse_args(argv)

    try:
        if args.command == "install":
            return install()
        if args.command == "uninstall":
            return uninstall_omni_mem(remove_data=True, data_dir=WRAPPER_DIR / "data")
        if args.command == "reinstall":
            return reinstall_omni_mem(install)
        if args.command != "watch":
            ensure_bootstrap()
        config = load_config()
        if args.command == "push":
            engine = SyncEngine(config)
            result = spinner("Pushing memory to data repository", engine.push)
            summary("Push complete", _result_items(result))
        elif args.command == "pull":
            engine = SyncEngine(config)
            result = spinner("Pulling memory from data repository", engine.pull)
            summary("Pull complete", _result_items(result))
        elif args.command == "watch":
            watch(config, args.log)
        elif args.command == "startup-pull":
            return startup_pull()
        elif args.command == "status":
            return print_status()
        elif args.command == "service":
            launcher = launcher_path()
            if args.action == "install":
                install_service(config, launcher)
                ok("watcher service", service_status())
            elif args.action == "remove":
                remove_service()
                ok("watcher service", "removed")
            else:
                print(service_status())
        return 0
    except (RuntimeError, GitError, OSError, ValueError) as exc:
        error(str(exc))
        return 1
    except KeyboardInterrupt:
        error("interrupted")
        return 1
