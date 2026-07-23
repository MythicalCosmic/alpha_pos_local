# Alpha POS Desktop 1.0.30

- Accepts the protected support configuration in its shipped JSON format as
  well as the legacy `KEY=VALUE` format.
- Makes a fresh installation able to enable the restricted support tunnel and
  direct local-order evidence without manually rewriting the support package.
- Preserves the 1.0.29 shift-close acknowledgment, tunnel health, and
  direct-to-owner Telegram observability hardening.

The support tunnel remains outbound-only. Relay listeners bind to loopback, and
the installer contains no Telegram token or SSH private key; those remain in the
separate protected support configuration.
