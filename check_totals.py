"""
Check what journal entries exist in the uploaded data
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import JournalEntry, Upload, PayPeriod
from decimal import Decimal

# Get the journal upload for 2025-11-16
pay_period = PayPeriod.objects.get(period_id='2025-11-16')
journal_upload = Upload.objects.filter(
    pay_period=pay_period,
    source_system='Micropay_Journal',
    is_active=True
).first()

if journal_upload:
    print(f'Journal Upload: {journal_upload.file_name}')
    print(f'Pay Period: {pay_period.period_id}')
    print()

    # Get all unique descriptions with their totals
    from django.db.models import Sum
    entries = JournalEntry.objects.filter(
        upload=journal_upload
    ).values('description').annotate(
        total_debit=Sum('debit'),
        total_credit=Sum('credit')
    ).order_by('description')

    print('All Journal Entry Descriptions in uploaded file:')
    print(f"{'Description':<45} {'Debit':>15} {'Credit':>15} {'Net':>15}")
    print('=' * 95)

    grand_total = Decimal('0')
    for entry in entries:
        debit = entry['total_debit'] or Decimal('0')
        credit = entry['total_credit'] or Decimal('0')
        net = debit - credit
        grand_total += net
        print(f'{entry["description"]:<45} ${debit:>13,.2f} ${credit:>13,.2f} ${net:>13,.2f}')

    print('=' * 95)
    print(f"{'GRAND TOTAL (all entries):':<45} {'':<15} {'':<15} ${grand_total:>13,.2f}")
else:
    print('No journal upload found for 2025-11-16')
