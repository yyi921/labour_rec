import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import PayPeriod, EmployeePayPeriodSnapshot, CostAllocationRule
import json
import requests

# Test saving an override with EMPTY data for employee 111742
pay_period_id = '2025-11-30'
employee_code = '111742'

# Try to save with override but empty override data (simulating selecting Override radio without entering data)
print("=== ATTEMPTING SAVE WITH OVERRIDE BUT NO DATA ===")
changes = [{
    'employee_code': employee_code,
    'source': 'override',
    # No 'override' key - simulating empty override input
}]

url = f'http://127.0.0.1:8000/api/save-cost-allocations/{pay_period_id}/'
response = requests.post(url, json={'changes': changes})

print(f"Response status: {response.status_code}")
print(f"Response body: {response.text}")

# Check after save
print("\n=== AFTER SAVE ===")
snapshot = EmployeePayPeriodSnapshot.objects.filter(
    employee_code=employee_code,
    pay_period__period_id=pay_period_id
).first()

if snapshot:
    print(f"Snapshot source: {snapshot.allocation_source}")
    print(f"Snapshot cost_allocation: {snapshot.cost_allocation}")
else:
    print("No snapshot found")

rule = CostAllocationRule.objects.filter(
    employee_code=employee_code,
    pay_period__period_id=pay_period_id
).first()

if rule:
    print(f"Rule source: {rule.source}")
    print(f"Rule allocations: {rule.allocations}")
else:
    print("No rule found")
