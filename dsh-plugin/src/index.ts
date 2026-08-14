/**
 * `dsh-omni-mem` — a DeepSeek Harness plugin that makes DSH a full peer in the
 * omni-mem cross-machine claude-mem sync. On session start it pulls the data
 * repository into the local claude-mem worker (the same `startup-pull` the
 * OpenCode startup plugin runs), and as new prompts/observations land in the
 * worker during the session it pushes them back to git through a debounced, 
 * fire-and-forget `omni-mem push`.
 *
 * The git sync itself is entirely delegated to the omni-mem Python command —
 * this plugin never touches the worker API or SQLite, only shells out. Because
 * omni-mem push is idempotent and serialized by its own `SyncLock`, the watcher
 * service can stay active as an independent fallback without any conflict.
 * @module dsh-omni-mem
 */

import type { Context } from '@deepseek-ai/cordis'
import Schema from '@deepseek-ai/schemastery'
import type {} from '@deepseek-ai/dsh-skill'
import type {} from '@deepseek-ai/dsh-agent'
import type {} from '@deepseek-ai/dsh-tools'
import { DebouncedPusher, resolveOmniMemCommand, runDetached } from './sync.js'

export const name = 'omni-mem'
export const inject: string[] = []

/** Plugin configuration. */
export interface Config {
  /** The omni-mem executable (default: resolved on PATH, then ~/.local/bin). */
  command?: string
  /** Pull the data repository at session start. Defaults to true. */
  pullOnSessionStart?: boolean
  /** Debounce interval (ms) over which "put" (prompt/tool) pushes coalesce. Defaults to 10000. */
  pushDebounceMs?: number
  /**
   * Push new memory back to git when a "put" event is observed. Defaults to
   * true. The watcher remains an independent fallback either way.
   */
  pushOnPut?: boolean
  /** Which "put" events count as new memory. Defaults to both prompt and tool. */
  pushOnEvents?: Array<'prompt' | 'tool'>
}

export const Config: Schema<Config> = Schema.object({
  command: Schema.string().default(''),
  pullOnSessionStart: Schema.boolean().default(true),
  pushDebounceMs: Schema.number().default(10_000),
  pushOnPut: Schema.boolean().default(true),
  pushOnEvents: Schema.array(Schema.union(['prompt', 'tool'])).default(['prompt', 'tool']),
})

type ResolvedConfig = Config & {
  command: string
  pullOnSessionStart: boolean
  pushDebounceMs: number
  pushOnPut: boolean
  pushOnEvents: Array<'prompt' | 'tool'>
}

/** Mount the omni-mem peer: a startup pull + a debounced push-on-put trigger. */
export function apply(ctx: Context, config: Config): void {
  const resolved = config as ResolvedConfig
  assertPositiveInteger('pushDebounceMs', resolved.pushDebounceMs)

  const command = resolveOmniMemCommand(resolved.command)
  ctx.logger?.info?.(`dsh-omni-mem: using omni-mem command '${command}'`)

  const pusher = new DebouncedPusher(command, resolved.pushDebounceMs, resolved.pushOnPut)

  if (resolved.pullOnSessionStart) {
    ctx.on('agent/session-start', () => {
      runDetached(command, ['startup-pull'])
    })
  }

  if (resolved.pushOnPut) {
    if (resolved.pushOnEvents.includes('prompt')) {
      ctx.on('agent/pre-step', (_payload, next) => {
        // Delegate so later listeners still see the decision, arm a push, and
        // only then resolve. Armed pushes are fire-and-forget and debounced,
        // so this never blocks the turn.
        const downstream = next()
        void downstream.then(() => {
          pusher.signal()
        })
        return downstream
      })
    }

    if (resolved.pushOnEvents.includes('tool')) {
      ctx.on('tools/post-execute', (_exec, _result, next) => {
        pusher.signal()
        return next()
      })
    }
  }

  ctx.effect(() => () => pusher.dispose(), 'dsh-omni-mem: drop armed push')
}

function assertPositiveInteger(field: string, value: number): void {
  if (!Number.isInteger(value) || value < 1) {
    throw new Error(`omni-mem: ${field} must be a positive integer`)
  }
}
