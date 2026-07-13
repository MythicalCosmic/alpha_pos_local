#!/usr/bin/env node
/*
 * Deterministically precompile the desktop panel's JSX with the vendored Babel.
 * No npm install or network access is required.
 *
 *   node tools/compile_desktop_ui.js          # write desktop/ui/app.bundle.js
 *   node tools/compile_desktop_ui.js --check  # fail if the committed bundle is stale
 */
'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const uiDir = path.join(root, 'desktop', 'ui');
const outputPath = path.join(uiDir, 'app.bundle.js');
const babel = require(path.join(uiDir, 'vendor', 'babel.min.js'));

// This order is the dependency order formerly expressed by index.html's script
// tags. Keep bridge/i18n first and the React entrypoint last.
const inputs = [
  'app/bridge.js',
  'app/i18n.js',
  'app/ui.jsx',
  'app/screens-main.jsx',
  'app/screens-admin.jsx',
  'app/screens-ops.jsx',
  'app/screens-updates.jsx',
  'app/screens-logs.jsx',
  'app/main.jsx',
];

function normalizedSource(relative) {
  return fs.readFileSync(path.join(uiDir, relative), 'utf8')
    .replace(/^\uFEFF/, '')
    .replace(/\r\n?/g, '\n');
}

function buildBundle() {
  const sources = inputs.map((relative) => [relative, normalizedSource(relative)]);
  const hash = crypto.createHash('sha256');
  for (const [relative, source] of sources) {
    hash.update(relative, 'utf8');
    hash.update('\0');
    hash.update(source, 'utf8');
    hash.update('\0');
  }
  const fingerprint = hash.digest('hex');

  const chunks = sources.map(([relative, source]) => {
    const code = relative.endsWith('.jsx')
      ? babel.transform(source, {
          ast: false,
          babelrc: false,
          comments: false,
          compact: false,
          filename: relative,
          presets: ['react'],
          sourceMaps: false,
          sourceType: 'script',
        }).code
      : source.trimEnd();
    return `\n/* source: ${relative} */\n${code}\n`;
  });

  return [
    '/* AlphaPOS desktop UI — generated; do not edit directly.\n',
    ' * Run: node tools/compile_desktop_ui.js\n',
    ` * source-sha256: ${fingerprint}\n`,
    ' */\n',
    '(function () {\n',
    "'use strict';\n",
    ...chunks,
    '})();\n',
  ].join('');
}

const expected = buildBundle();
if (process.argv.includes('--check')) {
  const current = fs.existsSync(outputPath)
    ? fs.readFileSync(outputPath, 'utf8').replace(/\r\n?/g, '\n')
    : '';
  if (current !== expected) {
    process.stderr.write(
      'desktop/ui/app.bundle.js is stale; run node tools/compile_desktop_ui.js\n',
    );
    process.exit(1);
  }
  process.stdout.write('desktop UI bundle is current\n');
} else {
  fs.writeFileSync(outputPath, expected, 'utf8');
  process.stdout.write(`wrote ${path.relative(root, outputPath)} (${expected.length} bytes)\n`);
}

