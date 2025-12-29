import os
import django
import requests

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import EmployeePayPeriodSnapshot

print("Generating all employee snapshots for 2025-11-30...")
print("This will create snapshots for all 848 employees with cost allocation rules.")

# Call the save-all-allocations API endpoint
url = 'http://127.0.0.1:8000/api/save-all-allocations/2025-11-30/'
response = requests.post(url, json={})

print(f"\nResponse status: {response.status_code}")
print(f"Response: {response.json()}")

# Check the result
snapshots = EmployeePayPeriodSnapshot.objects.filter(pay_period__period_id='2025-11-30')
print(f"\nAfter save: {snapshots.count()} employee snapshots")

total_cost = sum([s.total_cost or 0 for s in snapshots])
print(f"Total cost: ${total_cost:,.2f}")
