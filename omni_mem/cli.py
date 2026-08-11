"""Command-line interface for Omni-mem."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .config import AutoSyncConfig, Config, StartupPullConfig, load_config, save_config
from .git import GitError, clone
from .service import install as install_service
from .service import remove as remove_service
from .service import status as service_status
from .sync import SyncEngine, status as sync_status
from .uninstall import reinstall as reinstall_omni_mem
from .uninstall import uninstall as uninstall_omni_mem
from .watcher import watch
from .worker import WorkerClient


WRAPPER_DIR = Path(__file__).resolve().parent.parent
BIN_DIR = Path.home() / ".local" / "bin"


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def run_command(command: list[str], check: bool = True) -> str:
    result = subprocess.run(command, text=True, capture_output=True)
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"{' '.join(command)} failed: {detail}")
    return result.stdout.strip()


def normalize_remote(url: str) -> str:
    return url.rstrip("/").removesuffix(".git")


def verify_prerequisites() -> str:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("this version currently supports Linux only")
    for command in ("git", "python3", "curl", "gh"):
        if not command_exists(command):
            raise RuntimeError(f"required command not found: {command}")
    # gh auth status writes useful information to stderr, so verify with the
    # authenticated API instead of relying on its output.
    try:
        username = run_command(["gh", "api", "user", "-q", ".login"])
    except RuntimeError as exc:
        raise RuntimeError("gh is not authenticated; run 'gh auth login'") from exc
    if not command_exists("opencode") and not (
        (Path.home() / ".config" / "opencode").is_dir()
        or (Path.home() / ".opencode").is_dir()
    ):
        raise RuntimeError("opencode was not found")
    plugin = Path.home() / ".config" / "opencode" / "plugins" / "claude-mem.js"
    if not plugin.is_file():
        raise RuntimeError(f"claude-mem opencode plugin was not found: {plugin}")
    try:
        WorkerClient().check()
    except Exception as exc:
        raise RuntimeError("claude-mem worker is unreachable; start it before installing") from exc
    return username


def ask_nonempty(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("Please enter a value.")


def ask_positive_int(prompt: str, default: int) -> int:
    while True:
        value = input(prompt).strip() or str(default)
        try:
            parsed = int(value)
            if parsed > 0:
                return parsed
        except ValueError:
            pass
        print("Please enter a positive integer.")


def ask_positive_float(prompt: str, default: float) -> float:
    while True:
        value = input(prompt).strip() or str(default)
        try:
            parsed = float(value)
            if parsed > 0:
                return parsed
        except ValueError:
            pass
        print("Please enter a positive number.")


def ask_yes_no(prompt: str) -> bool:
    while True:
        value = input(prompt).strip().lower()
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer y or n.")


def create_or_select_data_repo(username: str, destination: Path) -> tuple[str, bool]:
    choice = ask_nonempty("Create a NEW data repo or attach an EXISTING one? [new/existing] ").lower()
    while choice not in {"new", "n", "existing", "e"}:
        print("Please answer new or existing.")
        choice = ask_nonempty("Create a NEW data repo or attach an EXISTING one? [new/existing] ").lower()

    if choice in {"new", "n"}:
        name = ask_nonempty("Name of the new private data repo: ")
        run_command(
            [
                "gh",
                "repo",
                "create",
                f"{username}/{name}",
                "--private",
                "--description",
                "Memory data for Omni-mem-Opencode",
            ]
        )
        url = f"https://github.com/{username}/{name}.git"
        new_repo = True
    else:
        url = ask_nonempty("URL of the existing data repo: ")
        run_command(["git", "ls-remote", url])
        new_repo = False

    if destination.exists():
        if (destination / ".git").is_dir():
            current = run_command(["git", "-C", str(destination), "remote", "get-url", "origin"])
            if normalize_remote(current) != normalize_remote(url):
                raise RuntimeError(
                    f"data directory already points to {current}, not the selected repo {url}"
                )
            run_command(["git", "-C", str(destination), "pull", "--rebase", "--quiet"], check=False)
        elif any(destination.iterdir()):
            raise RuntimeError(f"data directory is not empty: {destination}")
    else:
        clone(url, destination)
    return url, new_repo


def write_launcher() -> Path:
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


def write_opencode_startup_plugin() -> Path:
    plugin_dir = Path.home() / ".config" / "opencode" / "plugins"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    plugin = plugin_dir / "omni-mem.js"
    plugin.write_text(
        "import os from \"node:os\";\n"
        "import { spawn } from \"node:child_process\";\n\n"
        "let started = false;\n\n"
        "export default async function OmniMemStartup() {\n"
        "  if (started) return {};\n"
        "  started = true;\n"
        "  const command = `${os.homedir()}/.local/bin/omni-mem`;\n"
        "  const child = spawn(command, [\"startup-pull\"], {\n"
        "    detached: true,\n"
        "    stdio: \"ignore\",\n"
        "  });\n"
        "  child.on(\"error\", () => {});\n"
        "  child.unref();\n"
        "  return {};\n"
        "}\n"
    )
    return plugin


def register_opencode_plugin() -> None:
    config_path = Path.home() / ".config" / "opencode" / "opencode.json"
    if not config_path.exists():
        return
    with config_path.open() as stream:
        config = json.load(stream)
    plugins = config.get("plugin", [])
    if isinstance(plugins, str):
        plugins = [plugins]
    if "./plugins/omni-mem.js" not in plugins:
        plugins.append("./plugins/omni-mem.js")
    config["plugin"] = plugins
    config_path.write_text(json.dumps(config, indent=2) + "\n")


def install() -> int:
    print("==> Omni-mem Linux installer")
    username = verify_prerequisites()
    print(f"Prerequisites OK ({username})")
    data_dir = WRAPPER_DIR / "data"
    url, _ = create_or_select_data_repo(username, data_dir)

    enabled = ask_yes_no("Enable automatic synchronization? [y/n] ")
    auto = AutoSyncConfig(enabled=enabled)
    if enabled:
        auto.observations_per_push = ask_positive_int(
            "Push after how many new observations? [1]: ", 1
        )
        auto.poll_interval_seconds = ask_positive_float("Polling interval in seconds [5]: ", 5)
        auto.debounce_seconds = ask_positive_float("Push debounce in seconds [10]: ", 10)

    startup_enabled = ask_yes_no("Pull memory automatically when OpenCode starts? [y/n] ")
    startup = StartupPullConfig(enabled=startup_enabled)
    if startup_enabled:
        startup.retry_attempts = ask_positive_int("Startup pull retry attempts [12]: ", 12)
        startup.retry_delay_seconds = ask_positive_float(
            "Startup pull retry delay in seconds [5]: ", 5
        )

    config = Config(str(WRAPPER_DIR), str(data_dir), url, auto, startup)
    save_config(config)
    launcher = write_launcher()
    write_opencode_startup_plugin()
    register_opencode_plugin()
    if enabled:
        install_service(config, launcher)
    else:
        remove_service()
    print("Installation complete.")
    print(f"Data repository: {data_dir}")
    print("Commands: omni-mem push, omni-mem pull, omni-push, omni-pull")
    if enabled:
        print("Automatic watcher: active")
    return 0


def print_status() -> int:
    config = load_config()
    print(json.dumps({**sync_status(config), "service": service_status()}, indent=2))
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


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    program = Path(sys.argv[0]).name
    if not argv and program in {"omni-push", "omni-pull"}:
        argv = [program.removeprefix("omni-")]

    parser = argparse.ArgumentParser(prog="omni-mem")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("install")
    sub.add_parser("push")
    sub.add_parser("pull")
    sub.add_parser("watch")
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
        config = load_config()
        if args.command == "push":
            print(SyncEngine(config).push())
        elif args.command == "pull":
            print(json.dumps(SyncEngine(config).pull(), indent=2))
        elif args.command == "watch":
            watch(config)
        elif args.command == "startup-pull":
            return startup_pull()
        elif args.command == "status":
            return print_status()
        elif args.command == "service":
            launcher = BIN_DIR / "omni-mem"
            if args.action == "install":
                install_service(config, launcher)
            elif args.action == "remove":
                remove_service()
            else:
                print(service_status())
        return 0
    except (RuntimeError, GitError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
