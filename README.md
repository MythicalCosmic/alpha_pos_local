# alpha_pos_local

The **Windows desktop POS** edition — compiled into the AlphaPOS app with **embedded
Postgres**. Consumes `alpha_pos_core` as a submodule + editable install, and adds only
the point-of-sale apps + the desktop build chain.

## Owns

- `customers` — cashier POS: login picker, order create/pay, chef/client KDS displays,
  till shift control.
- `waiters` — waiter POS: order taking, table-status, order-level discounts.
- `desktop/` — the control panel + packaging (PyInstaller spec, `build_installer.ps1`,
  Inno Setup, the tufup self-update `tools/release.py`).

## From `core` (shared)

`base` + sync engine, `stock`, `discounts`, `cashbox`, `fiscalization`, `licensing`,
`notifications`. **`hr` ships here too as tables-only** (no HR UI) so the AUTO_POS
attendance row at cashier login has somewhere to write — handled by
`core/attendance/pos_hook.py`.

## Edition specifics

- **ASGI:** `waitress` → **embedded uvicorn** inside the frozen build.
- **Channel layer:** `InMemoryChannelLayer` (single process — no Redis, no JSON file).
- **DB:** **embedded Postgres** bundled in the installer, supervised as a child process
  (data dir under `%LOCALAPPDATA%\AlphaPOS`), replacing SQLite.
- Websocket consumers: order-queue / KDS / table-map / drawer / license, and the
  till side of the desktop↔cloud sync socket + cashier-control (lock/force-logout).
- The `notifications` order-taking surface (telegram bot / QR self-order) mounts its
  URLs **here only**.

## Status

`customers`, `waiters`, `desktop` + build chain copied. Next: `config/settings.py`
(extends `core` settings_base, `EDITION=local`, `OPEN_LAN=on`), embedded-uvicorn ASGI,
wire core as a submodule, swap SQLite→embedded Postgres, `manage.py check`.
