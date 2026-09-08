# Alpha POS Desktop 1.0.41

## Signed-update trust recovery

- This manually installed recovery release establishes a replacement signed
  update root after the original release signing state was lost during a
  workstation reinstall.
- The dedicated Trust Recovery installer moves only the obsolete updater cache
  to a timestamped rollback folder. On first update check, Alpha POS installs
  its new bundled public root.
- PostgreSQL data, orders, shifts, users, configuration, logs, and support
  settings are outside the updater cache and are not changed by the migration.
- Ordinary installers and automatic updates never reset the trust cache; the
  recovery behavior must be selected explicitly at build time.

## Included operational fixes

- Active cashier and manager login creates or resumes one authoritative shift.
- Multiple cashiers can work from the same shared till.
- Same-branch shift closing includes the terminal ownership and zero-value-order
  recovery fixes shipped in 1.0.40.

## Rollout

Existing installations that trust the retired root must run the 1.0.41 Setup
installer once. After that manual in-place upgrade, future signed updates work
normally from the replacement feed.
