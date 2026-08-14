# Omni-mem-Opencode

Two-way synchronization of **claude-mem** memory across multiple **OpenCode** and
**DeepSeek Harness** installations, on **Linux and Windows**.

```text
OpenCode / DeepSeek Harness -> claude-mem worker -> Omni-mem Python CLI -> private Git data repository
```

Each machine exports its local claude-mem memory to a **private Git repository**
and imports the merged memory of the other machines. The sync core is pure
Python; only the service integration, config paths, launchers, process handling,
and the *startup-pull trigger* differ per OS or per coding tool.

Both platforms write into the **same claude-mem worker**, so the automatic
watcher recognizes OpenCode and DeepSeek Harness observations alike. Only *who
runs `omni-mem startup-pull` when the tool starts* changes with the platform
selected during install: an OpenCode plugin, or a DeepSeek Harness plugin.

## Quick install

Run the installer from the wrapper directory. It asks a few questions, clones
(or attaches) your private data repository, and sets up the automatic watcher.

**Linux:**

```bash
git clone https://github.com/Bleed00/Omni-mem-Opencode.git
cd Omni-mem-Opencode
python3 -m omni_mem install
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/Bleed00/Omni-mem-Opencode.git
cd Omni-mem-Opencode
pip install -e .
python -m omni_mem install
```

> On Windows the `omni-mem`, `omni-push` and `omni-pull` commands come from
> `pip install -e .`; on Linux the installer writes them to `~/.local/bin`.

> The terminal UI differs by platform: **Windows** uses `rich` and
> `questionary` (installed by `pip install -e .`); **Linux** uses a
> zero-dependency ANSI UI, so no pip package or virtual environment is needed
> there.

The install command is interactive:

1. asks which platform to set up — **OpenCode** or **DeepSeek Harness**;
2. verifies Git, Python, `curl`, the chosen tool (OpenCode + the claude-mem
   plugin, **or** DeepSeek Harness + a DSH profile), and a running worker;
3. offers to create a **new** private data repository (requires `gh`) or attach
   an **existing** one (always available);
4. clones the data repository into `data/`;
5. asks whether automatic synchronization should be enabled (and its
   thresholds);
6. asks whether to pull memory when the chosen tool starts (startup pull);
7. installs the watcher service and the startup-pull trigger for the platform
   you chose (an OpenCode plugin, or the `dsh-omni-mem` DeepSeek Harness
   bundle).

When the installer finishes you can start using it immediately:

```bash
omni-mem push          # export local memory to the data repository
omni-mem pull          # import the data repository into the local worker
omni-mem status        # show sync and service state
```

### Choosing a platform

During install you pick **opencode** or **deepseek**. The choice changes only the
startup-pull trigger:

- **opencode** writes and registers the `omni-mem.js` OpenCode startup plugin
  (the historical behavior);
- **deepseek** installs the `@bleed00/dsh-omni-mem` bundle into a DeepSeek
  Harness profile, which pulls the data repository at session start and pushes
  new memory back on "put" events.

Everything else — the git sync, the merge rules, the automatic watcher — is
identical regardless of platform. The watcher's push trigger already reads
claude-mem's own rows, so OpenCode and DeepSeek Harness observations are pushed
the same way by the same code.

## Prerequisites

Install these before running the installer (which ones are required depends on
the platform you select):

- **OpenCode** — for the `opencode` platform
- **claude-mem** installed and configured as an OpenCode plugin (for the
  `opencode` platform)
- **DeepSeek Harness** (`dsh` on `PATH` with at least one profile) — for the
  `deepseek` platform
- a running **claude-mem worker**
- **Python** 3.10 or newer
- **Git**
- **`curl`**
- **GitHub CLI (`gh`)** — optional; only needed to *create* a new data
  repository. Without it you can still attach an existing one.
- a **private GitHub data repository** (or permission to create one)

### Install OpenCode and claude-mem

For the **opencode** platform:

```bash
opencode --version                                     # verify OpenCode
npx -y @thedotmack/claude-mem install --ide opencode   # install claude-mem
```

### Install DeepSeek Harness

For the **deepseek** platform, install DeepSeek Harness and create a profile:

```bash
npx -y @deepseek-ai/dsh web        # or `dsh plugin init <profile>` for a CLI profile
dsh plugin --profile <profile> add @deepseek-ai/dsh-base
```

The omni-mem installer mounts `@bleed00/dsh-omni-mem` into the profile you
choose; the claude-mem worker still must be running.

Configure the worker, for example with OpenRouter. Save as
`~/.claude-mem/settings.json`:

```json
{
  "CLAUDE_MEM_RUNTIME": "worker",
  "CLAUDE_MEM_PROVIDER": "openrouter",
  "CLAUDE_MEM_OPENROUTER_MODEL": "poolside/laguna-xs-2.1:free",
  "CLAUDE_MEM_OPENROUTER_API_KEY": "YOUR_API_KEY"
}
```

Protect it and start the worker:

```bash
chmod 600 ~/.claude-mem/settings.json
npx claude-mem start
npx claude-mem status
```

### Install GitHub CLI

Used only to create a *new* data repository. Skip this if you will attach an
existing repository.

```bash
# Arch / CachyOS
sudo pacman -S github-cli

# Debian / Ubuntu
sudo apt install gh

# Fedora
sudo dnf install gh

# Windows
winget install GitHub.cli
```

Then authenticate:

```bash
gh auth login
```

Choose `GitHub.com`, `HTTPS`, and browser authentication.

## Usage

### Manual synchronization

Export the local memory to the private data repository:

```bash
omni-mem push
omni-push          # alias
```

Import the data repository into the local worker:

```bash
omni-mem pull
omni-pull          # alias
```

Both operations are idempotent: re-running a pull never creates duplicate
records, and a push with nothing new produces no commit.

Run the first full export explicitly right after installing, so the accumulated
memory is available on every machine:

```bash
omni-mem push
```

### Status

```bash
omni-mem status
```

Shows whether the worker is reachable, the state of the local data repository,
the automatic-sync configuration, and the watcher service status.

## Automatic synchronization

During installation, enable automatic sync and configure:

- observations per push (e.g. `1`, `10`, `30`);
- polling interval in seconds;
- debounce interval in seconds.

The watcher starts from a **baseline** of the observations already present, so
installing never pushes the whole database unexpectedly. After the first manual
`omni-mem push`, the watcher pushes automatically once the configured number of
new observations is reached. A failed push is retried at the next polling
cycle.

The watcher is installed per platform:

- **Linux**: a `systemd --user` service
  (`omni-mem-watch.service`) with restart on failure.
- **Windows**: a per-user **registry Run key** that launches the watcher hidden
  at logon via `pythonw.exe`. It uses no elevated APIs, so it works on accounts
  where Task Scheduler registration is blocked; as a trade-off it does not
  auto-restart on crash (it starts again at the next logon). Output is appended
  to `%APPDATA%\omni-mem\watch.log`.

The installer also registers a startup-pull trigger for the platform you chose.
For **opencode** that is an OpenCode startup plugin that runs
`omni-mem startup-pull` whenever OpenCode starts; for **deepseek** it is the
`@bleed00/dsh-omni-mem` bundle in the selected DSH profile, which pulls at
session start and pushes new memory back on "put" events. Both run with retries
while the worker is still starting and do not modify the claude-mem plugin.

Useful commands:

```bash
omni-mem status                 # overall state incl. service
omni-mem service status         # watcher service state
omni-mem service remove         # stop and remove the watcher service
omni-mem watch                  # run the watcher in the foreground
omni-mem startup-pull           # test the startup pull manually
systemctl --user status omni-mem-watch.service        # Linux service state
journalctl --user -u omni-mem-watch.service -f        # Linux watcher logs
Get-Content "$env:APPDATA\omni-mem\watch.log" -Tail 20   # Windows watcher log
```

## Uninstall

```bash
omni-mem uninstall        # remove service, launchers, startup trigger and config
omni-mem reinstall        # uninstall and run the installer again
```

`uninstall` removes whichever startup trigger this install registered: the
OpenCode plugin, or the `@bleed00/dsh-omni-mem` bundle from the saved DSH
profile.

## Data model and merge safety

The data repository contains:

```text
sessions.json
observations.json
summaries.json
prompts.json
```

Records are merged using **stable cross-device keys** instead of local SQLite
numeric IDs:

- sessions: platform plus content session ID;
- observations: memory session, title, and creation timestamp;
- summaries: memory session ID;
- prompts: platform, content session ID, and prompt number.

The first push exports the complete local knowledge base. Later pushes preserve
the complete accumulated data while Git stores only the differences in each
commit. Deletions and edits are propagated through tombstones so every machine
converges on the same state.

## Configuration

The local Omni-mem configuration is stored at:

```text
~/.config/omni-mem/config.json       # Linux
%APPDATA%\omni-mem\config.json       # Windows
```

It contains local paths, the data repository URL, the selected platform
(`opencode` or `deepseek`), the chosen DSH profile (`dsh_profile`, when deepseek),
and automatic-sync settings. It does not contain API keys.

Watcher state is stored separately at:

```text
~/.config/omni-mem/watch-state.json  # Linux
%APPDATA%\omni-mem\watch-state.json  # Windows
```

## Security

- Keep the data repository **private**. It contains prompts, observations, and
  summaries from your sessions.
- Never commit `~/.claude-mem/settings.json` or API keys.
- Use `chmod 600 ~/.claude-mem/settings.json` (Linux).
- The wrapper repository is safe to publish only after its Git history has been
  audited and no personal data has ever been committed.

## Development

On **Linux** the CLI runs from the wrapper with no installation:

```bash
python3 -m omni_mem --help
python3 -m unittest discover tests
```

On **Windows**, install the package (editable) to get the `omni-mem`,
`omni-push` and `omni-pull` commands and the `rich`/`questionary` UI:

```powershell
pip install -e .
```

`omni-mem install` bootstraps this automatically on Windows when the commands
or the UI dependencies are missing.

The runtime uses the Python standard library, plus `rich` and `questionary`
for the Windows terminal UI (Linux uses a zero-dependency ANSI UI), and the
system `git` and `gh` commands.

## Platform-specific pieces

The sync core (`data.py`, `sync.py`, `git.py`, `watcher.py`, the worker HTTP
client) is platform-independent. Only these pieces differ per OS or per coding
tool:

- `service.py` dispatches to `service_linux.py` (systemd user services) or
  `service_windows.py` (logon autostart via the per-user Run key).
- `config.py` resolves `~/.config/omni-mem` on POSIX and `%APPDATA%\omni-mem` on
  Windows, and skips `chmod` on Windows.
- `lock.py` checks process liveness with `os.kill(pid, 0)` on POSIX and
  `OpenProcess`/`GetExitCodeProcess` on Windows.
- `worker.py` discovers the claude-mem worker port from `worker.pid`/
  `supervisor.json`, then env/settings, then a health probe; it never relies on
  a uid that does not exist on Windows.
- `ui.py` dispatches to `ui_rich.py` (rich + questionary, Windows) or
  `ui_ansi.py` (zero-dependency ANSI, Linux).
- `cli.py` generates POSIX symlink launchers or relies on pip console scripts on
  Windows, and hides console windows for background subprocesses.
- `deepseek.py` discovers DSH profiles under `$DSH_HOME/profiles` and mounts (or
  removes) the `@bleed00/dsh-omni-mem` bundle via `dsh plugin`.
- `git.py` and `cli.py` run background subprocesses with
  `CREATE_NO_WINDOW` on Windows so no console window flashes.

The data format and worker API are platform- and tool-independent.

## DeepSeek Harness plugin

The `dsh-plugin/` directory is a self-contained, installable DeepSeek Harness
bundle (`@bleed00/dsh-omni-mem`). It makes DSH a full peer of the sync: on
`agent/session-start` it runs `omni-mem startup-pull` (the same command the
OpenCode plugin runs), and as prompts/tool results land in the claude-mem worker
it pushes the new memory back to git through a debounced, fire-and-forget
`omni-mem push`.

It never touches the worker API or SQLite — it only shells out to the `omni-mem`
CLI. Because `omni-mem push` is idempotent and serialized by omni-mem's
`SyncLock`, the automatic watcher can stay active as an independent fallback
without conflict.

```sh
cd dsh-plugin
pnpm install --config.auto-install-peers=false
pnpm run build   # tsc + tsdown → lib/index.js
pnpm test
```

## License

MIT - see [LICENSE](LICENSE).
