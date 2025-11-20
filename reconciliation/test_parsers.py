"""
Test script for file parsers
Run with: python manage.py shell -c "exec(open('reconciliation/test_parsers.py').read())"
"""
from reconciliation.file_detector import FileDetector
from reconciliation.parsers import TandaParser, IQBParser, JournalParser
from reconciliation.models import Upload, PayPeriod
from reconciliation.upload_handler import UploadHandler
from django.contrib.auth.models import User
import os

# Get or create test user
user, _ = User.objects.get_or_create(
    username='test_user',
    defaults={'email': 'test@example.com'}
)

# Test files
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Test with the uploaded files
test_files = [
    ('Tanda', r'C:\Users\yuany\OneDrive\Desktop\labour_reconciliation\media\test_data\Tanda_Timesheet Report by Hours, $, Export Name and Location (16).csv'),
    ('IQB', r'C:\Users\yuany\OneDrive\Desktop\labour_reconciliation\media\test_data\Micropay_TSV IQB-RET002 FNE 20251102 FN2.csv'),
    ('Journal', r'C:\Users\yuany\OneDrive\Desktop\labour_reconciliation\media\test_data\Micropay_TSV GL Batch FNE 20250907 FN2.csv'),
]

print("=" * 80)
print("FILE PARSER TEST")
print("=" * 80)

for name, filepath in test_files:
    print(f"\nTesting: {name}")
    print("-" * 80)
    
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        continue
    
    # Detect file type
    file_type, confidence, df = FileDetector.detect_file_type(filepath)
    print(f"File Type: {file_type} (Confidence: {confidence*100:.1f}%)")
    
    if df is None or file_type == 'Unknown':
        print("Skipping - could not detect file type")
        continue
    
    # Extract period
    period_info = FileDetector.extract_period(file_type, df, filepath)
    if not period_info:
        print("Skipping - could not extract period")
        continue

    # Print period information (Journal files don't have start date)
    if period_info.get('period_start'):
        print(f"Period: {period_info['period_start']} to {period_info['period_end']}")
    else:
        print(f"Period End: {period_info['period_end']}")
    
    # Get or create pay period
    pay_period, created = PayPeriod.objects.get_or_create(
        period_id=period_info['period_id'],
        defaults={
            'period_start': period_info['period_start'],
            'period_end': period_info['period_end'],
        }
    )
    print(f"Pay Period: {pay_period} ({'created' if created else 'existing'})")

    # Create upload record (with versioning - will supersede existing uploads)
    upload = UploadHandler.create_upload(
        pay_period=pay_period,
        source_system=file_type,
        file_name=os.path.basename(filepath),
        file_path=filepath,
        uploaded_by=user
    )
    print(f"Upload ID: {upload.upload_id} (v{upload.version})")
    
    # Parse based on file type
    try:
        if file_type == 'Tanda_Timesheet':
            count = TandaParser.parse(upload, df)
            print(f"✓ Parsed {count} Tanda timesheet records")
            
        elif file_type == 'Micropay_IQB':
            count = IQBParser.parse(upload, df)
            print(f"✓ Parsed {count} IQB detail records")
            
        elif file_type == 'Micropay_Journal':
            count = JournalParser.parse(upload, df)
            print(f"✓ Parsed {count} journal entry records")
        
        # Update upload status
        upload.record_count = count
        upload.status = 'completed'
        upload.save()
        
        print(f"✓ Upload status: {upload.status}")
        
    except Exception as e:
        print(f"✗ Error parsing file: {e}")
        upload.status = 'failed'
        upload.error_message = str(e)
        upload.save()
    
    print("=" * 80)

# Show summary
from reconciliation.models import TandaTimesheet, IQBDetail, JournalEntry

print("\nDatabase Summary:")
print(f"  Tanda Records: {TandaTimesheet.objects.count()}")
print(f"  IQB Records: {IQBDetail.objects.count()}")
print(f"  Journal Records: {JournalEntry.objects.count()}")
print(f"  Uploads: {Upload.objects.count()}")
print(f"  Pay Periods: {PayPeriod.objects.count()}")

print("\nTest complete!")