# Omni-mem-Opencode

Two-way sync of **claude-mem** memory (observations, summaries, prompts,
sessions) across multiple PCs, using a **private GitHub repo** as transport.

This project is a **wrapper**: it only contains code and instructions. **No
personal data is tracked here.** The data lives in a **separate data repo**
(private) on GitHub, whose local clone sits in the `data/` folder of this
wrapper.

```
┌─ Omni-mem-Opencode (wrapper, code only) ───────────────┐
│  README.md · install.sh · scripts/*                    │
│  data/  ← local clone of the DATA REPO                 │
│     ├── .git/                                          │
│     ├── sessions.json  observations.json               │
│     └── summaries.json  prompts.json                   │
└───────────────┬────────────────────────────────────────┘
                │  omni-push / omni-pull
                ▼
        github.com/<you>/<data-repo>   (private, storage)
```

No external services (no cmem.ai Pro, no paid cloud): the data lives in your
own repo, and only you can access it.

---

## What it does

- **`omni-push`** - exports this PC's claude-mem memory into the data repo
  (observations, summaries, prompts, sessions).
- **`omni-pull`** - imports the memory from the data repo into this PC's
  worker.
- The import is **idempotent**: claude-mem deduplicates by id, so re-running
  never creates duplicates.
- The export is a **union-merge by id**: entries from other PCs that are no
  longer in the local worker are preserved, so every PC accumulates the full
  knowledge base.

---

## Prerequisites

On **every** PC:

- **opencode**
- **claude-mem** as an opencode plugin, with the **worker running**
- **git**, **python3**, **curl**
- **GitHub CLI** (`gh`) authenticated - needed to create/attach the data repo
- Access to the data repo (or permission to create one)

> This project does **not** install opencode or claude-mem: it assumes they are
> already working. It only wires up the synchronization.

---

## 1. GitHub CLI (gh)

You need `gh` to create (or attach) the data repo. If you already used `gh`,
skip to [checking](#check-gh).

### Install gh

Pick the way that fits your OS:

```bash
# Linux (Debian/Ubuntu)
sudo apt install gh

# Linux (Fedora)
sudo dnf install gh

# macOS
brew install gh

# Windows
winget install --id GitHub.cli
```

Or follow the official guide: <https://cli.github.com>

### Authenticate

```bash
gh auth login
```

Follow the prompts:

1. Choose **GitHub.com**
2. Choose **HTTPS**
3. Authenticate via browser (recommended) or paste a token

### Give gh permission to delete repos (optional but recommended)

Used later to clean up test repos:

```bash
gh auth refresh -h github.com -s delete_repo
```

### Check

```bash
gh api user -q .login     # prints your username, e.g. "alice"
gh repo list              # lists your repos
```

If both work, `gh` is ready.

---

## 2. Verify claude-mem installation

### 2.1 Install the plugin

```bash
npx -y @thedotmack/claude-mem install --ide opencode
```

This installs the opencode plugin
(`~/.config/opencode/plugins/claude-mem.js`), creates the memory context file
(`~/.config/opencode/AGENTS.md`) and registers the `claude-mem` MCP server in
the opencode config.

### 2.2 Runtime helpers

The worker needs **Bun** and **uv/uvx**:

```bash
# Bun (worker runtime)
curl -fsSL https://bun.sh/install | bash

# uv / uvx (Chroma, the vector search engine)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then reopen the terminal and check: `bun --version` and `uvx --version`.

### 2.3 Configure the provider

claude-mem defaults to Claude (paid Anthropic account). If you want to use a free
version through the openrouter API key you can create/edit this file:

Create `~/.claude-mem/settings.json`:

that should look like this in the end:

```json
{
  "CLAUDE_MEM_RUNTIME": "worker",
  "CLAUDE_MEM_PROVIDER": "openrouter",
  "CLAUDE_MEM_OPENROUTER_MODEL": "poolside/laguna-xs-2.1:free",
  "CLAUDE_MEM_OPENROUTER_API_KEY": "YOUR_API_KEY"
}
```

It is recommended to protect the file (as it contains your API key):

```bash
chmod 600 ~/.claude-mem/settings.json
```

Start the worker and verify:

```bash
npx claude-mem start
npx claude-mem status
```

---

## 3. Install Omni-mem-Opencode

### 3.1 Clone the wrapper

```bash
git clone https://github.com/Bleed00/Omni-mem-Opencode.git
cd Omni-mem-Opencode
```

### 3.2 Run the installer

```bash
bash scripts/install.sh
```

The installer guides you through 5 steps:

1. **Check prerequisites** - opencode, claude-mem, running worker, `gh`, git,
   python3, curl. It stops with an error if something is missing.
2. **Choose the data repo** - either:
   - **create a new one** (enter a name, it is created private via `gh`), or
   - **attach an existing one** (enter the URL, it is verified).
3. **Local clone** - the data repo is cloned into `data/` inside the wrapper.
4. **Periodic auto-push** (optional) - if you confirm, choose an interval
   (e.g. `30m`, `1h`, `2h`) and a systemd user timer is enabled.
5. **Commands** - creates `~/.local/bin/omni-push` and
   `~/.local/bin/omni-pull`.

### 3.3 Sync

```bash
omni-pull   # import the memory from the data repo into THIS PC
omni-push   # export THIS PC's memory to the data repo
```

Run them from any directory.

---

## How it works

### Export -> data repo (`omni-push`)

1. Reads the claude-mem worker (HTTP `127.0.0.1:<port>`) and downloads **all**
   observations, summaries and prompts (pagination of 100).
2. Reads the local DB (`~/.claude-mem/claude-mem.db`, read-only) to export the
   **sessions** (`sdk_sessions`) and to enrich summaries with their
   `memory_session_id` (otherwise the import would fail).
3. Writes `data/sessions.json`, `data/observations.json`,
   `data/summaries.json`, `data/prompts.json` with a **union-merge by id**.
4. `git commit` locally, then `git pull --rebase`, then `git push` to the data
   repo.

### Data repo -> local import (`omni-pull`)

1. `git pull` in the data repo.
2. Sends `data/*.json` to the worker with `POST /api/import`.

### Worker port

Detected automatically: `CLAUDE_MEM_WORKER_PORT` from
`~/.claude-mem/settings.json`, otherwise the default `37700 + (uid % 100)`.
On typical installs it is `37700`.

---

## Project organization

- **opencode** -> everything lands under the project `"opencode"` (the plugin
  uses `project?.name || "opencode"`, and opencode does not expose a project
  name, so it is always the fallback). Consistent across PCs.
- **Manual memories** -> use the explicit project name (e.g. `VCU_2026`),
  preserved by the sync and queryable per project.

---

## Security & privacy

- The **data repo** is **private**: only you (and anyone you invite) can read
  it. It contains your session texts - **never make it public**.
- The wrapper repo contains no personal data.
- `~/.claude-mem/settings.json` (with your API key) is never touched or
  uploaded. Keep it at `600`:
  ```bash
  chmod 600 ~/.claude-mem/settings.json
  ```

---

## Windows support

Current scripts are **bash** and target Linux/macOS. On Windows the supported
paths are **Git Bash** (ships with Git for Windows) or **WSL**.

Known limitations on Windows:

- The **auto-push timer** uses `systemctl --user` (systemd), which is not
  available on native Windows - use Task Scheduler or WSL instead.
- `~/.local/bin` and symlink-based command installation assume a Unix-like
  shell.
- `readlink -f` is available in Git Bash and WSL.

A portable Python-based verifier/configurator is a possible future improvement
(see roadmap in the repo issues).

---

## Limitations

- **Never two `omni-push` at the same time**: it uses `pull --rebase`, but if
  two PCs push together the merge may need attention.
- The "cold" memory (the Chroma vector index) is **not** synced: it regenerates
  itself from the DB.
- Observations/summaries/prompts carry absolute paths from the PC that produced
  them (`files_read`, `files_modified`): those paths may not exist on the
  destination PC, but the content remains searchable.

---

## License

MIT - see [LICENSE](LICENSE).
