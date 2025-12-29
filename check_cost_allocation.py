#!/usr/bin/env python
"""Check if cost allocation data exists for period 2025-11-30"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'labour_reconciliation.settings')
django.setup()

from reconciliation.models import ParsedData, PayPeriod

# Check the flag
pay_period = PayPeriod.objects.filter(period_id='2025-11-30').first()
print(f"\nPeriod: {pay_period.period_id}")
print(f"has_cost_allocation flag: {pay_period.has_cost_allocation}")

# Check if cost allocation data exists
records_with_iqb = ParsedData.objects.filter(
    pay_period__period_id='2025-11-30',
    iqb_cost_allocation__isnull=False
).count()

records_with_tanda = ParsedData.objects.filter(
    pay_period__period_id='2025-11-30',
    tanda_cost_allocation__isnull=False
).count()

print(f"\nRecords with IQB cost allocation: {records_with_iqb}")
print(f"Records with Tanda cost allocation: {records_with_tanda}")

if records_with_iqb > 0 or records_with_tanda > 0:
    print("\n⚠️  ISSUE: Cost allocation data exists but has_cost_allocation flag is False!")
    print("This explains why the dashboard shows 'Verify Tanda Mapping & Run Cost allocation'")
    print("instead of 'Cost Allocation View' and 'General Journal'")
else:
    print("\nNo cost allocation data found - cost allocation needs to be run.")
