"""One-shot bootstrap for an explicitly private Alpha POS installer.

Public installers never contain the payload filename handled here. A private
installer may place a validated support bundle beside ``AlphaPOS.exe``; the
PyInstaller runtime hook calls :func:`apply_installed_private_payload` before
the application imports Django settings.

The payload is deliberately narrow. It may configure the outbound support
tunnel and owner-only audit delivery, but it can never change restaurant,
cloud-sync, database, licensing, or fiscal identity.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any

from desktop import config_store


logger = logging.getLogger('desktop.private_release')

PAYLOAD_FILENAME = '.alphapos-private-support.json'
APPLIED_MARKER = config_store.DATA_DIR / '.private_support_payload_applied'
MAX_PAYLOAD_BYTES = 128 * 1024
MASK = '\u2022' * 8

SUPPORT_TUNNEL_KEYS = frozenset({
    'SUPPORT_TUNNEL_ENABLED',
    'SUPPORT_TUNNEL_HOST',
    'SUPPORT_TUNNEL_PORT',
    'SUPPORT_TUNNEL_USER',
    'SUPPORT_TUNNEL_REMOTE_DB_PORT',
    'SUPPORT_TUNNEL_REMOTE_API_PORT',
    'SUPPORT_TUNNEL_PRIVATE_KEY_B64',
    'SUPPORT_TUNNEL_KNOWN_HOST',
})
OWNER_AUDIT_KEYS = frozenset({
    'ORDER_AUDIT_TELEGRAM_CHAT_IDS',
    'LOCAL_TELEGRAM_AUDIT_ENABLED',
    'LOCAL_TELEGRAM_ORDER_RECORDED_ENABLED',
    'LOCAL_TELEGRAM_ORDER_PAID_ENABLED',
    'LOCAL_TELEGRAM_SHIFT_REPORT_ENABLED',
    'LOCAL_TELEGRAM_SHIFT_REPORT_FORMAT',
    'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN',
    'LOCAL_TELEGRAM_AUDIT_CHAT_IDS',
})
ALLOWED_PRIVATE_KEYS = SUPPORT_TUNNEL_KEYS | OWNER_AUDIT_KEYS


class PrivateReleasePayloadError(RuntimeError):
    """Safe failure while validating a private release payload."""


def installed_payload_path() -> Path | None:
    """Return the fixed installed payload path for a frozen application."""
    if not getattr(sys, 'frozen', False):
        return None
    return Path(sys.executable).resolve().parent / PAYLOAD_FILENAME


def _document_from_bytes(raw: bytes) -> dict[str, str]:
    if not raw or len(raw) > MAX_PAYLOAD_BYTES:
        raise PrivateReleasePayloadError(
            'private support payload is empty or exceeds the size limit'
        )
    try:
        document = json.loads(raw.decode('utf-8-sig'))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PrivateReleasePayloadError(
            'private support payload is not valid UTF-8 JSON'
        ) from exc
    if not isinstance(document, dict):
        raise PrivateReleasePayloadError(
            'private support payload must be a JSON object'
        )
    schema = document.get('schema')
    if schema not in (None, 'alphapos.private-support.v1'):
        raise PrivateReleasePayloadError(
            'private support payload uses an unsupported schema'
        )
    if 'config' in document:
        unexpected_top_level = sorted(set(document) - {'schema', 'config'})
        if unexpected_top_level:
            raise PrivateReleasePayloadError(
                'private support payload contains unsupported metadata: '
                + ', '.join(unexpected_top_level)
            )
    candidate = document.get('config', document)
    if not isinstance(candidate, dict):
        raise PrivateReleasePayloadError(
            'private support payload config must be a JSON object'
        )

    unknown = sorted(set(candidate) - ALLOWED_PRIVATE_KEYS)
    if unknown:
        # Names are safe to report; values are never interpolated.
        raise PrivateReleasePayloadError(
            'private support payload contains forbidden settings: '
            + ', '.join(unknown)
        )
    if not candidate:
        raise PrivateReleasePayloadError(
            'private support payload contains no approved settings'
        )

    normalized: dict[str, str] = {}
    for key, value in candidate.items():
        if isinstance(value, (dict, list, tuple)):
            raise PrivateReleasePayloadError(
                f'private support setting {key} must be a scalar value'
            )
        normalized[key] = '' if value is None else str(value)
    return normalized


def _validate_support_configuration(values: dict[str, str]) -> None:
    if not SUPPORT_TUNNEL_KEYS.intersection(values):
        return
    missing = sorted(
        key for key in SUPPORT_TUNNEL_KEYS
        if not str(values.get(key) or '').strip()
        and key != 'SUPPORT_TUNNEL_ENABLED'
    )
    if missing:
        raise PrivateReleasePayloadError(
            'private support payload is missing tunnel settings: '
            + ', '.join(missing)
        )
    try:
        from desktop import support_tunnel
        support_tunnel._validate_configuration({
            'host': values.get('SUPPORT_TUNNEL_HOST'),
            'port': values.get('SUPPORT_TUNNEL_PORT'),
            'user': values.get('SUPPORT_TUNNEL_USER'),
            'remote_db_port': values.get('SUPPORT_TUNNEL_REMOTE_DB_PORT'),
            'remote_api_port': values.get('SUPPORT_TUNNEL_REMOTE_API_PORT'),
            'private_key_b64': values.get('SUPPORT_TUNNEL_PRIVATE_KEY_B64'),
            'known_host': values.get('SUPPORT_TUNNEL_KNOWN_HOST'),
            'local_db_port': '5433',
            'local_api_port': '8000',
        })
    except Exception as exc:  # noqa: BLE001 - convert to a value-safe failure
        raise PrivateReleasePayloadError(
            'private support payload has an invalid tunnel configuration'
        ) from exc


def _validate_owner_audit(values: dict[str, str]) -> None:
    local = {
        key: value for key, value in values.items()
        if key.startswith('LOCAL_TELEGRAM_')
    }
    if not local:
        return
    try:
        from desktop import local_telegram_audit
        token = str(local.get('LOCAL_TELEGRAM_AUDIT_BOT_TOKEN') or '').strip()
        if token and token != MASK:
            local_telegram_audit._validate_token(token)
        if 'LOCAL_TELEGRAM_AUDIT_CHAT_IDS' in local:
            local_telegram_audit.parse_chat_ids(
                local.get('LOCAL_TELEGRAM_AUDIT_CHAT_IDS')
            )
        if 'LOCAL_TELEGRAM_SHIFT_REPORT_FORMAT' in local:
            report_format = str(
                local.get('LOCAL_TELEGRAM_SHIFT_REPORT_FORMAT') or ''
            ).strip().upper()
            if report_format not in {'TXT', 'MD'}:
                raise ValueError('unsupported report format')
    except Exception as exc:  # noqa: BLE001 - never include credential values
        raise PrivateReleasePayloadError(
            'private support payload has invalid owner-audit settings'
        ) from exc


def validate_payload_bytes(raw: bytes) -> dict[str, str]:
    """Validate and normalize a private payload without logging its values."""
    values = _document_from_bytes(raw)
    _validate_support_configuration(values)
    _validate_owner_audit(values)
    return values


def canonical_payload_bytes(raw: bytes) -> bytes:
    """Return a deterministic, allowlisted private payload for the installer."""
    values = validate_payload_bytes(raw)
    document = {
        'schema': 'alphapos.private-support.v1',
        'config': {key: values[key] for key in sorted(values)},
    }
    return (
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2)
        + '\n'
    ).encode('utf-8')


def _prepare_local_telegram(
    incoming: dict[str, str],
    *,
    current: dict[str, str],
) -> dict[str, str]:
    local = {
        key: value for key, value in incoming.items()
        if key.startswith('LOCAL_TELEGRAM_')
    }
    if not local:
        return {}
    from desktop import local_telegram_audit
    form_values = local_telegram_audit.configuration_values_from_environment(
        local
    )
    return local_telegram_audit.prepare_configuration_update(
        form_values,
        current=current,
    )


def _merge_values(
    incoming: dict[str, str],
    *,
    current: dict[str, str],
) -> dict[str, str]:
    clean: dict[str, str] = {}
    local_keys = {key for key in incoming if key.startswith('LOCAL_TELEGRAM_')}
    for key, value in incoming.items():
        if key in local_keys:
            continue
        if (
            key in config_store.SECRET_KEYS
            and not str(value or '').strip()
            and str(current.get(key) or '').strip()
        ):
            # A private upgrade may carry an intentionally blank/masked field.
            # It must never erase a credential already provisioned on the till.
            continue
        if (
            key in config_store.SECRET_KEYS
            and str(value or '').strip() == MASK
        ):
            continue
        clean[key] = value
    clean.update(_prepare_local_telegram(incoming, current=current))
    return clean


def apply_private_payload(
    payload_path: Path,
    *,
    marker_path: Path | None = None,
) -> dict[str, Any]:
    """Atomically merge one validated payload and remove it after success."""
    payload_path = Path(payload_path)
    marker_path = Path(marker_path or APPLIED_MARKER)
    if not payload_path.is_file():
        return {'status': 'absent', 'imported_count': 0}

    try:
        # Inno Setup places credential material beside the frozen executable.
        # Remove inherited/broad ACEs before the first byte is parsed.
        config_store._harden_windows_private_path(payload_path)
        raw = payload_path.read_bytes()
    except OSError as exc:
        raise PrivateReleasePayloadError(
            'private support payload could not be read'
        ) from exc
    digest = hashlib.sha256(raw).hexdigest()
    try:
        previous_digest = marker_path.read_text(encoding='ascii').strip()
    except OSError:
        previous_digest = ''
    if previous_digest == digest:
        payload_path.unlink(missing_ok=True)
        return {'status': 'already_applied', 'imported_count': 0}

    incoming = validate_payload_bytes(raw)
    current = config_store.read_config()
    clean = _merge_values(incoming, current=current)
    if not clean:
        raise PrivateReleasePayloadError(
            'private support payload produced no configuration changes'
        )

    # write_config preserves unmanaged settings and every managed field not
    # present in ``clean``. The allowlist above makes branch/cloud/DB identity
    # impossible to change through this path.
    config_store.write_config(clean)
    config_store._write_protected(marker_path, digest + '\n')
    try:
        payload_path.unlink()
    except OSError:
        # The digest marker makes a leftover payload inert on every later boot.
        logger.warning(
            'private support payload was applied but could not be removed'
        )
    return {'status': 'applied', 'imported_count': len(clean)}


def apply_installed_private_payload() -> dict[str, Any]:
    path = installed_payload_path()
    if path is None:
        return {'status': 'not_frozen', 'imported_count': 0}
    return apply_private_payload(path)
