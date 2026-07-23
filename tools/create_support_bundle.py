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
    parser.add_argument('--local-audit-chat-ids', default='')
    parser.add_argument('--local-audit-token-env', default='')
    parser.add_argument(
        '--local-telegram-enabled',
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(
        '--local-order-recorded',
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        '--local-order-paid',
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        '--local-shift-report',
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        '--local-shift-report-format',
        choices=('TXT', 'MD'),
        default='TXT',
    )
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
        'LOCAL_TELEGRAM_AUDIT_ENABLED': str(bool(args.local_telegram_enabled)),
        'LOCAL_TELEGRAM_ORDER_RECORDED_ENABLED': str(
            bool(args.local_order_recorded),
        ),
        'LOCAL_TELEGRAM_ORDER_PAID_ENABLED': str(bool(args.local_order_paid)),
        'LOCAL_TELEGRAM_SHIFT_REPORT_ENABLED': str(
            bool(args.local_shift_report),
        ),
        'LOCAL_TELEGRAM_SHIFT_REPORT_FORMAT': args.local_shift_report_format,
        'LOCAL_TELEGRAM_AUDIT_CHAT_IDS': args.local_audit_chat_ids,
    }
    if args.telegram_token_env:
        token = str(os.environ.get(args.telegram_token_env) or '').strip()
        if token:
            config['TELEGRAM_BOT_TOKEN'] = token
    if args.local_audit_token_env:
        local_token = str(
            os.environ.get(args.local_audit_token_env) or '',
        ).strip()
        if local_token:
            config['LOCAL_TELEGRAM_AUDIT_BOT_TOKEN'] = local_token
    if args.local_telegram_enabled:
        if not args.local_audit_chat_ids.strip():
            raise SystemExit(
                'local Telegram audit is enabled but owner chat IDs are missing',
            )
        if not config.get('LOCAL_TELEGRAM_AUDIT_BOT_TOKEN'):
            raise SystemExit(
                'local Telegram audit is enabled but its token environment '
                'variable is missing or empty',
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps({'config': config}, indent=2, sort_keys=True) + '\n'
    fd, tmp_name = tempfile.mkstemp(
        prefix=f'.{args.output.name}.', suffix='.tmp', dir=str(args.output.parent),
    )
    tmp = Path(tmp_name)
    # The output directory can be broadly inherited (for example a shared
    # Desktop/OneDrive checkout). Close the empty mkstemp handle and establish
    # the owner-only DACL before a private key or Telegram token is ever written.
    os.close(fd)
    try:
        _protect_output(tmp)
        with tmp.open('w', encoding='utf-8', newline='\n') as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        # Re-assert the boundary after writing as defense in depth and to catch
        # any unexpected permission drift before the file becomes visible.
        _protect_output(tmp)
        if args.output.exists() and os.name == 'nt':
            from desktop.support_tunnel import _harden_windows_private_key
            _harden_windows_private_key(args.output, rights='F')
        os.replace(tmp, args.output)
    except BaseException:
        if tmp.exists() and os.name == 'nt':
            try:
                from desktop.support_tunnel import _harden_windows_private_key
                _harden_windows_private_key(tmp, rights='F')
            except Exception:  # noqa: BLE001
                pass
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    print(f'created protected support bundle: {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
