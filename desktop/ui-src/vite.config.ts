import fs from 'node:fs';
import path from 'node:path';
import { defineConfig, type Plugin } from 'vite';
import { buildKeyMap, compactKeys } from './src/i18n/compact';

const SRC = path.resolve(__dirname, 'src') + path.sep;

/** Rewrites i18n key literals to short ids in the production bundle. */
function i18nCompact(): Plugin {
  let map: Map<string, string> = new Map();
  return {
    name: 'alpha-i18n-compact',
    apply: 'build',
    enforce: 'pre',
    buildStart() {
      map = buildKeyMap(fs.readFileSync(path.join(SRC, 'i18n', 'en.ts'), 'utf8'));
      if (map.size === 0) this.error('no i18n keys found in en.ts');
    },
    transform(code, id) {
      if (!id.startsWith(SRC) || !/\.(tsx?|mjs)$/.test(id) || id.endsWith('compact.ts')) return null;
      const next = compactKeys(code, map);
      return next === code ? null : { code: next, map: null };
    },
  };
}

// Output is committed to ../ui and served by desktop/control_server.py (and
// proxied by the Tauri shell). Relative base so it works from any origin.
export default defineConfig({
  base: './',
  plugins: [i18nCompact()],
  oxc: {
    jsx: { runtime: 'automatic', importSource: 'preact' },
  },
  build: {
    outDir: '../ui',
    emptyOutDir: true,
    target: 'chrome110',
    modulePreload: { polyfill: false },
    sourcemap: false,
    manifest: true,
    cssCodeSplit: true,
    reportCompressedSize: false,
    assetsInlineLimit: 0,
  },
  preview: {
    port: 4173,
    strictPort: true,
    host: '127.0.0.1',
  },
});
