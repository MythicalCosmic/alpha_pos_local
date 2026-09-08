# Alpha POS Desktop 1.0.38

This release fixes branch authorization for cloud-managed restaurant staff and
completes the backend/local codebase structure cleanup.

## Operational fixes

- Cloud-managed cashier and waiter identities now resolve to the local till's
  bound branch for login and shift operations.
- Login and session responses expose that effective local branch to clients,
  while the synchronized identity remains cloud-managed in storage.
- A concrete identity assigned to another branch remains denied.
- Cashiers can close their own active local shift even when their centrally
  managed identity is stored with the global `cloud` scope.
- Server-authoritative user names, roles, credentials, suspensions, and
  deletions continue to synchronize without local login telemetry outranking
  them.

## Maintenance

- Tests are grouped by feature under explicit `tests/` packages.
- Obsolete compatibility code, stale comments, and superseded release notes
  were removed without changing the accounting or synchronization contracts.
- Shared-core full replay pagination now uses a bounded machine-to-machine
  page size instead of the smaller public API pagination ceiling.
- Long full-replay pages retain their database lease for the complete bounded
  apply window, preventing the periodic worker from taking over mid-replay.

## Verification

- Shared core: 942 passed, 2 edition-specific skips.
- Desktop/local edition: 502 passed, 11 platform/database-specific skips.
- Django checks, Ruff, compilation, and diff validation passed.

No database migration is required for 1.0.38.
