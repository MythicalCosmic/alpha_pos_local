"""Backfill branch_id onto order line items so the cloud finally receives them.

Order line items are created with bulk_create (customers/waiters order services),
which bypasses Model.save() — the place that stamps branch_id and marks a row
pending for the cloud push. So every historical OrderItem kept branch_id='' and
the sync sweep (which only sends THIS branch's rows) skipped them forever: the
cloud got order headers + payments but never the items. The services now stamp
branch_id going forward; this one-time data migration fixes the existing backlog.

Desktop-edition only (the `customers` app isn't installed on the cloud), and a
no-op on any install whose items are already stamped, so it's safe to re-run.
"""
from django.conf import settings
from django.db import migrations


def backfill_orderitem_branch_id(apps, schema_editor):
    bid = getattr(settings, 'BRANCH_ID', '') or ''
    if not bid:
        # No branch identity configured -> nothing meaningful to stamp; the push
        # sweep keys on the branch id, so leaving these untouched is correct.
        return
    OrderItem = apps.get_model('base', 'OrderItem')
    # synced_at=None re-marks them pending so the next sweep uploads the backlog.
    OrderItem.objects.filter(branch_id='').update(branch_id=bid, synced_at=None)


def noop_reverse(apps, schema_editor):
    # Irreversible data fix; nothing to undo (we never recorded the prior '' rows).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('base', '0031_customer_alter_rolepermission_role_alter_user_role_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_orderitem_branch_id, noop_reverse),
    ]
