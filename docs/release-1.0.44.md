# Alpha POS Desktop 1.0.44

This release includes the verified audit fixes completed after 1.0.43.

- Payments, order edits, discounts, and retries preserve recorded amounts and
  reject invalid or inconsistent input before business records are saved.
- Stock availability and reservations use base units and combine shared
  ingredient requirements. Failed reservations roll back completely.
- Inventory filters and recipe reads exclude deleted records and honor the
  selected location. Batched reads reduce database queries.
- Recipe creation rolls back incomplete writes. Approved recipe edits create
  separate draft versions with unique codes; invalid units and multipliers
  produce validation errors.
- Recipe services have focused modules, and obsolete helpers have been removed.

The complete source suites passed 3,683 tests with 29 documented platform,
edition, or database skips. Another 365 stock checks passed on PostgreSQL,
including competing reservations and concurrent recipe version creation.

Install using the existing Windows account and installation, after checkout
activity has stopped and preferably after shift close. Preserve the existing
data directory and record a backup and sync-queue status before upgrading.
Verify version 1.0.44, backend health, normal cash/card checkout, and queue drain
afterward. Existing Smart POS 0.0.11-or-newer compatibility requirements apply.

This release does not rewrite historical sales or stock. Historical cashier
cache recovery and comparison with actual cash/card closing amounts remain
separate operational checks.
