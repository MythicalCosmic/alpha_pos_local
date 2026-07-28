# Alpha POS Local

Alpha POS Local is the in-restaurant Windows edition. It runs the cashier,
waiter, kitchen-display, courier-dispatch, and synchronization APIs beside an
embedded PostgreSQL database, then packages them as the AlphaPOS desktop app.
Shared business rules come from the pinned `alpha_pos_core` submodule.

## Repository layout

- `customers/` — cashier authentication, ordering, checkout, shift control, and
  local display APIs.
- `waiters/` — waiter authentication, table service, ordering, and discounts.
- `couriers/` — courier provisioning, dispatch, mobile sessions, payments, and
  delivery events.
- `desktop/` — application lifecycle, embedded PostgreSQL, control panel,
  support tooling, audit delivery, and signed updates.
- `config/` — local Django settings, URLs, and ASGI wiring.
- `tests/` — desktop, operations, release, and cross-app integration tests.
- `alpha_pos_core/` — pinned shared backend submodule.

The shared core supplies users, shifts, financial models, synchronization,
stock, cashbox, fiscalization, licensing, notifications, and HR attendance
services. Local cashier and waiter login call the shared attendance service
directly.

## Runtime

- HTTP and WebSocket traffic runs through embedded Uvicorn and Django Channels.
- A single-process `InMemoryChannelLayer` provides local realtime delivery.
- PostgreSQL is supervised as a child process and stores data beneath the
  installation's `%LOCALAPPDATA%\AlphaPOS` directory.
- Public QR self-order routes run on the till. The customer Telegram bot runs
  on the server edition.

## Development

Initialize the shared code and install the development dependencies:

```bash
git submodule update --init --recursive
python -m pip install -r requirements-dev.txt
```

Then run:

```bash
python manage.py check
python -m pytest
```

Pytest excludes the shared submodule because `alpha_pos_core` has its own test
suite. Release and operational procedures live in `RELEASES.md`,
`desktop/UPDATES.md`, `OPERATIONS.md`, and `PRIVATE_RELEASE_BUILD.md`.
