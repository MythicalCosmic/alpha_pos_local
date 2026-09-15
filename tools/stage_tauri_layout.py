"""Stage the Tauri install layout as a folder for the 1.0.x tufup bridge release.

    python tools/stage_tauri_layout.py \
        --shell desktop-shell/target/x86_64-pc-windows-msvc/release/AlphaPOS.exe \
        --backend dist/AlphaPOSBackend \
        --guard desktop-shell/target/x86_64-pc-windows-msvc/release/alphapos-update-guard.exe \
        --out dist/tauri-layout

The 1.0.x updater swaps the whole install folder for the published bundle and
launches <install>\\AlphaPOS.exe. Publishing this folder with
``tools/release.py --publish --bundle dist/tauri-layout`` therefore installs the
Tauri shell with the old updater's own rollback intact. The folder must match
what the NSIS installer puts on disk, so a manifest of relative paths and
SHA-256 hashes is written next to (not inside) the layout for comparison.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SHELL_NAME = 'AlphaPOS.exe'
BACKEND_DIR = 'backend'
BACKEND_EXE = 'AlphaPOSBackend.exe'
GUARD_PATH = Path('bin') / 'alphapos-update-guard.exe'
VERSION_NAME = 'version.txt'


def file_manifest(folder: Path) -> dict[str, str]:
    """Relative POSIX path -> sha256 for every file under ``folder``."""
    manifest = {}
    for path in sorted(p for p in folder.rglob('*') if p.is_file()):
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b''):
                digest.update(chunk)
        manifest[path.relative_to(folder).as_posix()] = digest.hexdigest()
    return manifest


def stage(*, shell: Path, backend: Path, guard: Path, out: Path, version: str, force: bool = False) -> dict:
    if not shell.is_file():
        raise SystemExit(f'shell executable not found: {shell}')
    if not (backend / BACKEND_EXE).is_file():
        raise SystemExit(f'backend onedir not found (missing {BACKEND_EXE}): {backend}')
    if not guard.is_file():
        raise SystemExit(f'update guard executable not found: {guard}')
    if out.exists() and any(out.iterdir()):
        if not force:
            raise SystemExit(f'{out} is not empty; pass --force to replace it')
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    shutil.copy2(shell, out / SHELL_NAME)
    shutil.copytree(backend, out / BACKEND_DIR)
    (out / GUARD_PATH).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(guard, out / GUARD_PATH)
    (out / VERSION_NAME).write_text(version + '\n', encoding='utf-8')

    manifest = {'version': version, 'files': file_manifest(out)}
    manifest_path = out.parent / f'{out.name}-manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--shell', type=Path, required=True)
    parser.add_argument('--backend', type=Path, required=True)
    parser.add_argument('--guard', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=ROOT / 'dist' / 'tauri-layout')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args(argv)

    from desktop.version import __version__
    from tools import sync_version

    if sync_version.main(['--check']) != 0:
        raise SystemExit('desktop shell version drift; run tools/sync_version.py first')
    manifest = stage(shell=args.shell, backend=args.backend, guard=args.guard, out=args.out, version=__version__, force=args.force)
    print(f"staged {len(manifest['files'])} files for {__version__} into {args.out}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
