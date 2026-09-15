import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import en from '../../src/i18n/en';
import ru from '../../src/i18n/ru';
import uz from '../../src/i18n/uz';
import { translate } from '../../src/i18n';

const SRC = path.resolve(__dirname, '../../src');

function sourceFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((d) => {
    const full = path.join(dir, d.name);
    if (d.isDirectory()) return d.name === 'i18n' ? [] : sourceFiles(full);
    return /\.(tsx?|mjs)$/.test(d.name) ? [full] : [];
  });
}

const code = sourceFiles(SRC).map((f) => fs.readFileSync(f, 'utf8')).join('\n');
const keys = Object.keys(en);

describe('i18n catalogues', () => {
  it('uz and ru define exactly the en keys with non-empty strings', () => {
    for (const dict of [uz, ru]) {
      expect(Object.keys(dict).sort()).toEqual([...keys].sort());
      for (const k of keys) expect((dict as Record<string, string>)[k].trim()).not.toBe('');
    }
  });

  it('keeps interpolation placeholders consistent across languages', () => {
    const vars = (s: string) => (s.match(/\{\w+\}/g) || []).sort().join(',');
    for (const k of keys) {
      const expected = vars((en as Record<string, string>)[k]);
      expect(vars((uz as Record<string, string>)[k]), `uz ${k}`).toBe(expected);
      expect(vars((ru as Record<string, string>)[k]), `ru ${k}`).toBe(expected);
    }
  });

  it('has no unused keys', () => {
    const unused = keys.filter((k) => !code.includes(`'${k}'`) && !code.includes(`"${k}"`));
    expect(unused).toEqual([]);
  });

  it('references no undefined keys', () => {
    const referenced = new Set<string>();
    for (const m of code.matchAll(/\bt\(\s*['"]([\w.]+)['"]/g)) referenced.add(m[1]);
    for (const m of code.matchAll(/['"]((?:nav|common|dash|obs|lic|audit|cfg|tests|fis|upd|log|sync|la|chip|phase|theme|session|time)\.[A-Za-z0-9]+)['"]/g)) referenced.add(m[1]);
    const missing = [...referenced].filter((k) => !(k in en));
    expect(missing).toEqual([]);
  });

  it('interpolates {n} and falls back to en', () => {
    expect(translate(uz, 'tests.retryDone', { n: 3 })).toContain('3');
    expect(translate({ ...uz, 'common.copy': undefined as unknown as string }, 'common.copy')).toBe(en['common.copy']);
    expect(translate(en, 'time.minAgo', { n: 5 })).toBe('5 min ago');
  });
});
