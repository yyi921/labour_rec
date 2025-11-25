"""
Test filter issue in Cost Allocation View
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import CostAllocationRule, PayPeriod, IQBDetail, Upload

# Get pay period
pp = PayPeriod.objects.get(period_id='2025-11-16')

# Check all rules
all_rules = CostAllocationRule.objects.filter(pay_period=pp)
print(f"Total Rules Count: {all_rules.count()}")

if all_rules.count() > 0:
    print(f"\nFirst 5 employees:")
    for rule in all_rules[:5]:
        print(f"  {rule.employee_code} - {rule.employee_name} - Source: {rule.source}")
else:
    print("\nNO RULES FOUND!")

# Check IQB upload
iqb_upload = Upload.objects.filter(
    pay_period=pp,
    source_system='Micropay_IQB',
    is_active=True
).first()

if iqb_upload:
    print(f"\nIQB Upload found: {iqb_upload.file_name}")

    # Check employee with location 421
    include_types = ['Annual Leave', 'Auto Pay', 'Hours By Rate', 'Long Service Leave',
                     'Non Standard Add Before', 'Other Leave', 'Sick Leave',
                     'Standard Add Before', 'Super', 'Term ETP - Taxable (Code: O)',
                     'Term Post 93 AL Gross', 'Term Post 93 LL Gross', 'User Defined Leave']

    employees_with_421 = IQBDetail.objects.filter(
        upload=iqb_upload,
        transaction_type__in=include_types,
        cost_account_code__startswith='421-'
    ).values_list('employee_code', 'full_name').distinct()[:5]

    print(f"\nEmployees with cost accounts starting with 421-:")
    for emp_code, emp_name in employees_with_421:
        print(f"  {emp_code} - {emp_name}")
