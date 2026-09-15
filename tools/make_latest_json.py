"""Write the Tauri updater manifest (latest.json) for a signed NSIS installer.

    python tools/make_latest_json.py \
        --installer "desktop-shell/target/x86_64-pc-windows-msvc/release/bundle/nsis/Alpha POS_1.1.1_x64-setup.exe" \
        --base-url https://control.78.111.91.113.nip.io/updates/installers/ \
        --notes "Faster startup" --out dist/latest.json

The installer is published under a space-free name (AlphaPOS_<version>_x64-setup.exe)
and its minisign signature (the installer's .sig file) is embedded verbatim.
The version defaults to desktop/version.py and must match the installer name.
Publish order on the server: installer, then .sig, then latest.json last.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PLATFORM = 'windows-x86_64'
_SEMVER = re.compile(r'\d+\.\d+\.\d+')


def published_name(version: str) -> str:
    return f'AlphaPOS_{version}_x64-setup.exe'


def build_manifest(*, version: str, signature: str, base_url: str, notes: str = '', pub_date: datetime | None = None) -> dict:
    if not _SEMVER.fullmatch(version):
        raise SystemExit(f'version must be x.y.z, got {version!r}')
    signature = signature.strip()
    if not signature:
        raise SystemExit('signature is empty')
    if not base_url.startswith('https://'):
        raise SystemExit('base URL must be https')
    base = base_url if base_url.endswith('/') else base_url + '/'
    when = (pub_date or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    return {
        'version': version,
        'notes': notes,
        'pub_date': when.isoformat().replace('+00:00', 'Z'),
        'platforms': {
            PLATFORM: {
                'signature': signature,
                'url': base + quote(published_name(version)),
            },
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--signature', type=Path, help='defaults to <installer>.sig')
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--version')
    parser.add_argument('--notes', default='')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)

    if args.version:
        version = args.version
    else:
        from desktop.version import __version__ as version
    if not args.installer.is_file():
        raise SystemExit(f'installer not found: {args.installer}')
    if f'_{version}_' not in args.installer.name:
        raise SystemExit(f'installer name {args.installer.name!r} does not carry version {version}')
    signature_path = args.signature or args.installer.with_name(args.installer.name + '.sig')
    if not signature_path.is_file():
        raise SystemExit(f'signature not found: {signature_path}')

    manifest = build_manifest(
        version=version,
        signature=signature_path.read_text(encoding='utf-8'),
        base_url=args.base_url,
        notes=args.notes,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(f'wrote {args.out} for {version} -> {manifest["platforms"][PLATFORM]["url"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
