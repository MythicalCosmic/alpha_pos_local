# Alpha POS Desktop 1.0.43

Successful payments and cashier/waiter order edits now advance the order update
timestamp used by incremental cashier reports. Previously, a report could keep
an unpaid copy after the order had been paid because its update timestamp did
not change. Sync acknowledgements preserve the source order timestamp.

PostgreSQL cashier ownership locks also allow a closing shift to complete its
foreign-key checks while a late order creation waits for that shift. This fixes
a reproduced shift-close/create deadlock without weakening the active-shift guard.

The isolated code patch passed 287 local regression tests and 11 PostgreSQL
checks, including payment retry, rejected payment, and shift-close serialization.
The shared core order/sync and shift suites passed 196 and 85 tests respectively.

Previously missed report entries require an explicit refresh of the cashier
report cache. This release does not rewrite historical payments, amounts or
payment dates. Verify the installed version and a full cash/card closing period
after installation.
