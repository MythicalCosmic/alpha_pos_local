"""PyInstaller runtime hook for the optional private support payload."""
from __future__ import annotations

import logging

from desktop.private_release import (
    PrivateReleasePayloadError,
    apply_installed_private_payload,
)


logger = logging.getLogger('desktop.private_release.bootstrap')

try:
    result = apply_installed_private_payload()
    if result.get('status') == 'applied':
        logger.info(
            'private support configuration applied (%s approved settings)',
            result.get('imported_count', 0),
        )
except PrivateReleasePayloadError as exc:
    # Exception text is intentionally value-free. Keep the previous restaurant
    # configuration and allow the application to boot.
    logger.error('private support configuration was rejected: %s', exc)
except Exception:  # noqa: BLE001 - optional payload must never brick checkout
    logger.exception('private support configuration bootstrap failed safely')
