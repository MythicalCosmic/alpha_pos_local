# Alpha POS Desktop 1.0.32

This release repairs the second-launch failure discovered during the live
1.0.31 laptop test and adds an explicit private-installer path for fast,
authorized restaurant provisioning.

## Checkout and startup reliability

- Repairs existing order-audit ACLs object by object before reading them.
  Directories receive inheritable owner rights and files receive effective file
  rights; recursive directory-only grants can no longer create empty file
  DACLs.
- Refuses to traverse symlinks, junctions, or other reparse points while
  repairing private evidence.
- Protects the local Telegram outbox and existing report artifacts with the
  same owner-only ACL boundary.
- Serializes Django bootstrap, migrations, and required setup before any
  model-backed desktop status request can query an upgraded schema.
- Makes HTTP order evidence fail open: an optional audit import or write
  failure is logged but cannot abort ASGI startup or turn a sale into an HTTP
  failure.
- Starts and stops the support tunnel, order audit, and local Telegram workers
  independently so one optional subsystem cannot block checkout or updater
  cleanup.

## Private restaurant installer

- Adds an opt-in private build mode that validates a protected support bundle
  without printing credential values and embeds it only in a separately named
  private installer.
- Applies the bundle before Django starts, accepts only support-tunnel and
  owner-audit settings, and cannot change branch, cloud-sync, database,
  licensing, or fiscal identity.
- Preserves nonblank existing secrets when an incoming value is blank or
  masked, writes a non-secret digest marker, and removes the installed
  plaintext payload after successful application.
- Keeps the normal installer, portable executable, updater bundle, Git history,
  and public release path credential-free.

Anyone holding the private installer can extract its embedded credentials.
Treat that installer as a private key and distribute it only through the
authorized support channel.
