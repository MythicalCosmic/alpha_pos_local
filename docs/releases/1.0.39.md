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
- Manager-assisted closure requires a finite nonnegative count for every
  supported tender; missing, misspelled, duplicate, negative, or nonnumeric
  values are rejected before the shift changes.
- Manager-assisted closure retains the normal unpaid-order, tender-integrity,
  and settlement-evidence safeguards.
- Unpaid orders with a zero balance remain in order history but no longer
  prevent an otherwise valid shift from closing.
- Cloud branch markers resolve case-insensitively, preventing `CLOUD` versus
  `branch1` authorization failures.
- The cloud API cannot manufacture a close manifest for a treasury-eligible
  restaurant shift from a partial mirror. Those shifts must close on their
  source terminal and sync their immutable settlement bundle.

## AI assistant

- Luna remains warm and helpful when questions are repeated or several
  questions are asked together.
- Luna tool calls use the provider-compatible reasoning configuration.

No database migration is required for 1.0.39.

## Windows release

- Clean onedir and portable builds now fail closed unless the required x64
  Microsoft C++ runtime matches the approved SHA-256 and PE architecture.
- The public installer contains no restaurant configuration, support
  credentials, private keys, or TUF signing keys.
- A clean installer extraction and the installed frozen application completed
  the database, migrations, HTTP, sync, fiscal mock, and GUI-import self-test.

## Verification

- Shared core: 985 passed, 2 edition-specific skips.
- Desktop/local edition: 528 passed, 11 platform/database-specific skips.
- Cloud server edition: 490 passed.
- Django checks, migration consistency, Ruff, and diff validation passed.
