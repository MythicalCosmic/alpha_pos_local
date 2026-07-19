"""Durable local receipt-print outbox for synced online orders."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import hashlib
import uuid

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Prefetch, Q
from django.utils import timezone

from base.models import Order, OrderItem
from customers.models import ReceiptPrintJob, ReceiptPrintPolicy


class PrintClaimConflict(Exception):
    """The acknowledgement does not own the job's current fenced claim."""


class PrintClaimNotFound(Exception):
    """No print job exists for the supplied opaque claim token."""


def _session_digest(session_key: str) -> str:
    return hashlib.sha256((session_key or '').encode('utf-8')).hexdigest()


def _lease_duration() -> timedelta:
    try:
        seconds = int(getattr(settings, 'TELEGRAM_PRINT_LEASE_SECONDS', 180))
    except (TypeError, ValueError):
        seconds = 180
    # Long enough for an ordinary print dialog/spool, bounded so a dead browser
    # cannot strand the ticket forever.
    return timedelta(seconds=max(30, min(seconds, 3600)))


def _materialization_settle_duration() -> timedelta:
    """How long a financially-complete item snapshot must stay unchanged."""
    try:
        seconds = float(getattr(
            settings, 'TELEGRAM_PRINT_MATERIALIZATION_SETTLE_SECONDS', 2,
        ))
    except (TypeError, ValueError):
        seconds = 2
    # A zero value is useful for deterministic tests.  Production's small
    # default covers the ordinary gap between records in one sync response
    # without making a cashier wait for the normal polling interval twice.
    return timedelta(seconds=max(0, min(seconds, 60)))


def _lock(queryset, *, skip_locked=False):
    if skip_locked and connection.features.has_select_for_update_skip_locked:
        return queryset.select_for_update(skip_locked=True)
    return queryset.select_for_update()


def _live_items_prefetch(prefix=''):
    return Prefetch(
        f'{prefix}items',
        queryset=OrderItem.objects.filter(is_deleted=False).order_by('uuid'),
        to_attr='_receipt_live_items',
    )


def _materialization_fingerprint(order) -> str:
    """Return explicit completeness evidence, or ``''`` while lines are partial.

    The canonical Order subtotal is the gross of product lines before order
    discounts and before non-product delivery/tip charges.  OrderItem.price is
    already the frozen unit price including size/topping add-ons, so the only
    correct checksum is ``sum(price * quantity) == subtotal``.  Comparing with
    total_amount would permanently block legitimate discounted/delivery orders.

    The fingerprint also contains every live line UUID and sync version.  A
    zero-priced/free line therefore changes the snapshot even though it does
    not change the gross, resetting the stability window when it arrives.
    """
    items = getattr(order, '_receipt_live_items', None)
    if items is None:
        items = list(order.items.filter(is_deleted=False).order_by('uuid'))
    if not items:
        return ''

    cent = Decimal('0.01')
    subtotal = Decimal(order.subtotal or 0).quantize(cent)
    gross = sum(
        (Decimal(item.price or 0) * int(item.quantity or 0) for item in items),
        Decimal('0.00'),
    ).quantize(cent)
    if gross != subtotal:
        return ''

    evidence = [f'subtotal={subtotal}']
    evidence.extend(
        ':'.join((
            str(item.uuid),
            str(item.sync_version),
            str(int(item.quantity or 0)),
            str(Decimal(item.price or 0).quantize(cent)),
        ))
        for item in items
    )
    return hashlib.sha256('|'.join(evidence).encode('utf-8')).hexdigest()


def _materialize_new_jobs(limit=250):
    """Create local jobs only once Telegram line gross proves completeness.

    Order and OrderItem are separate sync records. Claiming an Order before its
    lines arrive produces a partial kitchen receipt.  Presence alone is not
    enough: the live ``price * quantity`` gross must equal Order.subtotal.  The
    one-to-one constraint plus ``ignore_conflicts`` makes simultaneous pollers
    safe.
    """
    policy, _created = ReceiptPrintPolicy.objects.get_or_create(pk=1)
    orders = list(
        Order.objects.filter(
            order_origin=Order.Origin.TELEGRAM,
            is_deleted=False,
            items__is_deleted=False,
            created_at__gte=policy.activated_at,
        )
        .exclude(status=Order.Status.CANCELED)
        .filter(receipt_print_job__isnull=True)
        .order_by('created_at', 'pk')
        .prefetch_related(_live_items_prefetch())
        .distinct()[:limit]
    )
    now = timezone.now()
    eligible_at = now + _materialization_settle_duration()
    jobs = []
    for order in orders:
        fingerprint = _materialization_fingerprint(order)
        if fingerprint:
            jobs.append(ReceiptPrintJob(
                order_id=order.pk,
                materialization_fingerprint=fingerprint,
                eligible_at=eligible_at,
            ))
    if jobs:
        ReceiptPrintJob.objects.bulk_create(
            jobs, ignore_conflicts=True,
        )


def _refresh_pending_materialization(now, limit=250):
    """Reset eligibility whenever the visible independently-synced lines move."""
    candidates = (
        ReceiptPrintJob.objects.filter(
            Q(state=ReceiptPrintJob.State.PENDING)
            | Q(
                state=ReceiptPrintJob.State.CLAIMED,
                lease_expires_at__lte=now,
            )
            | Q(
                state=ReceiptPrintJob.State.CLAIMED,
                lease_expires_at__isnull=True,
            ),
            order__order_origin=Order.Origin.TELEGRAM,
            order__is_deleted=False,
        )
        .exclude(order__status=Order.Status.CANCELED)
        .select_related('order')
        .prefetch_related(_live_items_prefetch('order__'))
        .order_by('order__created_at', 'order_id')
    )
    jobs = list(_lock(candidates)[:limit])
    settle = _materialization_settle_duration()
    for job in jobs:
        fingerprint = _materialization_fingerprint(job.order)
        if fingerprint == job.materialization_fingerprint:
            continue
        job.materialization_fingerprint = fingerprint
        job.eligible_at = now + settle if fingerprint else None
        job.save(update_fields=[
            'materialization_fingerprint', 'eligible_at', 'updated_at',
        ])


def claim_next(*, session_key: str):
    """Return this POS session's active claim or atomically lease the next job."""
    owner = _session_digest(session_key)
    now = timezone.now()
    with transaction.atomic():
        _materialize_new_jobs()
        _refresh_pending_materialization(now)
        # Materialization stamps eligible_at with its own current timestamp.
        # Refresh now so the supported zero-settle test/dev mode can claim the
        # freshly-created row in this same request.
        now = timezone.now()

        # HTTP response loss must not create a second claim: an exact retry from
        # the same authenticated browser receives the same token and order.
        existing = (_lock(ReceiptPrintJob.objects)
                    .filter(
                        state=ReceiptPrintJob.State.CLAIMED,
                        claimed_session_hash=owner,
                        lease_expires_at__gt=now,
                        order__order_origin=Order.Origin.TELEGRAM,
                        order__is_deleted=False,
                    )
                    .exclude(order__status=Order.Status.CANCELED)
                    .select_related('order')
                    .order_by('claimed_at', 'pk')
                    .first())
        if existing is not None:
            return existing

        available = ReceiptPrintJob.objects.filter(
            Q(state=ReceiptPrintJob.State.PENDING)
            | Q(
                state=ReceiptPrintJob.State.CLAIMED,
                lease_expires_at__lte=now,
            )
            | Q(
                state=ReceiptPrintJob.State.CLAIMED,
                lease_expires_at__isnull=True,
            )
        ).filter(
            order__order_origin=Order.Origin.TELEGRAM,
            order__is_deleted=False,
            eligible_at__isnull=False,
            eligible_at__lte=now,
        ).exclude(
            materialization_fingerprint='',
        ).exclude(
            order__status=Order.Status.CANCELED,
        ).select_related('order').order_by('order__created_at', 'order_id')
        job = _lock(available, skip_locked=True).first()
        if job is None:
            return None

        job.state = ReceiptPrintJob.State.CLAIMED
        job.claim_token = uuid.uuid4()
        job.claimed_session_hash = owner
        job.claimed_at = now
        job.lease_expires_at = now + _lease_duration()
        job.attempt_count += 1
        job.save(update_fields=[
            'state', 'claim_token', 'claimed_session_hash', 'claimed_at',
            'lease_expires_at', 'attempt_count', 'updated_at',
        ])
        return job


def acknowledge(*, claim_token, session_key: str):
    """Durably stop delivery for a successfully printed receipt.

    Repeating the same acknowledgement is intentionally a 200-level no-op.
    """
    owner = _session_digest(session_key)
    with transaction.atomic():
        job = (_lock(ReceiptPrintJob.objects)
               .filter(claim_token=claim_token).first())
        if job is None:
            raise PrintClaimNotFound
        if job.claimed_session_hash != owner:
            raise PrintClaimConflict
        if job.state == ReceiptPrintJob.State.PRINTED:
            return job, True
        if job.state != ReceiptPrintJob.State.CLAIMED:
            raise PrintClaimConflict

        now = timezone.now()
        job.state = ReceiptPrintJob.State.PRINTED
        job.printed_at = now
        job.lease_expires_at = None
        job.last_error = ''
        job.save(update_fields=[
            'state', 'printed_at', 'lease_expires_at', 'last_error',
            'updated_at',
        ])
        return job, False


def release_failed(*, claim_token, session_key: str, error: str):
    """Release an unprinted claim for a later retry, fenced by its token."""
    owner = _session_digest(session_key)
    with transaction.atomic():
        job = (_lock(ReceiptPrintJob.objects)
               .filter(claim_token=claim_token).first())
        if job is None:
            raise PrintClaimNotFound
        if (
            job.state != ReceiptPrintJob.State.CLAIMED
            or job.claimed_session_hash != owner
        ):
            raise PrintClaimConflict

        job.state = ReceiptPrintJob.State.PENDING
        job.claim_token = None
        job.claimed_session_hash = ''
        job.claimed_at = None
        job.lease_expires_at = None
        job.last_error = (error or 'Printer reported failure').strip()[:1000]
        job.save(update_fields=[
            'state', 'claim_token', 'claimed_session_hash', 'claimed_at',
            'lease_expires_at', 'last_error', 'updated_at',
        ])
        return job
