# dsh-anywhere-claude-mem

A [DeepSeek Harness](https://github.com/deepseek-ai) plugin that makes DSH a full
peer in the **anywhere-claude-mem** cross-machine sync of your `claude-mem` memory.

[![npm](https://img.shields.io/npm/v/@bleed00/dsh-anywhere-claude-mem?label=npm&logo=npm)](https://www.npmjs.com/package/@bleed00/dsh-anywhere-claude-mem)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Node.js](https://img.shields.io/badge/Node.js-%E2%89%A520.12-339933?logo=node.js&logoColor=white)](https://nodejs.org/)
[![dsh-plugin](https://img.shields.io/badge/topic-dsh--plugin-555555)](https://github.com/topics/dsh-plugin)

When a DeepSeek Harness session starts, this plugin pulls the data repository
into the local claude-mem worker — the same `anywhere-claude-mem startup-pull` that the
OpenCode startup plugin runs. During the session it also watches the prompt /
tool "put" events and, after a debounce, pushes new memory back to git. DeepSeek
Harness thus becomes a first-class participant in the bidirectional anywhere-claude-mem
sync, so the memory DSH produces is available on every other machine — and the
memory other machines produced is already there when DSH starts.

> The git sync itself is entirely delegated to the `anywhere-claude-mem` Python command.
> This plugin never touches the claude-mem worker API or its SQLite database; it
> only shells out to the `anywhere-claude-mem` CLI.

## Why the plugin and the watcher coexist safely

The automatic watcher (`anywhere-claude-mem watch`) already polls the claude-mem database
and pushes once a configured number of new observations lands. That detection is
based on **claude-mem's own rows, independent of which coding tool wrote them** —
OpenCode, Claude Code, or DeepSeek Harness all feed the same worker. So the
watcher alone would eventually push DSH memory too.

`dsh-anywhere-claude-mem` makes DSH push **promptly** on the actual "put" instead of waiting
for the next poll tick. The two can run at the same time without conflict
because `anywhere-claude-mem push` is idempotent (a push with nothing new creates no
commit) and serially locked by anywhere-claude-mem's `SyncLock`; a push this plugin fires
and a push the watcher fires simply serialize, and the duplicate is a no-op.

## Install

One-liner from the project checkout (or any profile):

```sh
npx -y @deepseek-ai/dsh plugin --profile <profile> add github:Bleed00/Anywhere-claude-mem/dsh-plugin
```

Or install the `anywhere-claude-mem` Python package and use its installer, which offers a
**deepseek** setup alongside **opencode** and writes this bundle into your DSH
profile for you:

```sh
pip install -e .
anywhere-claude-mem install      # choose "deepseek" at the platform prompt
```

## Requirements

- A [DeepSeek Harness](https://github.com/deepseek-ai) installation with `dsh`
  on `PATH` and a profile to patch.
- The npm package `@bleed00/dsh-anywhere-claude-mem` (or this checkout) available to pnpm.
- `anywhere-claude-mem` installed (Python package) and configured (`anywhere-claude-mem install`).
- The claude-mem worker running (`http://127.0.0.1:37700`).

## Config

| Field | Default | Description |
|---|---|---|
| `command` | resolved on PATH, then `~/.local/bin/anywhere-claude-mem` | The `anywhere-claude-mem` executable. |
| `pullOnSessionStart` | `true` | Run `anywhere-claude-mem startup-pull` when a DSH session starts. |
| `pushOnPut` | `true` | Push new memory back to git on "put" events. |
| `pushDebounceMs` | `10000` | Coalescing window (ms) for push-on-put. |
| `pushOnEvents` | `["prompt","tool"]` | Which "put" events count: `prompt`, `tool`, or both. |

Override any of them in your profile's `cordis.patch.yml`:

```yaml
- id: anywhere-claude-mem
  config:
    command: /home/me/.local/bin/anywhere-claude-mem
    pushDebounceMs: 15000
    pushOnEvents:
      - prompt
```

## How it works

- `agent/session-start` → `anywhere-claude-mem startup-pull` (fire-and-forget).
- `agent/pre-step` (a prompt was submitted) and `tools/post-execute` (a tool
  finished) are the "put" moments. Each arms a debouncer; once `pushDebounceMs`
  passes with no new event it runs `anywhere-claude-mem push`, again fire-and-forget so a
  sync never blocks a turn.

## Development

```sh
pnpm install --config.auto-install-peers=false
pnpm run build   # tsc + tsdown → lib/index.js
pnpm test
```

The package targets Node ≥ 20.12, TypeScript 6.0, and is authored against the
`@deepseek-ai/*` framework packages (cordis, schemastery, dsh-agent, dsh-tools,
dsh-skill). Because the peer packages are supplied by the host dsh installation,
install with `--config.auto-install-peers=false`.

## License

MIT — see [LICENSE](../../LICENSE) © Bleed00
