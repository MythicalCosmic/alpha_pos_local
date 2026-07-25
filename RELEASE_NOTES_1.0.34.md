# Alpha POS Desktop 1.0.34

This release hardens checkout, synchronization, shift accounting, and financial
reporting around the failure modes found during the restaurant reconciliation.
It preserves valid Smart POS 0.0.5 checkout traffic while refusing ambiguous
payment requests that could otherwise misstate the cash drawer.

## Checkout evidence and crash-safe retries

- Requires every non-zero checkout to include valid tender evidence: either the
  legacy single `payment_method`, structured `payments`, or the compatible
  Smart POS 0.0.5 dual form where both representations agree.
- Rejects missing, empty, malformed, contradictory, non-finite, non-positive,
  over-precision, or implausibly large tender values instead of silently
  defaulting an order to cash.
- Derives a stable payment action from retryable checkout requests so a crash
  after database commit can be retried without a second payment row or a second
  drawer credit.
- Returns stable payment evidence on both the first successful checkout and a
  recovered retry.
- Records zero-total orders without inventing a cash/card payment row.

## Synchronization recovery

- Preserves the server's sanitized rejection reason for each record, making
  dependency failures and validation errors actionable at the till.
- Makes manual retry reporting truthful: a record is not shown as cleared when
  the retry did not succeed.
- Retains the original dead-letter reason while a retry is pending and appends
  the latest transport/authentication failure without erasing the diagnostic
  evidence.
- Selects explicitly requested dead-letter records for recovery even when the
  normal queue view is capped, while keeping concurrent-generation checks that
  prevent stale retry results from overwriting newer state.

## Shift, cash, and reporting integrity

- Keeps usable per-tender totals when a frozen shift snapshot is only partially
  populated, with explicit source/completeness information instead of an
  all-or-nothing fallback.
- Treats a frozen tender snapshot as complete only when it contains exactly the
  five canonical methods, matches freshly derived net settlement evidence, and
  leaves no amount unattributed. Mismatches expose per-method discrepancies and
  fall back to the derived evidence instead of hiding money behind plausible
  zero rows.
- Requires action-identified paid orders to retain concrete, same-action,
  contiguous payment children whose methods agree with the order header.
  Missing or inconsistent children are reported as UNKNOWN rather than guessed
  as cash or card.
- Applies explicit branch cash-settlement cursor semantics so each cash movement
  belongs to the intended settlement interval.
- Rejects cash HR salary/expense movements while the branch has an `ACTIVE` or
  `ENDED` shift; use the cashier cashbox expense workflow or a non-cash method
  as appropriate.
- Rejects non-finite, over-precision, or out-of-range cashbox expense amounts
  before they enter the financial ledger.
- Attributes receipt-ledger and spreadsheet payment reporting by payment time,
  retaining the order's creation time as separate evidence.
- Uses one authoritative cutoff throughout an active-shift report and export,
  preventing a sale, refund, refund item, or expense from landing in one total
  while being absent from its receipt-level proof.
- Keeps a closed shift's clock-skewed, FK-owned refund as an explicit
  unbucketed adjustment in JSON and XLSX distributions, so net revenue still
  reconciles without inventing a false hour or date.
- Speeds up shift-window attribution and removes per-shift query growth from
  live-total enrichment without changing end-exclusive shift boundaries.

## Cloud companion hardening

- Applies the same strict payment-request validation and exact retry evidence to
  cloud admin checkout: malformed or empty bodies cannot become cash, crash
  retries reuse one payment action, conflicting replays return a conflict, and
  zero-total orders create no synthetic tender row.
- Preserves the cloud safety rule that physical cash must be collected on the
  owning restaurant desktop.

## Mandatory rollout gate

Smart POS **0.0.5 or newer** is the minimum supported cashier frontend. Early
versions sent an empty checkout body; Alpha POS Desktop 1.0.34 intentionally
rejects that unsafe shape. The backend cannot reliably infer a cashier
frontend's version from normal API traffic.

Before rollout, manually verify every cashier station's Smart POS version from a
trusted version display or deployment record. Stop if a version is below 0.0.5
or unknown. Upgrade with checkouts stopped and preferably after shift close,
record the queue state and tender totals, then canary controlled cash, card, and
any supported split-tender checkout. Confirm each canary sale once in the local
order/payment ledger and confirm no new rejected or quarantined sync records
before continuing.

Do not clear dead-letter or quarantine records merely to make the queue counter
zero. Preserve their reasons, correct the underlying validation/dependency
failure, and use the reviewed recovery path.
