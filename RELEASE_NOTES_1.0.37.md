# Alpha POS Desktop 1.0.37

This release makes shift money fail closed: the application no longer presents
an incomplete or ambiguously attributed subtotal as proven physical cash.

## Physical cash and all-tender settlement

- Separates physical drawer CASH from card, acquirer, and Payme settlement.
- Derives CASH after customer change, cash refunds, and drawer expenses.
- Keeps missing cashier counts nullable and visibly `UNCOUNTED`; a missing
  count is never converted to zero or reported as a proven shortage.
- Treats cashier count submission and manager confirmation as independent
  events.
- Preserves the manager's immutable reconciliation while exposing later
  evidence differences as diagnostics rather than rewriting history.
- Requires complete tender attribution before a manager can reconcile a new
  shift. Unknown sale or refund evidence blocks the action even when positive
  and negative unknown amounts happen to net to zero.
- Treats historical reconciliations without a complete posted tender bundle as
  CASH-only proof. Non-cash and all-tender confirmation remain incomplete.

## Synchronization and historical repair safety

- Locks the financially owning shift before applying synchronized order,
  payment, refund, item, expense, or frozen tender evidence.
- Rejects non-identical late evidence for a completed/reconciled shift while
  acknowledging an exact replay idempotently.
- Includes a fingerprinted, dry-run-first historical repair command with exact
  local/cloud generation checks and auditable repair markers.
- Keeps settlement-row corrections local/cloud independent; the repair refuses
  to run while those rows are still queued or unsynchronized.

## Reporting and support

- Publishes nullable availability/completeness fields for shift financial
  evidence instead of returning plausible zeroes after a derivation failure.
- Exposes complete-population, paginated-filter-safe totals for ENDED shifts
  still awaiting manager reconciliation.
- Distinguishes known diagnostic subtotals from complete confirmed totals.
- Reports the running build identity in the local health response.
- Updates the local Telegram shift audit to show cashier count and manager
  confirmation separately.

## Rollout

Install with checkout stopped and preferably after the current shift closes.
Back up both local and cloud databases first. Deploy the compatible server
contract, install the manager frontend, publish Smart POS **0.0.11**, and
upgrade every cashier station before relying on the new UI fields.

On one canary till, test exact CASH, CASH with change, card/acquirer, Payme,
mixed tender, and a simulated response-loss retry. Verify one paid order,
explicit payment lines, the same retry idempotency key, correct physical CASH,
and a clean sync queue before wider rollout.

No historical repair should be applied during ordinary checkout. Use the
separate repair runbook and a checkout-stopped maintenance window.
