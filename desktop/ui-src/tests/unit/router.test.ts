// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { createRouter, hasUnsavedChanges, parseHash, registerGuard, router, type Router } from '../../src/router/router';

describe('parseHash', () => {
  it('maps known routes and falls back to dashboard', () => {
    expect(parseHash('#/config')).toBe('config');
    expect(parseHash('#/local-audit')).toBe('local-audit');
    expect(parseHash('#config')).toBe('config');
    expect(parseHash('#/logs?x=1')).toBe('logs');
    expect(parseHash('')).toBe('dashboard');
    expect(parseHash('#/nope')).toBe('dashboard');
  });
});

describe('hash router + unsaved guard', () => {
  let r: Router;
  let dirty = false;
  let release: () => void;

  beforeEach(() => {
    window.history.replaceState(null, '', '#/config');
    dirty = false;
    release = registerGuard(() => dirty);
    r = createRouter(window);
  });

  afterEach(() => {
    release();
    r.destroy();
  });

  it('navigates freely when nothing is dirty', () => {
    expect(r.getState().route).toBe('config');
    expect(r.navigate('logs')).toBe(true);
    expect(r.getState()).toEqual({ route: 'logs', pending: null });
    expect(window.location.hash).toBe('#/logs');
  });

  it('holds navigation while dirty until the user decides', () => {
    dirty = true;
    expect(hasUnsavedChanges()).toBe(true);
    expect(r.navigate('tests')).toBe(false);
    expect(r.getState()).toEqual({ route: 'config', pending: 'tests' });
    r.cancelPending();
    expect(r.getState()).toEqual({ route: 'config', pending: null });
    r.navigate('tests');
    r.confirmPending();
    expect(r.getState()).toEqual({ route: 'tests', pending: null });
    expect(window.location.hash).toBe('#/tests');
  });

  it('reverts a manual hash change while dirty', () => {
    dirty = true;
    window.location.hash = '#/fiscal';
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    expect(r.getState()).toEqual({ route: 'config', pending: 'fiscal' });
    expect(window.location.hash).toBe('#/config');
  });

  it('follows a manual hash change when clean', () => {
    window.location.hash = '#/updates';
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    expect(r.getState().route).toBe('updates');
  });

  it('notifies subscribers', () => {
    const seen: string[] = [];
    const off = r.subscribe((s) => seen.push(s.route));
    r.navigate('license');
    off();
    r.navigate('logs');
    expect(seen).toEqual(['license']);
  });

  it('exposes window.__alphaHasUnsavedChanges', () => {
    router();
    expect(typeof window.__alphaHasUnsavedChanges).toBe('function');
    expect(window.__alphaHasUnsavedChanges!()).toBe(false);
    dirty = true;
    expect(window.__alphaHasUnsavedChanges!()).toBe(true);
  });

  it('normalizes unknown hashes on creation', () => {
    r.destroy();
    window.history.replaceState(null, '', '#/whatever');
    r = createRouter(window);
    expect(r.getState().route).toBe('dashboard');
    expect(window.location.hash).toBe('#/dashboard');
  });
});
