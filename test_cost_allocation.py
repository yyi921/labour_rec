"""
Test cost allocation engine
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import PayPeriod
from reconciliation.cost_allocation import CostAllocationEngine
import json

print("=" * 80)
print("COST ALLOCATION TEST")
print("=" * 80)

# Get pay period
pay_period = PayPeriod.objects.filter(has_iqb=True, has_tanda=True).first()

if not pay_period:
    print("No pay period with both IQB and Tanda data")
    exit()

print(f"\nPay Period: {pay_period.period_id}")
print("-" * 80)

engine = CostAllocationEngine(pay_period)

# Test 1: Build from IQB
print("\n1. Building allocations from IQB...")
result_iqb = engine.build_allocations(source='iqb')

print("IQB Allocations:")
print(f"  Rules Created: {result_iqb['rules_created']}")
print(f"  Valid: {result_iqb['valid_rules']}")
print(f"  Invalid: {result_iqb['invalid_rules']}")

# Test 2: Build from Tanda
print("\n2. Building allocations from Tanda...")
result_tanda = engine.build_allocations(source='tanda')

print("Tanda Allocations:")
print(f"  Rules Created: {result_tanda['rules_created']}")
print(f"  Valid: {result_tanda['valid_rules']}")
print(f"  Invalid: {result_tanda['invalid_rules']}")

if result_tanda['mapping_errors']:
    print(f"\n  Mapping Errors:")
    for error in result_tanda['mapping_errors'][:5]:
        print(f"    {error['employee']}: {', '.join(error['unmapped_locations'])}")

# Test 3: Get verification data
print("\n3. Getting verification data (all departments)...")
verification = engine.get_verification_data()

print("Verification Data:")
print(f"  Employees: {verification['employee_count']}")

# Show sample employee
if verification['employees']:
    sample = verification['employees'][0]
    print(f"\n  Sample Employee: {sample['employee_name']}")
    print(f"    Total Cost: ${sample['total_cost']:,.2f}")
    print(f"    Source: {sample['source']}")
    print(f"    Valid: {sample['is_valid']}")
    
    print(f"\n    GL Breakdown:")
    for gl, amount in sample['gl_breakdown'].items():
        print(f"      {gl}: ${amount:,.2f}")
    
    print(f"\n    IQB Allocation:")
    for cc, pct in sample['iqb_allocation'].items():
        print(f"      {cc}: {pct}%")
    
    if sample['tanda_allocation']:
        print(f"\n    Tanda Allocation:")
        for cc, pct in sample['tanda_allocation'].items():
            print(f"      {cc}: {pct}%")
    
    print(f"\n    Current Allocation:")
    for cc, details in sample['current_allocation'].items():
        print(f"      {cc}: {details['percentage']}% (${details['amount']:,.2f})")

# Test 4: Department filter
print("\n4. Getting verification data for Food department (50)...")
verification_food = engine.get_verification_data(department_code='50')

print("Food Department:")
print(f"  Employees: {verification_food['employee_count']}")

if verification_food['employees']:
    for emp in verification_food['employees'][:3]:
        print(f"\n  {emp['employee_name']}:")
        print(f"    Total: ${emp['total_cost']:,.2f}")
        for cc, details in emp['current_allocation'].items():
            if cc.split('-')[1][:2] == '50':  # Only food cost centers
                print(f"      {cc}: {details['percentage']}%")

print("\n" + "=" * 80)
print("Test complete!")