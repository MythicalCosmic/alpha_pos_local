"""Propagate desktop/version.py into the Tauri shell's manifests.

    python tools/sync_version.py          # rewrite versions in place
    python tools/sync_version.py --check  # exit 1 if anything is out of sync

desktop/version.py stays the single source of truth. The shell's workspace
version (Cargo) and tauri.conf.json must match it, because the updater compares
the running shell version with latest.json and the old tufup helper confirms
the bridge release by exact version string.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / 'desktop' / 'version.py'
CARGO_TOML = ROOT / 'desktop-shell' / 'Cargo.toml'
TAURI_CONF = ROOT / 'desktop-shell' / 'src-tauri' / 'tauri.conf.json'

_SEMVER = re.compile(r'\d+\.\d+\.\d+')
_WORKSPACE_VERSION = re.compile(
    r'(\[workspace\.package\][^\[]*?^version\s*=\s*")([^"]+)(")',
    re.MULTILINE | re.DOTALL,
)


def source_version(version_file: Path = VERSION_FILE) -> str:
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', version_file.read_text(encoding='utf-8'), re.MULTILINE)
    if not match or not _SEMVER.fullmatch(match.group(1)):
        raise SystemExit(f'{version_file}: __version__ must be x.y.z')
    return match.group(1)


def cargo_version(text: str) -> str | None:
    match = _WORKSPACE_VERSION.search(text)
    return match.group(2) if match else None


def with_cargo_version(text: str, version: str) -> str:
    if not _WORKSPACE_VERSION.search(text):
        raise SystemExit(f'{CARGO_TOML}: [workspace.package] version not found')
    return _WORKSPACE_VERSION.sub(lambda m: f'{m.group(1)}{version}{m.group(3)}', text, count=1)


def with_tauri_version(text: str, version: str) -> str:
    # Rewrite only the top-level "version" value to keep formatting intact.
    config = json.loads(text)
    if config.get('version') == version:
        return text
    updated, count = re.subn(r'^(\s{2}"version":\s*")([^"]*)(")', lambda m: f'{m.group(1)}{version}{m.group(3)}', text, count=1, flags=re.MULTILINE)
    if count != 1 or json.loads(updated).get('version') != version:
        raise SystemExit(f'{TAURI_CONF}: top-level "version" not found')
    return updated


def main(argv=None, *, version_file=VERSION_FILE, cargo_toml=CARGO_TOML, tauri_conf=TAURI_CONF) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true', help='report drift without writing')
    args = parser.parse_args(argv)

    version = source_version(version_file)
    cargo_text = cargo_toml.read_text(encoding='utf-8')
    tauri_text = tauri_conf.read_text(encoding='utf-8')
    drift = []
    if cargo_version(cargo_text) != version:
        drift.append(f'{cargo_toml.name}: {cargo_version(cargo_text)}')
    if json.loads(tauri_text).get('version') != version:
        drift.append(f'{tauri_conf.name}: {json.loads(tauri_text).get("version")}')

    if args.check:
        if drift:
            print(f'version drift from desktop/version.py ({version}): ' + ', '.join(drift))
            return 1
        print(f'desktop shell versions match {version}')
        return 0

    if drift:
        cargo_toml.write_text(with_cargo_version(cargo_text, version), encoding='utf-8')
        tauri_conf.write_text(with_tauri_version(tauri_text, version), encoding='utf-8')
        print(f'synced desktop shell to {version} ({", ".join(drift)})')
    else:
        print(f'desktop shell already at {version}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
