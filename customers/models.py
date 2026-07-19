
"""Local-only persistence for cashier/POS integration concerns.

The shared ``base.Order`` model synchronizes between cloud and tills.  Receipt
printing is deliberately *not* synchronized: it is a side effect owned by one
physical installation and needs a durable local ledger so a refreshed browser
or a second cashier session cannot rediscover and print the same online order.
"""
from django.db import models


class ReceiptPrintPolicy(models.Model):
    """One-row activation boundary for the local auto-print feature.

    Filtering by the order's original ``created_at`` prevents a later cloud
    origin backfill (POS -> TELEGRAM) from replaying months of old orders after
    this desktop release is installed.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    activated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'ReceiptPrintPolicy<activated_at={self.activated_at}>'


class ReceiptPrintJob(models.Model):
    """Durable, fenced claim for one Telegram order receipt.

    A job is created lazily by the claim endpoint after the complete order and
    its live item gross are visible locally.  Independently-synced OrderItems
    can arrive after their Order, so ``materialization_fingerprint`` and
    ``eligible_at`` require the matching line set to remain unchanged briefly
    before it can be claimed.  ``order`` is one-to-one, which is the
    database-level duplicate-print guard.  The random ``claim_token`` is a
    fencing token: after an expired lease is reclaimed, a late acknowledgement
    from the old printer can no longer complete the new claim.

    Physical printers cannot offer mathematical exactly-once delivery (a
    process can die after paper leaves the printer but before ACK reaches us).
    This ledger provides the strongest practical contract: one active consumer,
    durable retry after an unacknowledged lease, and never print again after a
    successful acknowledgement.
    """

    class State(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        CLAIMED = 'CLAIMED', 'Claimed'
        PRINTED = 'PRINTED', 'Printed'

    order = models.OneToOneField(
        'base.Order', on_delete=models.CASCADE, related_name='receipt_print_job',
    )
    state = models.CharField(
        max_length=12, choices=State.choices, default=State.PENDING,
        db_index=True,
    )
    claim_token = models.UUIDField(null=True, blank=True, unique=True)
    # A hash of the authenticated POS session, never the bearer credential.
    # It lets a lost HTTP response be replayed safely by the same terminal
    # without exposing that claim to another signed-in device.
    claimed_session_hash = models.CharField(
        max_length=64, blank=True, default='', db_index=True,
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    attempt_count = models.PositiveIntegerField(default=0)
    # SHA-256 over Order.subtotal and every live line's identity/version/money.
    # Empty means the currently visible lines do not prove completeness.
    materialization_fingerprint = models.CharField(
        max_length=64, blank=True, default='', db_index=True,
    )
    # A matching fingerprint must remain unchanged until this instant.  This
    # closes the ordinary multi-record sync window (including zero-price lines,
    # which a gross-only equality check cannot detect by itself).
    eligible_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_error = models.TextField(blank=True, default='')
    printed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at', 'pk']
        indexes = [
            models.Index(
                fields=['state', 'lease_expires_at'],
                name='receipt_print_claim_idx',
            ),
        ]

    def __str__(self):
        return f'ReceiptPrintJob<order={self.order_id} state={self.state}>'
