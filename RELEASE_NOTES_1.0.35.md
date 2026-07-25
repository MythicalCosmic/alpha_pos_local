# Alpha POS Desktop 1.0.35

This release contains the complete checkout, synchronization, shift-accounting,
and reporting hardening introduced in 1.0.34, plus two canary-proven desktop
lifecycle fixes.

## Canary follow-up fixes

- Prevents dashboard status polling from restarting the secondary order-audit
  and local Telegram workers after application or updater shutdown has begun.
  This removes a harmless but noisy database-shutdown race while preserving the
  automatic startup backfill on the newly launched process.
- Honors `LICENSE_HEARTBEAT_DISABLED` for intentionally offline-licensed
  installations. Disabled heartbeat is now reported as an intentional state
  instead of repeatedly logging a missing control-center URL as a failure.

Neither canary finding affected checkout, payments, shift totals, or cloud
synchronization. Both were detected by exercising the signed 1.0.34 updater and
inspecting the frozen application's shutdown and startup logs.

## Financial and synchronization integrity

- Requires valid tender evidence for every non-zero checkout and rejects
  malformed, missing, contradictory, non-finite, non-positive, over-precision,
  or implausibly large payment values instead of guessing cash.
- Makes checkout retries crash-safe and idempotent so a retry after commit
  cannot create a second payment or drawer credit.
- Preserves server rejection details, dead-letter history, dependency
  information, and concurrent-generation protections throughout reviewed retry
  and recovery.
- Validates frozen shift tender snapshots against derived settlement evidence
  and exposes discrepancies instead of accepting plausible but incomplete
  cash/card totals.
- Keeps receipt, spreadsheet, refund, expense, and shift-window reporting on
  one authoritative cutoff and preserves otherwise unbucketed adjustments as
  explicit evidence.
- Rejects unsafe cash movements and invalid cashbox expense amounts before they
  can enter the financial ledger.
- Applies the same strict payment and idempotency rules to cloud-admin checkout
  while retaining the rule that physical cash belongs to the restaurant till.

## Mandatory rollout gate

Smart POS **0.0.5 or newer** is required on every cashier station. Older
versions could submit an empty checkout body, which this desktop release
intentionally rejects because the tender cannot be inferred safely.

Upgrade with checkouts stopped and preferably after shift close. Record local
queue counts and tender totals, update one canary station, and verify controlled
cash, card, and any supported split-tender checkout exactly once in the local
order/payment ledger. Confirm that no new rejected or quarantined sync records
appear before wider rollout.

Do not clear dead-letter or quarantine records merely to make a counter zero.
Preserve the reason, correct the underlying validation or dependency failure,
and use the reviewed recovery path.
