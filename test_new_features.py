"""
Test re-uploading journal file with fixed parser
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import Upload, PayPeriod, JournalEntry
from reconciliation.parsers import JournalParser
from reconciliation.file_detector import FileDetector
import pandas as pd
from django.conf import settings

# Get the pay period
pay_period = PayPeriod.objects.get(period_id='2025-11-16')

# Get the existing journal upload
old_upload = Upload.objects.filter(
    pay_period=pay_period,
    source_system='Micropay_Journal',
    is_active=True
).first()

if old_upload:
    print(f"Found existing upload: {old_upload.file_name}")
    print(f"Current record count: {old_upload.record_count}")
    
    # Delete old journal entries
    deleted_count = JournalEntry.objects.filter(upload=old_upload).delete()[0]
    print(f"Deleted {deleted_count} old journal entries")
    
    # Get the file path
    file_path = os.path.join(settings.MEDIA_ROOT, old_upload.file_path)
    print(f"Reading file: {file_path}")
    
    # Re-parse with the fixed parser
    df = pd.read_csv(file_path, low_memory=False)
    print(f"DataFrame has {len(df)} rows")
    
    # Parse again
    record_count = JournalParser.parse(old_upload, df)
    print(f"Created {record_count} new journal entries")
    
    # Update upload record
    old_upload.record_count = record_count
    old_upload.save()
    
    print("\nNow checking what descriptions we have:")
    from django.db.models import Sum
    entries = JournalEntry.objects.filter(
        upload=old_upload
    ).values('description').annotate(
        total_debit=Sum('debit'),
        total_credit=Sum('credit')
    ).order_by('description')
    
    print(f"\n{'Description':<45} {'Debit':>15} {'Credit':>15} {'Net':>15}")
    print('=' * 95)
    for entry in entries:
        from decimal import Decimal
        debit = entry['total_debit'] or Decimal('0')
        credit = entry['total_credit'] or Decimal('0')
        net = debit - credit
        print(f'{entry["description"]:<45} ${debit:>13,.2f} ${credit:>13,.2f} ${net:>13,.2f}')
else:
    print("No journal upload found")
