# Omni-mem-Opencode

Linux-first, two-way synchronization of **claude-mem** memory across multiple
OpenCode installations.

The project is split into two repositories:

- **Wrapper repository**: code, installer, and documentation.
- **Data repository**: private Git repository containing exported memory data.

The local clone of the data repository is stored in `data/` inside the wrapper.
The wrapper ignores that directory, so personal memory never enters the wrapper
repository.

```text
OpenCode -> claude-mem worker -> Omni-mem Python CLI -> private data repository
```

## Current platform support

The implementation targets **Linux with systemd user services** and **Windows
with Task Scheduler**. The sync core is pure Python and shared between the two
platforms; only the service integration, configuration paths, launchers, and
process handling differ.

## Prerequisites

Install these components before running Omni-mem:

- OpenCode
- claude-mem configured as an OpenCode plugin
- A running claude-mem worker
- Python 3.10 or newer
- Git
- GitHub CLI (`gh`); optional, required only to *create* a new data repository
- `curl`
- A private GitHub data repository, or permission to create one

## Configure GitHub CLI

Omni-mem uses `gh` to create a private data repository. Install it using the
method for your distribution:

```bash
# Arch / CachyOS
sudo pacman -S github-cli

# Debian / Ubuntu
sudo apt install gh

# Fedora
sudo dnf install gh
```

On Windows, `gh` is optional: `omni-mem install` offers to install it with
`winget install GitHub.cli` and start `gh auth login`. If you decline, you can
only attach an existing data repository. Install it manually if preferred:

```powershell
winget install GitHub.cli
gh auth login
```

Official documentation: <https://cli.github.com>

Authenticate the CLI:

```bash
gh auth login
```

Choose:

1. `GitHub.com`
2. `HTTPS`
3. Browser authentication

Verify the account:

```bash
```

Optional: allow deletion of temporary repositories:

```bash
```

The delete permission is not required for normal Omni-mem operation.

## Install OpenCode and claude-mem

Install OpenCode according to its official documentation, then verify it:

```bash
opencode --version
```

Install claude-mem for OpenCode:

```bash
npx -y @thedotmack/claude-mem install --ide opencode
```

Configure the claude-mem worker. This example uses OpenRouter:

```json
{
  "CLAUDE_MEM_RUNTIME": "worker",
  "CLAUDE_MEM_PROVIDER": "openrouter",
  "CLAUDE_MEM_OPENROUTER_MODEL": "poolside/laguna-xs-2.1:free",
  "CLAUDE_MEM_OPENROUTER_API_KEY": "YOUR_API_KEY"
}
```

Save it as `~/.claude-mem/settings.json`, then protect it:

```bash
chmod 600 ~/.claude-mem/settings.json
npx claude-mem start
npx claude-mem status
```

## Install Omni-mem

Clone the wrapper:

```bash
cd Omni-mem-Opencode
```

Run the Python installer:

```bash
python3 -m omni_mem install
```

The installer:

1. Verifies Git, Python, curl, GitHub CLI, OpenCode, claude-mem, and the worker.
2. Asks whether to create a new private data repository or attach an existing
   one.
3. Clones the data repository into `data/`.
4. Asks whether automatic synchronization should be enabled.
5. If enabled, asks how many new observations should trigger a push, the poll
   interval, and the debounce interval.
6. Installs `omni-mem`, `omni-push`, and `omni-pull` in `~/.local/bin`.
7. Installs and starts a Linux `systemd --user` watcher when automatic sync is
   enabled.
8. Installs an OpenCode startup plugin that runs `omni-mem startup-pull` when
   OpenCode starts, if startup pull is enabled.

## Install Omni-mem on Windows

The wrapper is installed as an editable package so `pip` generates the
`omni-mem`, `omni-push`, and `omni-pull` console commands:

```powershell
# from the wrapper directory
pip install -e .
python -m omni_mem install
```

The installer:

1. Verifies Git, Python, curl, OpenCode, claude-mem, and the worker; offers to
   install `gh` (optional).
2. Attaches an existing private data repository, or creates a new one when `gh`
   is available.
3. Clones the data repository into `data/`.
4. Asks whether automatic synchronization should be enabled.
5. If enabled, registers a Task Scheduler task (`omni-mem-watch`) that runs the
   watcher hidden at logon via `pythonw.exe`, with automatic restart on crash.
   Its output is appended to `%APPDATA%\omni-mem\watch.log`.
6. Installs an OpenCode startup plugin that runs `omni-mem startup-pull` when
   OpenCode starts, if startup pull is enabled.

Windows notes:

- The claude-mem worker port is discovered from `~/.claude-mem/worker.pid`
  (or `supervisor.json`), not computed from the user id, because Windows has no
  uid. A health-endpoint probe over `37700`–`37799` is the last-resort fallback.
- `ExecutionPolicy` blocks `npm.ps1`/`npx.ps1`; the tool only invokes `.exe`
  commands (`git`, `curl`, `gh`, `powershell`), so it is unaffected.
- Configuration lives in `%APPDATA%\omni-mem\`, not `~/.config/omni-mem`.

## Manual synchronization

Export the local memory to the private data repository:

```bash
omni-mem push
omni-push
```

Import the data repository into the local worker:

```bash
omni-mem pull
omni-pull
```

Both operations are idempotent. Re-running a pull does not create duplicate
records.

## Automatic synchronization

During installation, enable automatic synchronization and configure:

- observations per push, for example `1`, `10`, or `30`;
- polling interval in seconds;
- debounce interval in seconds.

The watcher starts from a baseline of the observations already present. This
prevents installation from unexpectedly pushing the existing database. Run the
first full export explicitly:

```bash
omni-mem push
```

After that, the watcher pushes when the configured number of new observations
is reached. A failed push is retried during the next polling cycle.

The installer also asks whether to pull the data repository whenever OpenCode
starts. This is implemented as a separate OpenCode plugin and includes retries
while the claude-mem worker is still starting. It does not modify the
claude-mem plugin.

Useful commands:

```bash
omni-mem status
omni-mem watch
omni-mem service status
omni-mem service remove
systemctl --user status omni-mem-watch.service
journalctl --user -u omni-mem-watch.service -f
```

The startup pull can also be tested manually:

```bash
omni-mem startup-pull
```

## Data model and merge safety

The data repository contains:

```text
sessions.json
observations.json
summaries.json
prompts.json
```

Records are merged using stable cross-device keys rather than local SQLite
numeric IDs:

- sessions: platform plus content session ID;
- observations: memory session, title, and creation timestamp;
- summaries: memory session ID;
- prompts: platform, content session ID, and prompt number.

The first push exports the complete local knowledge base. Later pushes preserve
the complete accumulated data while Git stores only the differences in each
commit.

## Configuration

The local Omni-mem configuration is stored at:

```text
~/.config/omni-mem/config.json        # Linux
%APPDATA%\omni-mem\config.json        # Windows
```

It contains local paths, the data repository URL, and automatic-sync settings.
It does not contain API keys.

Watcher state is stored separately in:

```text
~/.config/omni-mem/watch-state.json   # Linux
%APPDATA%\omni-mem\watch-state.json   # Windows
```

## Security

- Keep the data repository private. It contains prompts, observations, and
  summaries from your sessions.
- Never commit `~/.claude-mem/settings.json` or API keys.
- Use `chmod 600 ~/.claude-mem/settings.json`.
- The wrapper repository is safe to publish only after its Git history has been
  audited and no personal data has ever been committed.

## Development

Run the CLI directly from the wrapper:

```bash
python3 -m omni_mem --help
python3 -m py_compile omni_mem/*.py
```

The runtime uses only the Python standard library and the system `git` and
`gh` commands.

## Platform-specific pieces

The sync core (`data.py`, `sync.py`, `git.py`, `watcher.py`, the worker HTTP
client) is platform-independent. Only these pieces differ per OS:

- `service.py` dispatches to `service_linux.py` (systemd user services) or
  `service_windows.py` (Task Scheduler via PowerShell).
- `config.py` resolves `~/.config/omni-mem` on POSIX and `%APPDATA%\omni-mem` on
  Windows, and skips `chmod` on Windows.
- `lock.py` checks process liveness with `os.kill(pid, 0)` on POSIX and
  `OpenProcess`/`GetExitCodeProcess` on Windows.
- `worker.py` discovers the claude-mem worker port from `worker.pid`/
  `supervisor.json`, then env/settings, then a health probe; it never relies on
  a uid that does not exist on Windows.
- `cli.py` generates POSIX symlink launchers or relies on pip console scripts on
  Windows, and hides console windows for background subprocesses.

The data format and worker API are platform-independent.

## License

MIT - see [LICENSE](LICENSE).
