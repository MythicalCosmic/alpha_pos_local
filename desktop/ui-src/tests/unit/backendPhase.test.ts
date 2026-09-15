import { describe, expect, it } from 'vitest';
import type { ServerStatus } from '../../src/bridge/types';
import { deriveBackendPhase, isTransitional, powerAction, serverProblem } from '../../src/data/backendPhase';

const s = (over: Partial<ServerStatus>): ServerStatus => ({
  running: false, phase: 'stopped', desired_running: false, django_ready: true, last_error: null, ...over,
});
const q = (data: ServerStatus | undefined, transportFailures = 0) => ({ data, transportFailures });

describe('deriveBackendPhase', () => {
  it('connecting before the first status arrives', () => {
    expect(deriveBackendPhase(q(undefined), null)).toBe('connecting');
    expect(deriveBackendPhase(q(undefined, 1), null)).toBe('connecting');
  });

  it('unreachable after two consecutive transport failures, even with cached data', () => {
    expect(deriveBackendPhase(q(undefined, 2), null)).toBe('unreachable');
    expect(deriveBackendPhase(q(s({ running: true, phase: 'running' }), 3), null)).toBe('unreachable');
  });

  it('running', () => {
    expect(deriveBackendPhase(q(s({ running: true, phase: 'running', desired_running: true })), null)).toBe('running');
  });

  it('booting when stopped but the backend wants to run', () => {
    expect(deriveBackendPhase(q(s({ desired_running: true, django_ready: false })), null)).toBe('booting');
    expect(deriveBackendPhase(q(s({ desired_running: true, django_ready: true })), null)).toBe('booting');
  });

  it('booting when running but django is not ready yet', () => {
    expect(deriveBackendPhase(q(s({ running: true, phase: 'running', desired_running: true, django_ready: false })), null)).toBe('booting');
  });

  it('starting / stopping from the backend phase', () => {
    expect(deriveBackendPhase(q(s({ phase: 'starting', desired_running: true })), null)).toBe('starting');
    expect(deriveBackendPhase(q(s({ phase: 'stopping' })), null)).toBe('stopping');
  });

  it('starting / stopping from the local click until the backend catches up', () => {
    expect(deriveBackendPhase(q(s({})), 'starting')).toBe('starting');
    expect(deriveBackendPhase(q(s({ running: true, phase: 'running' })), 'starting')).toBe('running');
    expect(deriveBackendPhase(q(s({ running: true, phase: 'running' })), 'stopping')).toBe('stopping');
    expect(deriveBackendPhase(q(s({})), 'stopping')).toBe('stopped');
  });

  it('error when stopped with a reported problem', () => {
    expect(deriveBackendPhase(q(s({ last_error: 'port in use' })), null)).toBe('error');
    expect(deriveBackendPhase(q(s({ environment: { error: 'bad .env' } })), null)).toBe('error');
    expect(deriveBackendPhase(q(s({ database: { error: 'pg down' } })), null)).toBe('error');
  });

  it('stopped otherwise; tolerates missing phase field', () => {
    expect(deriveBackendPhase(q(s({})), null)).toBe('stopped');
    expect(deriveBackendPhase(q({ running: true }), null)).toBe('running');
    expect(deriveBackendPhase(q({ running: false }), null)).toBe('stopped');
  });
});

describe('power button + helpers', () => {
  it('only running (stop) and stopped/error (start) are actionable', () => {
    expect(powerAction('running')).toBe('stop');
    expect(powerAction('stopped')).toBe('start');
    expect(powerAction('error')).toBe('start');
    for (const p of ['connecting', 'unreachable', 'booting', 'starting', 'stopping'] as const) {
      expect(powerAction(p)).toBeNull();
    }
  });

  it('transitional phases poll fast', () => {
    expect(isTransitional('booting')).toBe(true);
    expect(isTransitional('running')).toBe(false);
  });

  it('serverProblem prefers environment, then database, then last_error', () => {
    expect(serverProblem(undefined)).toBe('');
    expect(serverProblem(s({ last_error: 'c', database: { error: 'b' }, environment: { error: 'a' } }))).toBe('a');
    expect(serverProblem(s({ last_error: 'c', database: { error: 'b' } }))).toBe('b');
    expect(serverProblem(s({ last_error: 'c' }))).toBe('c');
  });
});
