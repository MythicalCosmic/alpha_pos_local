# Alpha POS Desktop 1.0.40

## Login and shift lifecycle

- Successful cashier and manager login now creates a real ACTIVE shift before
  returning a session.
- Repeated login resumes the same shift without moving its start time or
  creating a duplicate.
- Authenticated login safely claims a blank pre-upgrade cashier shift for the
  current installation; a shift owned by another installation remains blocked.
- Multiple cashiers may keep their own long-lived shifts on one shared till.
  The database still permits only one ACTIVE shift per user.
- The login response includes `active_shift`, including its authoritative ID,
  device ownership, and `resumed` state.
- Logout leaves the shift open. Only the explicit shift-close workflow ends it.

## Compatibility and migration

- Adds `base.0056_remove_exclusive_shift_device_slot`, which removes the former
  one-active-cashier-per-device constraint while preserving device attribution.
- No existing shift or settlement data is rewritten.

## Verification

- Shared core: 986 passed, 2 edition-specific skips.
- Desktop/local edition: 551 passed, 11 platform/database-specific skips.
- Django checks, migration consistency, Ruff, and diff validation passed.
