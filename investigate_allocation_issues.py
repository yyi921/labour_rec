"""
Investigate allocation issues
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import PayPeriod, CostAllocationRule, LocationMapping
from reconciliation.cost_allocation import CostAllocationEngine

# Get pay period
pay_period = PayPeriod.objects.get(period_id='2025-11-16')
engine = CostAllocationEngine(pay_period)

print("=" * 80)
print("ALLOCATION ISSUES INVESTIGATION")
print("=" * 80)

# 1. Check IQB invalid rules
print("\n1. INVALID IQB ALLOCATIONS (13 cases)")
print("-" * 80)

# Build IQB allocations first
engine.build_allocations(source='iqb')

invalid_iqb = CostAllocationRule.objects.filter(
    pay_period=pay_period,
    source='iqb',
    is_valid=False
)

print(f"Found {invalid_iqb.count()} invalid IQB allocation rules:\n")

for rule in invalid_iqb:
    print(f"Employee: {rule.employee_name} ({rule.employee_code})")
    print(f"  Total Percentage: {rule.total_percentage}%")
    print(f"  Validation Errors: {rule.validation_errors}")
    print(f"  Allocations:")
    for cost_account, details in rule.allocations.items():
        print(f"    {cost_account}: {details['percentage']}% (${details['amount']:,.2f})")
    print()

# 2. Check Tanda invalid rules
print("\n2. INVALID TANDA ALLOCATIONS (15 cases)")
print("-" * 80)

# Build Tanda allocations
result_tanda = engine.build_allocations(source='tanda')

invalid_tanda = CostAllocationRule.objects.filter(
    pay_period=pay_period,
    source='tanda',
    is_valid=False
)

print(f"Found {invalid_tanda.count()} invalid Tanda allocation rules:\n")

for rule in invalid_tanda:
    print(f"Employee: {rule.employee_name} ({rule.employee_code})")
    print(f"  Total Percentage: {rule.total_percentage}%")
    print(f"  Validation Errors: {rule.validation_errors}")
    print(f"  Allocations:")
    for cost_account, details in rule.allocations.items():
        print(f"    {cost_account}: {details['percentage']}% (${details['amount']:,.2f})")
    print()

# 3. Check mapping errors in detail
print("\n3. TANDA MAPPING ERRORS (2 employees)")
print("-" * 80)

if result_tanda['mapping_errors']:
    for error in result_tanda['mapping_errors']:
        employee = error['employee']
        unmapped = error['unmapped_locations']
        
        print(f"\nEmployee: {employee}")
        print(f"  Unmapped Locations/Teams:")
        for loc in unmapped:
            print(f"    - {loc}")
        
        # Check if these locations exist in our mapping file
        print(f"\n  Checking mapping database:")
        for loc in unmapped:
            exists = LocationMapping.objects.filter(tanda_location=loc).exists()
            if exists:
                mapping = LocationMapping.objects.get(tanda_location=loc)
                print(f"    {loc}: EXISTS but is_active={mapping.is_active}")
            else:
                # Try to find similar mappings
                parts = loc.split(' - ')
                if len(parts) == 2:
                    location_name = parts[0]
                    team_name = parts[1]
                    similar = LocationMapping.objects.filter(
                        tanda_location__icontains=location_name
                    )[:3]
                    if similar.exists():
                        print(f"    {loc}: NOT FOUND. Similar locations:")
                        for s in similar:
                            print(f"      - {s.tanda_location} -> {s.cost_account_code}")
                    else:
                        print(f"    {loc}: NOT FOUND. No similar locations.")

print("\n" + "=" * 80)
print("RECOMMENDATIONS:")
print("=" * 80)

print("\nFor Invalid Allocations:")
print("  - These are likely due to rounding errors where percentages don't add to 100%")
print("  - The validation tolerance is very strict (must be between 99.99% and 100.01%)")
print("  - These can be safely ignored or the tolerance can be adjusted")

print("\nFor Mapping Errors:")
print("  - Add missing location/team combinations to location_and_team_report.csv")
print("  - Re-run load_location_mapping.py")
print("  - Or manually create LocationMapping entries in Django admin")

print("\n" + "=" * 80)
