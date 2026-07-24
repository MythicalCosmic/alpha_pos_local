# Alpha POS Desktop 1.0.33

This release repairs direct raw-order Telegram delivery and completes a
responsive layout pass across the desktop control panel. It also makes private
upgrades repair a missing signed-update endpoint without permitting payloads to
redirect an installation.

## Upgrade-safe private installer

- Adds the exact `ALPHA_POS_UPDATE_URL` baked into the release whenever a
  private payload is staged, without modifying the protected source JSON.
- Gives the upgraded payload a new digest so an older installation with a
  blank or stale updater setting applies the repair on first launch.
- Rejects every alternate update URL, including host, scheme, path,
  trailing-slash, and whitespace variants.
- Continues to preserve branch, cloud-sync, database, licensing, and fiscal
  identity.

## Owner-only Telegram delivery

- Makes **Send raw file now** use the saved Local Telegram Audit bot and owner
  IDs when no separate complete raw-evidence route is configured.
- Keeps credentials atomic: a token and recipient list are selected from one
  complete source and are never mixed.
- Preserves a separately configured raw-evidence route as the higher-priority
  compatibility option.
- Never falls back to the broad staff notification recipient list.
- Derives the dashboard status and manual/automatic send paths from the same
  resolver, removing the false **Needs attention** state.
- Ignores errors left by obsolete recipients after the owner route changes.
- Records current delivery failures and clears them after an acknowledged
  manual send without exposing bot tokens in status or logs.

## Desktop layout

- Repairs the dashboard grid that created implicit columns and pushed the
  Telegram evidence panel beyond the right edge of the native window.
- Stacks the two long support panels at desktop-app widths so pinned endpoints,
  fingerprints, badges, switches, and actions remain readable.
- Adds safe shrink and wrapping behavior for cards, grids, key/value rows,
  badges, and action groups.
- Uses a compact one-column layout at the supported 900 x 640 minimum while
  retaining balanced multi-column tiles where they remain readable.
- Routes the raw-evidence **Manage** action directly to Local Telegram Audit.

The owner-only bot configuration remains protected per install and is not
included in Git, the public updater target, or the portable executable.
