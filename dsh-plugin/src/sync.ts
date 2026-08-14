/**
 * How the plugin talks to the omni-mem CLI: locate the executable, run
 * fire-and-forget subprocesses, and debounce the "push on put" trigger so a
 * burst of prompts doesn't spawn overlapping `omni-mem push` runs.
 *
 * The sync itself (git pull/push into the claude-mem worker) lives in the
 * omni-mem Python command. This module only shells out to it; every run is
 * safe to retry because `omni-mem push` is idempotent and serialized by the
 * omni-mem `SyncLock`.
 * @module dsh-omni-mem/sync
 */

import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

/** Runtime control surface for the sync coordinator. */
export interface SyncLimits {
  /** The omni-mem executable to invoke. */
  command: string
  /** Debounce interval (ms) over which push triggers coalesce. */
  debounceMs: number
  /** When true, collect push triggers and fire a single push after debounce. */
  enabled: boolean
}

/**
 * Locate the omni-mem executable. Precedence:
 * an explicit absolute path, then `omni-mem` on the PATH, then the Linux
 * `~/.local/bin/omni-mem` launcher that `omni-mem install` writes. Falls back
 * to the bare name so the child receives a descriptive ENOENT if nothing is
 * found rather than crashing the harness.
 */
export function resolveOmniMemCommand(configured?: string): string {
  const explicit = configured?.trim()
  if (explicit) return explicit

  const onPath = findFirstOnPath(['omni-mem', 'omni-mem.exe', 'omni-mem.cmd'])
  if (onPath !== undefined) return onPath

  if (process.platform !== 'win32') {
    const local = join(homedir(), '.local', 'bin', 'omni-mem')
    if (existsSync(local)) return local
  }
  return 'omni-mem'
}

/**
 * Run an omni-mem command detached and forget the child. Fire-and-forget:
 * the caller never awaits its completion, so a sync never blocks a prompt or
 * tool turn. The spawned child is unref'd; tests observe the returned process.
 */
export function runDetached(command: string, args: string[]): ReturnType<typeof spawn> {
  const child = spawn(command, args, {
    detached: true,
    stdio: 'ignore',
    windowsHide: true,
  })
  child.on('error', () => { /* worker-down / command-missing is expected */ })
  child.unref()
  return child
}

/**
 * A debounced push trigger: accumulates "put" signals (a prompt submitted, a
 * tool result observed) and, once `debounceMs` has passed with no new signal,
 * runs a single `omni-mem push`. The watcher remains an independent fallback,
 * so a lost push here is recovered by the next polling cycle.
 */
export class DebouncedPusher {
  private timer: NodeJS.Timeout | undefined
  private lastArgs: string[] = ['push']
  private pending = false
  private pushes = 0

  constructor(
    private readonly command: string,
    private readonly debounceMs: number,
    private readonly enabled: boolean,
  ) {}

  /** Returns true when this signal is the leading edge (arms the debounce). */
  signal(args?: string[]): boolean {
    if (!this.enabled) return false
    if (args !== undefined) this.lastArgs = args
    const first = !this.pending
    this.pending = true
    if (this.timer !== undefined) clearTimeout(this.timer)
    this.timer = setTimeout(() => {
      this.timer = undefined
      this.pending = false
      this.pushes += 1
      runDetached(this.command, this.lastArgs)
    }, this.debounceMs)
    return first
  }

  /** True when a push is armed (waiting out the debounce). */
  get armed(): boolean {
    return this.pending
  }

  /** Number of pushes actually fired since this pusher was created. */
  get fired(): number {
    return this.pushes
  }

  dispose(): void {
    if (this.timer !== undefined) {
      clearTimeout(this.timer)
      this.timer = undefined
    }
    this.pending = false
  }
}

function findFirstOnPath(names: string[]): string | undefined {
  const pathEntries = (process.env.PATH ?? '').split(process.platform === 'win32' ? ';' : ':')
  for (const dir of pathEntries) {
    if (dir.length === 0) continue
    for (const name of names) {
      const candidate = join(dir, name)
      try {
        if (existsSync(candidate)) return candidate
      } catch {
        // Keep scanning.
      }
    }
  }
  return undefined
}
