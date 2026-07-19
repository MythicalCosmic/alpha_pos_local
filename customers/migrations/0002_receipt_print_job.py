from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


def suppress_historical_telegram_replay(apps, schema_editor):
    """Mark pre-feature Telegram orders handled instead of reprinting history."""
    Order = apps.get_model('base', 'Order')
    ReceiptPrintJob = apps.get_model('customers', 'ReceiptPrintJob')
    db_alias = schema_editor.connection.alias
    activated_at = timezone.now()

    order_ids = (Order.objects.using(db_alias)
                 .filter(order_origin='TELEGRAM', is_deleted=False)
                 .values_list('pk', flat=True)
                 .iterator(chunk_size=1000))
    batch = []
    for order_id in order_ids:
        batch.append(ReceiptPrintJob(
            order_id=order_id,
            state='PRINTED',
            printed_at=activated_at,
            last_error=(
                'Suppressed historical replay when durable auto-print was enabled.'
            ),
        ))
        if len(batch) >= 1000:
            ReceiptPrintJob.objects.using(db_alias).bulk_create(
                batch, ignore_conflicts=True,
            )
            batch = []
    if batch:
        ReceiptPrintJob.objects.using(db_alias).bulk_create(
            batch, ignore_conflicts=True,
        )


def initialize_print_activation(apps, schema_editor):
    ReceiptPrintPolicy = apps.get_model('customers', 'ReceiptPrintPolicy')
    ReceiptPrintPolicy.objects.using(schema_editor.connection.alias).get_or_create(
        pk=1,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('base', '0050_order_origin'),
        ('customers', '0001_backfill_orderitem_sync'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReceiptPrintPolicy',
            fields=[
                ('id', models.PositiveSmallIntegerField(
                    default=1, editable=False, primary_key=True,
                    serialize=False,
                )),
                ('activated_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='ReceiptPrintJob',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False,
                    verbose_name='ID',
                )),
                ('state', models.CharField(
                    choices=[
                        ('PENDING', 'Pending'),
                        ('CLAIMED', 'Claimed'),
                        ('PRINTED', 'Printed'),
                    ], db_index=True, default='PENDING', max_length=12,
                )),
                ('claim_token', models.UUIDField(
                    blank=True, null=True, unique=True,
                )),
                ('claimed_session_hash', models.CharField(
                    blank=True, db_index=True, default='', max_length=64,
                )),
                ('claimed_at', models.DateTimeField(blank=True, null=True)),
                ('lease_expires_at', models.DateTimeField(
                    blank=True, db_index=True, null=True,
                )),
                ('attempt_count', models.PositiveIntegerField(default=0)),
                ('materialization_fingerprint', models.CharField(
                    blank=True, db_index=True, default='', max_length=64,
                )),
                ('eligible_at', models.DateTimeField(
                    blank=True, db_index=True, null=True,
                )),
                ('last_error', models.TextField(blank=True, default='')),
                ('printed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('order', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='receipt_print_job', to='base.order',
                )),
            ],
            options={'ordering': ['created_at', 'pk']},
        ),
        migrations.AddIndex(
            model_name='receiptprintjob',
            index=models.Index(
                fields=['state', 'lease_expires_at'],
                name='receipt_print_claim_idx',
            ),
        ),
        migrations.RunPython(
            initialize_print_activation,
            migrations.RunPython.noop,
        ),
        # Existing installs may already hold months of synced Telegram orders.
        # Treat those as handled at activation so the first poll cannot empty a
        # paper roll by replaying history. New orders are materialized lazily.
        migrations.RunPython(
            suppress_historical_telegram_replay,
            migrations.RunPython.noop,
        ),
    ]
