"""Validate and stage an ignored private-support payload without printing it."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop.private_release import canonical_payload_bytes  # noqa: E402
from desktop.support_tunnel import _harden_windows_private_key  # noqa: E402


def stage(source: Path, destination: Path | None = None) -> int:
    source = Path(source)
    raw = source.read_bytes()
    canonical = canonical_payload_bytes(raw)
    if destination is not None:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            _harden_windows_private_key(destination.parent, rights='F')
        destination.write_bytes(canonical)
        try:
            destination.chmod(0o600)
        except OSError:
            pass
        # Owner-only FullControl is still private and lets the build's guarded
        # finally block delete the plaintext reliably after Inno closes it.
        _harden_windows_private_key(destination, rights='F')
    return len(canonical)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if not args.check and args.output is None:
        parser.error('--output is required unless --check is used')
    stage(args.input, None if args.check else args.output)
    print(
        'Private support payload validated.'
        if args.check
        else 'Private support payload staged in the ignored build directory.'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
