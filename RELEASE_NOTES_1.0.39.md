# Alpha POS Desktop 1.0.39

## Cashier access and shifts

- Cashiers can switch accounts on a shared till without an old seven-day
  session blocking the next login.
- The till accepts normal attempts from multiple cashiers while retaining
  strict per-account PIN rate limits.
- Cloud-managed cashier identities resolve to the restaurant terminal's bound
  `branch1`, so every cashier can close their own local shift.
- Managers can close a selected same-branch shift with
  `POST /shifts/{shift_id}/end`.
- Manager-assisted closure requires explicit per-tender counts.
- Manager-assisted closure retains the normal unpaid-order, tender-integrity,
  and settlement-evidence safeguards.

## AI assistant

- Luna remains warm and helpful when questions are repeated or several
  questions are asked together.
- Luna tool calls use the provider-compatible reasoning configuration.

No database migration is required for 1.0.39.

## Verification

- Shared core: 979 passed, 2 edition-specific skips.
- Desktop/local edition: 509 passed, 11 platform/database-specific skips.
- Cloud server edition: 488 passed.
- Django checks, migration consistency, Ruff, and diff validation passed.
