# Alpha POS Desktop 1.0.36

This release hardens cashier identity ownership and both directions of cloud
synchronization after the restaurant reconciliation proved that the local
order and tender totals were complete.

## Cashier identity and terminal ownership

- Rejects requests that present different session-cookie and Bearer identities
  instead of silently choosing one account.
- Requires an explicit logout before the same browser signs in as another
  account.
- Binds every new local cashier shift to this installation's stable device
  identity. A cashier cannot take payment, refund, or record a drawer expense
  through a blank legacy shift or a shift owned by another terminal.
- Keeps legacy shifts closable so rollout does not strand historical work, but
  requires a fresh device-bound shift before accepting new money.
- Records token-free login, device, network, request, response, and local order
  evidence in a bounded, rotating forensic stream.

## Bidirectional synchronization recovery

- Replays the complete authenticated cloud feed once after upgrade so cloud
  user, catalog, and configuration changes skipped by an old cursor are
  delivered again.
- Makes the replay request durable before network transport. If the server is
  unavailable or another pull owns the lease, the background worker retries
  from the cleared cursor instead of losing the operator's request.
- Uses a database-serialized logical cloud-feed clock, so an operating-system
  clock correction cannot place a later cloud edit behind an older cursor.
- Refuses to advance the pull cursor when a cloud page contains an unsupported
  model, malformed records, or unresolved foreign-key dependencies. The
  evidence is replayed after the compatible code or parent record arrives.
- Gives trusted cloud state priority over legacy terminal-inflated versions for
  cloud-owned records while keeping local transactional and tombstone ownership
  fail-closed.
- Locks persisted rows before ordinary saves and physical deletes so stale
  in-memory objects cannot move a sync version backward or publish a retired
  UUID.
- Stores hard-delete tombstones even while transport is disabled, allowing a
  later reconnect to remove the same record on the cloud.
- Publishes the server's legacy-courier cleanup through the ordinary change
  feed instead of applying an invisible bulk database update.
- Disables Django's unsafe bulk-delete admin shortcut for synced data; ordinary
  one-record admin deletion remains available through the sync-aware soft
  delete path.
- Removes login timestamps from replicated User payloads so routine logins no
  longer create false identity versions or hide later cloud changes.
- Rebases natural-key UUID convergence and its exact outbound queue generation
  atomically, preventing locally owned fields from remaining queued under a
  vanished UUID.
- Preserves newer concurrent queue generations while acknowledging only the
  exact payload generation accepted by the other side.
- Exposes durable full-replay requested, pending, and completed state after
  cache loss or process restart, together with the latest pull error.
- Adds a desktop recovery action to request a complete cloud replay without
  deleting local order, payment, or settlement evidence.

## Rollout

Install with checkout stopped and preferably after the current shift closes.
After the first launch, close any pre-upgrade cashier shift that reports it is
not bound to this terminal, then start a fresh shift. Allow the automatic full
cloud replay to finish, verify the queue reaches zero without rejected or
quarantined rows, and perform one controlled cash and one controlled card
checkout before normal service.

Smart POS **0.0.5 or newer** remains mandatory.
