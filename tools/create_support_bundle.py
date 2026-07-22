"""Create a per-install, untracked support configuration bundle.

The private SSH key and optional Telegram token are read at runtime and never
printed. The resulting JSON is intentionally ignored by git and should be
handled like a password: import it only on the intended till, then archive it
in the owner's private storage.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tempfile
from pathlib import Path


def _host_entry(host: str, public_key_file: Path) -> str:
    parts = public_key_file.read_text(encoding='utf-8').strip().split()
    if len(parts) < 2 or not parts[0].startswith('ssh-'):
        raise SystemExit('host public key file is invalid')
    return f'{host} {parts[0]} {parts[1]}'


def _protect_output(path: Path) -> None:
    """Apply the same fail-closed DACL used for the extracted SSH key."""
    try:
        os.chmod(path, 0o600)
        if os.name == 'nt':
            root = Path(__file__).resolve().parents[1]
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from desktop.support_tunnel import _harden_windows_private_key
            # The owner needs to rotate this bundle later. Full control for the
            # current SID remains private while allowing atomic replace/delete.
            _harden_windows_private_key(path, rights='F')
    except Exception as exc:  # noqa: BLE001
        path.unlink(missing_ok=True)
        raise SystemExit(
            'could not protect support bundle; insecure copy was removed'
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--private-key', required=True, type=Path)
    parser.add_argument('--host-public-key', required=True, type=Path)
    parser.add_argument('--relay-host', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--relay-user', default='alphapos-support')
    parser.add_argument('--audit-chat-ids', default='')
    parser.add_argument('--telegram-token-env', default='')
    parser.add_argument('--remote-db-port', default='15433')
    parser.add_argument('--remote-api-port', default='18000')
    args = parser.parse_args()

    private_key = args.private_key.read_bytes()
    if b'PRIVATE KEY' not in private_key:
        raise SystemExit('private key file is invalid')
    config = {
        'SUPPORT_TUNNEL_ENABLED': 'True',
        'SUPPORT_TUNNEL_HOST': args.relay_host,
        'SUPPORT_TUNNEL_PORT': '22',
        'SUPPORT_TUNNEL_USER': args.relay_user,
        'SUPPORT_TUNNEL_REMOTE_DB_PORT': args.remote_db_port,
        'SUPPORT_TUNNEL_REMOTE_API_PORT': args.remote_api_port,
        'SUPPORT_TUNNEL_PRIVATE_KEY_B64': base64.b64encode(private_key).decode(),
        'SUPPORT_TUNNEL_KNOWN_HOST': _host_entry(
            args.relay_host, args.host_public_key,
        ),
        'ORDER_AUDIT_TELEGRAM_CHAT_IDS': args.audit_chat_ids,
    }
    if args.telegram_token_env:
        token = str(os.environ.get(args.telegram_token_env) or '').strip()
        if token:
            config['TELEGRAM_BOT_TOKEN'] = token

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps({'config': config}, indent=2, sort_keys=True) + '\n'
    fd, tmp_name = tempfile.mkstemp(
        prefix=f'.{args.output.name}.', suffix='.tmp', dir=str(args.output.parent),
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        _protect_output(tmp)
        if args.output.exists() and os.name == 'nt':
            from desktop.support_tunnel import _harden_windows_private_key
            _harden_windows_private_key(args.output, rights='F')
        os.replace(tmp, args.output)
    except Exception:
        if tmp.exists() and os.name == 'nt':
            try:
                from desktop.support_tunnel import _harden_windows_private_key
                _harden_windows_private_key(tmp, rights='F')
            except Exception:  # noqa: BLE001
                pass
        tmp.unlink(missing_ok=True)
        raise
    print(f'created protected support bundle: {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
