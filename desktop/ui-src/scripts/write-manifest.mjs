// Writes desktop/ui/build-manifest.json after `vite build`:
//  - source_sha256 over sorted src/** + index.html, vite.config.ts,
//    package-lock.json, tsconfig.json (CRLF-normalized; relative POSIX paths),
//    recomputed by tests/desktop/test_runtime_reliability.py to prove the
//    committed output matches the committed sources;
//  - every output file with its size;
//  - entry assets, page/locale chunks and the static import graph (budgets).
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outDir = path.resolve(root, '../ui');
const ROOT_INPUTS = ['index.html', 'vite.config.ts', 'package-lock.json', 'tsconfig.json'];

function walk(dir, base = dir) {
  const out = [];
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name);
    if (fs.statSync(full).isDirectory()) out.push(...walk(full, base));
    else out.push(path.relative(base, full).split(path.sep).join('/'));
  }
  return out;
}

export function sourceDigest() {
  const inputs = [...walk(path.join(root, 'src')).map((p) => `src/${p}`), ...ROOT_INPUTS].sort();
  const hash = crypto.createHash('sha256');
  for (const rel of inputs) {
    const text = fs.readFileSync(path.join(root, rel), 'utf8').replace(/^﻿/, '').replace(/\r\n?/g, '\n');
    hash.update(rel, 'utf8');
    hash.update('\0');
    hash.update(text, 'utf8');
    hash.update('\0');
  }
  return { sha: hash.digest('hex'), inputs };
}

function main() {
  const viteManifestPath = path.join(outDir, '.vite', 'manifest.json');
  const vite = JSON.parse(fs.readFileSync(viteManifestPath, 'utf8'));
  const entryKey = Object.keys(vite).find((k) => vite[k].isEntry);
  if (!entryKey) throw new Error('no entry in vite manifest');
  const entry = vite[entryKey];

  const graph = {};
  const pages = {};
  const locales = {};
  for (const [key, chunk] of Object.entries(vite)) {
    if (!chunk.file.endsWith('.js')) continue;
    graph[chunk.file] = {
      imports: (chunk.imports || []).map((k) => vite[k].file),
      css: chunk.css || [],
    };
    const page = /^src\/pages\/(\w+)\.tsx$/.exec(key);
    if (page) pages[page[1]] = chunk.file;
    const locale = /^src\/i18n\/(uz|ru)\.ts$/.exec(key);
    if (locale) locales[locale[1]] = chunk.file;
  }

  fs.rmSync(path.join(outDir, '.vite'), { recursive: true, force: true });
  const files = walk(outDir)
    .filter((p) => p !== 'build-manifest.json')
    .sort()
    .map((p) => ({ path: p, size: fs.statSync(path.join(outDir, p)).size }));

  const { sha, inputs } = sourceDigest();
  const manifest = {
    schema: 1,
    generator: 'desktop/ui-src/scripts/write-manifest.mjs',
    source_sha256: sha,
    source_count: inputs.length,
    entry: { html: 'index.html', js: entry.file, css: entry.css || [], imports: (entry.imports || []).map((k) => vite[k].file) },
    pages,
    locales,
    graph,
    files,
  };
  fs.writeFileSync(path.join(outDir, 'build-manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
  console.log(`build-manifest.json: ${files.length} files, source ${sha.slice(0, 12)}…`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
