import { isLang, type Lang } from '../i18n';

export type Theme = 'light' | 'dark' | 'system';

export interface Prefs {
  theme: Theme;
  lang: Lang;
}

export const PREFS_KEY = 'alphapos.panel.prefs';
export const DEFAULT_PREFS: Prefs = { theme: 'system', lang: 'en' };

function isTheme(value: unknown): value is Theme {
  return value === 'light' || value === 'dark' || value === 'system';
}

/** Map persisted desktop_state.json `ui` prefs (incl. legacy `dir`) onto the new model. */
export function migratePrefs(raw: Record<string, unknown> | null | undefined): Partial<Prefs> {
  const out: Partial<Prefs> = {};
  if (!raw || typeof raw !== 'object') return out;
  if (isTheme(raw.theme)) out.theme = raw.theme;
  else if (typeof raw.dir === 'string') {
    const dir = raw.dir.toLowerCase();
    if (dir === 'noir') out.theme = 'dark';
    else if (dir === 'porcelain' || dir === 'atelier') out.theme = 'light';
  }
  const lang = typeof raw.lang === 'string' ? raw.lang.toLowerCase() : raw.lang;
  if (isLang(lang)) out.lang = lang;
  return out;
}

export function readCachedPrefs(storage: Pick<Storage, 'getItem'> | undefined = safeStorage()): Prefs {
  try {
    const raw = storage?.getItem(PREFS_KEY);
    if (raw) return { ...DEFAULT_PREFS, ...migratePrefs(JSON.parse(raw)) };
  } catch {
    /* ignore corrupt cache */
  }
  return { ...DEFAULT_PREFS };
}

export function writeCachedPrefs(prefs: Prefs, storage: Pick<Storage, 'setItem'> | undefined = safeStorage()): void {
  try {
    storage?.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    /* storage may be unavailable */
  }
}

export function applyDocumentPrefs(prefs: Prefs, doc: Document = document): void {
  doc.documentElement.setAttribute('data-theme', prefs.theme);
  doc.documentElement.setAttribute('lang', prefs.lang);
}

function safeStorage(): Storage | undefined {
  try {
    return typeof localStorage === 'undefined' ? undefined : localStorage;
  } catch {
    return undefined;
  }
}
