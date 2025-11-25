"""
Test transaction type configuration loading
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import PayPeriod
from reconciliation.engine import ReconciliationEngine

print("=" * 80)
print("TRANSACTION TYPE CONFIGURATION TEST")
print("=" * 80)

# Get a pay period
pay_period = PayPeriod.objects.first()

if pay_period:
    # Create engine instance to test configuration loading
    engine = ReconciliationEngine(pay_period)

    print("\nTransaction Types for Hours Calculation:")
    print("-" * 80)
    for tt in engine.allowed_transaction_types['hours']:
        print(f"  - {tt}")

    print("\nTransaction Types for Costs Calculation:")
    print("-" * 80)
    for tt in engine.allowed_transaction_types['costs']:
        print(f"  - {tt}")

    print(f"\nTotal Hours Types: {len(engine.allowed_transaction_types['hours'])}")
    print(f"Total Costs Types: {len(engine.allowed_transaction_types['costs'])}")

else:
    print("No pay period found")

print("\n" + "=" * 80)
