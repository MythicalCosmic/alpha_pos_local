import { useEffect, useRef, useState } from 'preact/hooks';

export const ROUTE_IDS = ['dashboard', 'license', 'local-audit', 'config', 'tests', 'fiscal', 'logs', 'updates'] as const;
export type RouteId = (typeof ROUTE_IDS)[number];

export function parseHash(hash: string): RouteId {
  const id = String(hash || '').replace(/^#\/?/, '').split(/[/?#]/)[0];
  return (ROUTE_IDS as readonly string[]).includes(id) ? (id as RouteId) : 'dashboard';
}

export const hrefFor = (id: RouteId) => `#/${id}`;

/* ---------- unsaved-changes guards ---------- */
const guards = new Set<() => boolean>();

export function hasUnsavedChanges(): boolean {
  for (const guard of guards) if (guard()) return true;
  return false;
}

export function registerGuard(guard: () => boolean): () => void {
  guards.add(guard);
  return () => { guards.delete(guard); };
}

/** Block navigation (and let the shell ask) while `dirty` is true. */
export function useUnsavedGuard(dirty: boolean): void {
  const ref = useRef(dirty);
  ref.current = dirty;
  useEffect(() => registerGuard(() => ref.current), []);
}

/* ---------- hash router ---------- */
export interface RouterState {
  route: RouteId;
  /** Navigation blocked by an unsaved-changes guard, awaiting a decision. */
  pending: RouteId | null;
}

type Listener = (state: RouterState) => void;

export interface Router {
  getState(): RouterState;
  navigate(id: RouteId): boolean;
  confirmPending(): void;
  cancelPending(): void;
  subscribe(listener: Listener): () => void;
  destroy(): void;
}

export function createRouter(win: Window): Router {
  let state: RouterState = { route: parseHash(win.location.hash), pending: null };
  const listeners = new Set<Listener>();
  const set = (next: RouterState) => {
    state = next;
    listeners.forEach((fn) => fn(state));
  };
  const writeHash = (id: RouteId, replace: boolean) => {
    const url = hrefFor(id);
    if (win.location.hash === url) return;
    if (replace) win.history.replaceState(null, '', url);
    else win.history.pushState(null, '', url);
  };
  if (win.location.hash !== hrefFor(state.route)) writeHash(state.route, true);

  const commit = (id: RouteId, replace = false) => {
    writeHash(id, replace);
    set({ route: id, pending: null });
  };

  const onHashChange = () => {
    const next = parseHash(win.location.hash);
    if (next === state.route) {
      if (win.location.hash !== hrefFor(next)) writeHash(next, true);
      return;
    }
    if (hasUnsavedChanges()) {
      writeHash(state.route, true);
      set({ ...state, pending: next });
      return;
    }
    commit(next, true);
  };
  win.addEventListener('hashchange', onHashChange);

  return {
    getState: () => state,
    navigate(id) {
      if (id === state.route) return true;
      if (hasUnsavedChanges()) {
        set({ ...state, pending: id });
        return false;
      }
      commit(id);
      return true;
    },
    confirmPending() {
      if (state.pending) commit(state.pending);
    },
    cancelPending() {
      if (state.pending) set({ ...state, pending: null });
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    destroy() {
      win.removeEventListener('hashchange', onHashChange);
      listeners.clear();
    },
  };
}

let singleton: Router | null = null;

export function router(): Router {
  if (!singleton) {
    singleton = createRouter(window);
    window.__alphaHasUnsavedChanges = hasUnsavedChanges;
  }
  return singleton;
}

export function useRouter(): RouterState {
  const r = router();
  const [state, setState] = useState(r.getState());
  useEffect(() => r.subscribe(setState), [r]);
  return state;
}

export function navigate(id: RouteId): boolean {
  return router().navigate(id);
}
