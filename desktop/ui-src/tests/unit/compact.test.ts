import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { buildKeyMap, compactKeys, extractKeys, shortId } from '../../src/i18n/compact';
import en from '../../src/i18n/en';

const EN_SOURCE = fs.readFileSync(path.resolve(__dirname, '../../src/i18n/en.ts'), 'utf8');

describe('build-time i18n key compaction', () => {
  it('extracts exactly the en keys in declaration order', () => {
    expect(extractKeys(EN_SOURCE)).toEqual(Object.keys(en));
  });

  it('produces unique, non-integer short ids', () => {
    const ids = Array.from({ length: 1000 }, (_, i) => shortId(i));
    expect(new Set(ids).size).toBe(1000);
    for (const id of ids) expect(/^[a-z][0-9a-z]*$/.test(id)).toBe(true);
  });

  it('rewrites only exact key literals', () => {
    const map = buildKeyMap(EN_SOURCE);
    const idCopy = map.get('common.copy')!;
    const code = `t('common.copy'); t("common.copy"); x = 'common.copyX'; y = 'index.html'; z = \`common.copy\`;`;
    expect(compactKeys(code, map)).toBe(`t('${idCopy}'); t("${idCopy}"); x = 'common.copyX'; y = 'index.html'; z = \`common.copy\`;`);
  });

  it('keeps every locale lookup consistent after compaction', () => {
    const map = buildKeyMap(EN_SOURCE);
    for (const lang of ['uz', 'ru']) {
      const src = fs.readFileSync(path.resolve(__dirname, `../../src/i18n/${lang}.ts`), 'utf8');
      const compacted = compactKeys(src, map);
      for (const key of Object.keys(en)) {
        expect(compacted.includes(`"${key}"`), `${lang} still has ${key}`).toBe(false);
        expect(compacted.includes(`"${map.get(key)}":`), `${lang} ${key}`).toBe(true);
      }
    }
  });
});
