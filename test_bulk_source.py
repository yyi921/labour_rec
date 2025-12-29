import os
import django
import requests

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import CostAllocationRule

pay_period_id = '2025-11-30'

print("=== BEFORE BULK APPLY ===")
rules = CostAllocationRule.objects.filter(pay_period__period_id=pay_period_id)
print(f"Total employees: {rules.count()}")
print(f"IQB: {rules.filter(source='iqb').count()}")
print(f"Tanda: {rules.filter(source='tanda').count()}")
print(f"Override: {rules.filter(source='override').count()}")

print("\n=== APPLYING BULK SOURCE: TANDA ===")
url = f'http://127.0.0.1:8000/api/apply-bulk-source/{pay_period_id}/'
response = requests.post(url, json={'source': 'tanda'})

print(f"Response status: {response.status_code}")
print(f"Response: {response.json()}")

print("\n=== AFTER BULK APPLY ===")
rules = CostAllocationRule.objects.filter(pay_period__period_id=pay_period_id)
print(f"Total employees: {rules.count()}")
print(f"IQB: {rules.filter(source='iqb').count()}")
print(f"Tanda: {rules.filter(source='tanda').count()}")
print(f"Override: {rules.filter(source='override').count()}")

print("\n=== NOW TEST SAVE ALL ALLOCATIONS ===")
url = f'http://127.0.0.1:8000/api/save-all-allocations/{pay_period_id}/'
response = requests.post(url, json={})

print(f"Response status: {response.status_code}")
print(f"Response: {response.json()}")
