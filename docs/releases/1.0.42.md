# Alpha POS Desktop 1.0.42

## Stock and profitability audit integrity

- Stock deductions and later quantity adjustments now retain the exact order-line
  reference used to calculate cost of goods sold.
- Removing the final item from a cashier or waiter order keeps an auditable,
  soft-deleted order and line tombstone instead of severing the stock ledger link.
- Returns caused by line edits remain attributable to the original sale line, so
  profitability reporting can net the returned quantity from actual COGS.
- Shared accounting evidence adds explicit expense-reporting groups and preserves
  historical product-cost records used by finalized profitability periods.

## Upgrade safety

- This is an in-place application update. It does not reset PostgreSQL data,
  orders, shifts, users, configuration, logs, or support settings.
- Cashier stations must run Smart POS 0.0.11 or newer. Verify every station from
  its trusted version display or deployment record before enabling the update.
- Roll out to one idle canary station first; test cash, card, and any configured
  split-tender sale, then confirm its local ledger and sync queue before widening.
