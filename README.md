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

The current implementation targets **Linux with systemd user services**. The
core is Python and is intentionally being prepared for a future native Windows
implementation, but Windows support is not enabled yet.

## Prerequisites

Install these components before running Omni-mem:

- OpenCode
- claude-mem configured as an OpenCode plugin
- A running claude-mem worker
- Python 3.10 or newer
- Git
- GitHub CLI (`gh`)
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

Run the Python installer through the compatibility bootstrap:

```bash
bash scripts/install.sh
```

Alternatively:

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

Useful commands:

```bash
omni-mem status
omni-mem watch
omni-mem service status
omni-mem service remove
systemctl --user status omni-mem-watch.service
journalctl --user -u omni-mem-watch.service -f
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
~/.config/omni-mem/config.json
```

It contains local paths, the data repository URL, and automatic-sync settings.
It does not contain API keys.

Watcher state is stored separately in:

```text
~/.config/omni-mem/watch-state.json
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

## Future Windows support

Windows support is intentionally not enabled in this Linux-first version. The
planned Windows implementation will reuse the Python sync core and replace
only platform-specific pieces:

- Windows Task Scheduler instead of systemd;
- Windows configuration directories instead of XDG paths;
- native launcher handling instead of Unix symlinks.

The data format and worker API are platform-independent.

## License

MIT - see [LICENSE](LICENSE).
