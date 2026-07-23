# Alpha POS Desktop 1.0.29

- Keeps every locally closed shift in a visible pending state until the cloud
  verifies the exact close manifest and all per-tender settlement rows.
- Requeues incomplete close evidence and surfaces permanent cloud conflicts;
  an ordinary HTTP 200 or an empty generic sync queue can no longer masquerade
  as a completed shift-close upload.
- Adds always-visible controls and truthful health indicators for the restricted
  support tunnel. "DB ready" requires an authenticated local PostgreSQL query,
  not merely a running SSH process.
- Adds independent switches and delivery visibility for append-only local order
  capture and direct-to-owner Telegram evidence. Pending bytes retry without
  skipping until Telegram acknowledges them.
- Shows captured-order counts, recipient configuration, pending evidence bytes,
  JSONL/JSONL.GZ formats, last delivery errors, and shift-close pending/conflict
  warnings in the desktop dashboard.

The support tunnel remains outbound-only. Its relay listeners bind to loopback
and the release contains no Telegram token or SSH private key; those stay in the
protected per-install configuration.
