import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import pandas as pd
from reconciliation.models import Upload, IQBLeaveBalance
from reconciliation.parsers import IQBLeaveBalanceParser
from datetime import datetime

# Load the file
file_path = 'media/uploads/Micropay_IQB_Leave_2025-11-16_v4_70ece963.csv'
df = pd.read_csv(file_path, low_memory=False)

print(f"File loaded: {len(df)} rows")

# Get the upload
upload = Upload.objects.get(upload_id='7afb0fa8c0c04e8a9df8267c23c956f3')
print(f"Upload found: {upload}")

# Try to parse
as_of_date = datetime.strptime('2025-11-16', '%Y-%m-%d').date()
print(f"Parsing with as_of_date: {as_of_date}")

try:
    record_count = IQBLeaveBalanceParser.parse(upload, df, as_of_date)
    print(f"SUCCESS! Parsed {record_count} records")

    # Update upload
    upload.record_count = record_count
    upload.status = 'completed'
    upload.save()
    print(f"Upload updated to completed status")

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
