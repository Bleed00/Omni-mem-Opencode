import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { join } from 'node:path'
import { homedir } from 'node:os'
import { existsSync } from 'node:fs'
import { resolveAnywhereClaudeMemCommand, runDetached, DebouncedPusher } from '../src/sync.js'

describe('resolveAnywhereClaudeMemCommand', () => {
  const originalPlatform = process.platform

  afterEach(() => {
    // Vitest does not allow reassigning process.platform; restore what we can.
    Object.defineProperty(process, 'platform', { value: originalPlatform, configurable: true })
    vi.unstubAllEnvs()
  })

  it('returns the explicit absolute command when configured', () => {
    expect(resolveAnywhereClaudeMemCommand('/custom/bin/anywhere-claude-mem')).toBe('/custom/bin/anywhere-claude-mem')
  })

  it('falls back to a POSIX ~/.local/bin launcher when it exists, else the bare name', () => {
    Object.defineProperty(process, 'platform', { value: 'linux', configurable: true })
    vi.stubEnv('PATH', '')
    const local = join(homedir(), '.local', 'bin', 'anywhere-claude-mem')
    const expected = existsSync(local) ? local : 'anywhere-claude-mem'
    expect(resolveAnywhereClaudeMemCommand()).toBe(expected)
  })

  it('refuses to return an external path when a Windows PATH entry is only dotless', () => {
    // Regression guard: an empty/absent PATH must not fall through to a random
    // directory; the resolver degrades to the bare command name.
    Object.defineProperty(process, 'platform', { value: 'win32', configurable: true })
    vi.stubEnv('PATH', '')
    expect(resolveAnywhereClaudeMemCommand()).toBe('anywhere-claude-mem')
  })
})

describe('runDetached', () => {
  it('returns a detached, unrefed child process for the given command', () => {
    // 'true' always exits 0 without touching anything.
    const child = runDetached('true', ['cmd'])
    expect(child.pid).toBeGreaterThan(0)
  })
})

describe('DebouncedPusher', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('is disabled and inert when enabled is false', () => {
    const pusher = new DebouncedPusher('anywhere-claude-mem', 100, false)
    expect(pusher.signal()).toBe(false)
    expect(pusher.fired).toBe(0)
    pusher.dispose()
  })

  it('arms on the first signal and coalesces a burst', () => {
    const pusher = new DebouncedPusher('anywhere-claude-mem', 1000, true)
    expect(pusher.signal()).toBe(true) // leading edge
    expect(pusher.signal()).toBe(false) // subsequent signals not leading
    expect(pusher.armed).toBe(true)
    expect(pusher.fired).toBe(0)
    pusher.dispose()
  })

  it('fires exactly one push after the debounce window', () => {
    const pusher = new DebouncedPusher('anywhere-claude-mem', 1000, true)
    pusher.signal()
    pusher.signal()
    vi.advanceTimersByTime(1000)
    expect(pusher.fired).toBe(1)
    expect(pusher.armed).toBe(false)
    pusher.dispose()
  })

  it('resets the window when a new signal arrives mid-debounce', () => {
    const pusher = new DebouncedPusher('anywhere-claude-mem', 1000, true)
    pusher.signal()
    vi.advanceTimersByTime(900) // still waiting
    pusher.signal() // restarts the window
    vi.advanceTimersByTime(900) // not enough (restarted at t=900)
    expect(pusher.fired).toBe(0)
    vi.advanceTimersByTime(100) // completes the second window
    expect(pusher.fired).toBe(1)
    pusher.dispose()
  })

  it('dispose cancels an armed push', () => {
    const pusher = new DebouncedPusher('anywhere-claude-mem', 1000, true)
    pusher.signal()
    pusher.dispose()
    vi.advanceTimersByTime(2000)
    expect(pusher.fired).toBe(0)
  })
})
