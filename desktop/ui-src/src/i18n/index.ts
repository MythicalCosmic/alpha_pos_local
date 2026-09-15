import { createContext } from 'preact';
import { useContext } from 'preact/hooks';
import en from './en';

export type I18nKey = keyof typeof en;
export type Lang = 'en' | 'uz' | 'ru';
export type Dict = Record<I18nKey, string>;
export type Vars = Record<string, string | number>;
export type TFunction = (key: I18nKey, vars?: Vars) => string;

export const LANGS: readonly Lang[] = ['en', 'uz', 'ru'];

export function isLang(value: unknown): value is Lang {
  return value === 'en' || value === 'uz' || value === 'ru';
}

export function translate(dict: Dict, key: I18nKey, vars?: Vars): string {
  let text: string = dict[key] ?? en[key] ?? key;
  if (vars) {
    text = text.replace(/\{(\w+)\}/g, (match, name: string) => (name in vars ? String(vars[name]) : match));
  }
  return text;
}

const cache: Partial<Record<Lang, Dict>> = { en };

/** en ships in the entry chunk; uz / ru are separate lazy chunks. */
export async function loadDict(lang: Lang): Promise<Dict> {
  const hit = cache[lang];
  if (hit) return hit;
  const mod = lang === 'uz' ? await import('./uz') : await import('./ru');
  cache[lang] = mod.default;
  return mod.default;
}

export function makeT(dict: Dict): TFunction {
  return (key, vars) => translate(dict, key, vars);
}

export interface I18nValue {
  lang: Lang;
  t: TFunction;
}

export const I18nContext = createContext<I18nValue>({ lang: 'en', t: makeT(en) });

export function useI18n(): I18nValue {
  return useContext(I18nContext);
}

export function useT(): TFunction {
  return useContext(I18nContext).t;
}
