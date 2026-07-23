# Alpha POS home inspection tunnel

The support path provides temporary, full access to the restaurant's local
PostgreSQL database and local backend through two SSH hops. Neither the
restaurant database nor backend is bound to a public interface.

## Files to keep on the home laptop

Keep these three files together or in the locations passed to the connector:

- `AlphaPOS-Support-Connector.ps1`
- `AlphaPOS-Support-Relay-Known-Hosts`
- the separately transferred inspector private key

The private key is not in the repository, installer, or update bundle. Store it
under the current Windows user's private key directory and do not send it by
Telegram or email. The connector refuses an unexpected relay host key or
inspector key.

## Restaurant-side safety gate

In the desktop observability panel:

1. Enable the authorized support tunnel.
2. Wait for both **DB Ready** and **Backend Ready**.
3. Leave Alpha POS running while inspection is in progress.
4. Disable the tunnel after the inspection window.

Do not trust a running `ssh.exe` process alone. **DB Ready** requires a real
authenticated `SELECT 1`, and **Backend Ready** requires the exact local health
response.

## Validate and connect from home

From PowerShell on the home laptop:

```powershell
powershell -ExecutionPolicy Bypass -File .\AlphaPOS-Support-Connector.ps1 -ValidateOnly
powershell -ExecutionPolicy Bypass -File .\AlphaPOS-Support-Connector.ps1
```

Keep the second PowerShell window open. It exposes only these home-laptop
loopback endpoints:

- PostgreSQL: `127.0.0.1:25433`
- local backend: `http://127.0.0.1:28000`

For the standard embedded restaurant database, connect a PostgreSQL client with
database `alpha_pos` and user `alpha_pos`. The embedded cluster uses loopback
trust authentication, so the inspector SSH key is the effective access
boundary. Treat the session as privileged full-database access and use
read-only queries unless a repair has been explicitly approved.

If the restaurant is configured to use an external PostgreSQL service, use that
installation's configured database name, user, and password instead.

## Failure meanings

- Connector validation failure: wrong/missing key, unsafe key ACL, or host-pin
  mismatch. Do not bypass the check.
- Connection refused on the home loopback port: the connector is not running,
  the restaurant tunnel is disabled, or the restaurant is offline.
- Restaurant shows **DB Not Ready**: the local database query failed; do not
  inspect or claim that the tunnel is ready.
- Restaurant shows **Backend Not Ready**: the local backend health check failed.
- SSH forwarding failure: the relay rejected authentication, a permitted
  loopback listener is already occupied, or the relay policy is unavailable.

The relay accounts have no shell, terminal, agent forwarding, Unix-socket
forwarding, or arbitrary TCP destinations. The restaurant publisher can create
only its two loopback reverse listeners; the home inspector can open only local
forwards to those listeners.
