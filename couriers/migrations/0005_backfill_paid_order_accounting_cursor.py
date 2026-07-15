from django.db import migrations
from django.db.models.functions import Now


def backfill_paid_order_accounting_cursor(apps, schema_editor):
    """Stamp paid headers repaired after the core cursor backfill."""
    Order = apps.get_model('base', 'Order')
    Order.objects.filter(
        is_paid=True,
        paid_at__isnull=False,
        accounting_recorded_at__isnull=True,
    ).update(accounting_recorded_at=Now())


class Migration(migrations.Migration):

    dependencies = [
        ('base', '0046_accounting_recorded_cursor'),
        ('couriers', '0004_migrate_refunds_to_order_ledger'),
    ]

    operations = [
        migrations.RunPython(
            backfill_paid_order_accounting_cursor,
            migrations.RunPython.noop,
        ),
    ]
