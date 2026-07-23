# Alpha POS Desktop 1.0.31

This release repairs the sync acknowledgement and settlement paths that could
leave restaurant revenue ahead of cloud revenue while the desktop appeared
successfully synchronized.

## Sync integrity

- Requires an exact, non-overlapping accepted/retryable/rejected UUID result for
  every outbound record. An incomplete or legacy acknowledgement retains the
  batch instead of deleting it.
- Distinguishes safe idempotent replays from stale versions, cross-branch
  records, natural-key conflicts, and other permanent rejections.
- Keeps missing-parent records retryable without consuming poison-record
  attempts, and makes permanent rejections and branch quarantine visible as
  dead letters.
- Repairs the paid-header race from complete immutable payment evidence and
  rebases a locally pending paid Order after a higher cloud version is pulled.
- Preserves settlement action identity in both sync directions.
- Resolves local cashier identities through a restricted, non-login cloud
  identity path so their Orders are not stranded behind a missing User UUID.
- Isolates cursors, leases, scope epochs, and dead-letter revival by branch.
- Validates legacy array batches completely and bounds recovery of unpublished
  change-feed rows.
- Queues courier-assignment corrections through normal model save semantics.

## Local Telegram audit

- Adds a separate **Local Telegram Audit** desktop section with its own protected
  bot token, owner recipients, master switch, per-event switches, and TXT or
  Markdown shift report selection.
- Sends concise order-recorded and order-paid messages directly from the
  restaurant PC to Telegram. Product lines are deliberately excluded.
- Uses a small durable local outbox, stable event identities, commit callbacks,
  retry backoff, and bounded reconciliation scans to close process-crash gaps
  without replaying events from periods when the feature was disabled.
- Sends a bounded shift-close attachment with exact shift times, order headers,
  canonical tender/refund totals, frozen totals, and explicit
  frozen-minus-recomputed differences.
- Removes temporary reports after delivery and cleans stale crash remnants.

## Restricted home inspection

- Hardens the restaurant reverse tunnel with exact Ed25519 host pinning,
  protected key ACLs, injected-SSH-config suppression, loopback-only listeners,
  query-level database readiness, exact backend readiness, and visible retry
  diagnostics.
- Adds a separate no-shell home-inspector SSH account that can forward only the
  two support listeners.
- Ships a pinned `AlphaPOS-Support-Connector.ps1` and relay host-key artifact.
  The inspector private key and restaurant support configuration remain
  separate protected files and are never included in Git or the installer.

The server acknowledgement protocol must be deployed before updating the
desktop client. A 1.0.31 desktop intentionally retains a batch when an older
server cannot provide the complete acknowledgement partition.
