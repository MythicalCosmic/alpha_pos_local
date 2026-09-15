// Enforces the control-panel size budgets against desktop/ui/build-manifest.json.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outDir = path.resolve(root, '../ui');

export const BUDGETS = {
  initialJs: 70_000,
  initialCss: 25_000,
  pageChunk: 30_000,
  localeChunk: 20_000,
  totalJs: 150_000,
  totalNonPng: 400_000,
  singleFile: 100_000,
};

export function measure(manifest) {
  const size = (file) => fs.statSync(path.join(outDir, file)).size;
  const closure = (start) => {
    const seen = new Set();
    const visit = (file) => {
      if (seen.has(file)) return;
      seen.add(file);
      for (const dep of manifest.graph[file]?.imports || []) visit(dep);
    };
    visit(start);
    return seen;
  };
  const initial = new Set([...closure(manifest.entry.js), ...closure(manifest.pages.Dashboard)]);
  const initialCss = new Set(manifest.entry.css);
  for (const file of initial) for (const css of manifest.graph[file]?.css || []) initialCss.add(css);
  const sum = (files) => [...files].reduce((n, f) => n + size(f), 0);
  const jsFiles = manifest.files.filter((f) => f.path.endsWith('.js'));
  return {
    initialJs: sum(initial),
    initialCss: sum(initialCss),
    pages: Object.fromEntries(Object.entries(manifest.pages).map(([k, f]) => [k, size(f)])),
    locales: Object.fromEntries(Object.entries(manifest.locales).map(([k, f]) => [k, size(f)])),
    totalJs: jsFiles.reduce((n, f) => n + f.size, 0),
    totalNonPng: manifest.files.filter((f) => !f.path.endsWith('.png')).reduce((n, f) => n + f.size, 0),
    largest: manifest.files.reduce((a, f) => (f.size > a.size ? f : a), { path: '', size: 0 }),
    fonts: manifest.files.filter((f) => /\.(woff2?|ttf|otf|eot)$/i.test(f.path)).map((f) => f.path),
  };
}

function main() {
  const manifest = JSON.parse(fs.readFileSync(path.join(outDir, 'build-manifest.json'), 'utf8'));
  const m = measure(manifest);
  const failures = [];
  const check = (label, value, limit) => {
    const ok = value <= limit;
    console.log(`${ok ? 'ok  ' : 'FAIL'} ${label.padEnd(28)} ${String(value).padStart(7)} / ${limit}`);
    if (!ok) failures.push(label);
  };
  check('initial JS', m.initialJs, BUDGETS.initialJs);
  check('initial CSS', m.initialCss, BUDGETS.initialCss);
  for (const [name, bytes] of Object.entries(m.pages)) check(`page ${name}`, bytes, BUDGETS.pageChunk);
  for (const [name, bytes] of Object.entries(m.locales)) check(`locale ${name}`, bytes, BUDGETS.localeChunk);
  check('total JS', m.totalJs, BUDGETS.totalJs);
  check('output excl. PNG', m.totalNonPng, BUDGETS.totalNonPng);
  check(`largest (${m.largest.path})`, m.largest.size, BUDGETS.singleFile);
  check('font files', m.fonts.length, 0);
  if (failures.length) {
    console.error(`Budget violations: ${failures.join(', ')}`);
    process.exit(1);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
