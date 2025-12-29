import os
import django
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import (
    PayPeriod, EmployeePayPeriodSnapshot, JournalEntry, Upload,
    SageLocation, SageDepartment
)
from decimal import Decimal
from collections import defaultdict

# Simulate what the journal view does
def check_generated_journal(period_id):
    print(f"\n=== GENERATED JOURNAL ENTRIES FOR {period_id} ===")

    pay_period = PayPeriod.objects.get(period_id=period_id)

    # Get employee snapshots
    snapshots = EmployeePayPeriodSnapshot.objects.filter(pay_period=pay_period)
    print(f"Found {snapshots.count()} employee snapshots")

    if not snapshots.exists():
        print("ERROR: No employee snapshots found")
        return

    # Get journal upload
    journal_upload = Upload.objects.filter(
        pay_period=pay_period,
        source_system='Micropay_Journal',
        is_active=True
    ).first()

    if not journal_upload:
        print("ERROR: No journal upload found")
        return

    # Count total cost from snapshots
    total_snapshot_cost = Decimal('0')
    for snapshot in snapshots:
        if snapshot.total_cost:
            total_snapshot_cost += snapshot.total_cost

    print(f"Total cost from snapshots: ${total_snapshot_cost:,.2f}")

    # Count entries without cost allocation
    no_allocation = snapshots.filter(cost_allocation__isnull=True).count()
    empty_allocation = sum(1 for s in snapshots if s.cost_allocation == {})

    print(f"Snapshots without cost allocation: {no_allocation}")
    print(f"Snapshots with empty allocation: {empty_allocation}")

    # Check for snapshots that won't be allocated
    print("\nSampling snapshots with issues:")
    problem_snapshots = [s for s in snapshots if not s.cost_allocation or s.cost_allocation == {}]
    for s in problem_snapshots[:5]:  # Show first 5
        print(f"  Employee {s.employee_code} ({s.employee_name}): total_cost=${s.total_cost or 0}, allocation={s.cost_allocation}")

# Check both periods
check_generated_journal('2025-11-16')
check_generated_journal('2025-11-30')
