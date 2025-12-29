import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import Upload, IQBLeaveBalance, IQBDetail, PayCompCodeMapping
from django.db.models import Sum
from decimal import Decimal

pay_period_id = '2025-11-16'

# Get uploads
closing_upload = Upload.objects.filter(
    pay_period__period_id=pay_period_id,
    source_system='Micropay_IQB_Leave',
    is_active=True
).first()

opening_upload = Upload.objects.filter(
    source_system='Micropay_IQB_Leave',
    is_active=True,
    pay_period__period_id__lt=pay_period_id
).order_by('-pay_period__period_id').first()

iqb_upload = Upload.objects.filter(
    pay_period__period_id=pay_period_id,
    source_system='Micropay_IQB',
    is_active=True
).first()

paycomp_mappings = {m.pay_comp_code: m.gl_account for m in PayCompCodeMapping.objects.all()}

print("=== TESTING FIXED EMPLOYEE BREAKDOWN LOGIC ===\n")

leave_type = 'Annual Leave'
gl_liability = '2310'

# Get ALL unique employee codes from both opening AND closing balances
closing_emp_codes = set(IQBLeaveBalance.objects.filter(
    upload=closing_upload,
    leave_type=leave_type
).values_list('employee_code', flat=True).distinct())

opening_emp_codes = set(IQBLeaveBalance.objects.filter(
    upload=opening_upload,
    leave_type=leave_type
).values_list('employee_code', flat=True).distinct())

all_employee_codes = sorted(closing_emp_codes | opening_emp_codes)

print(f"Employees with closing balance: {len(closing_emp_codes)}")
print(f"Employees with opening balance: {len(opening_emp_codes)}")
print(f"Total unique employees (union): {len(all_employee_codes)}")

# Calculate totals from the breakdown
total_opening = Decimal('0')
total_closing = Decimal('0')
total_leave_taken = Decimal('0')

for emp_code in all_employee_codes:
    # Closing
    closing_agg = IQBLeaveBalance.objects.filter(
        upload=closing_upload,
        employee_code=emp_code,
        leave_type=leave_type
    ).aggregate(
        total_balance=Sum('balance_value'),
        total_loading=Sum('leave_loading')
    )
    closing_balance = closing_agg['total_balance'] or Decimal('0')
    closing_loading = closing_agg['total_loading'] or Decimal('0')
    closing_value = closing_balance + closing_loading
    total_closing += closing_value

    # Opening
    opening_agg = IQBLeaveBalance.objects.filter(
        upload=opening_upload,
        employee_code=emp_code,
        leave_type=leave_type
    ).aggregate(
        total_balance=Sum('balance_value'),
        total_loading=Sum('leave_loading')
    )
    opening_balance = opening_agg['total_balance'] or Decimal('0')
    opening_loading = opening_agg['total_loading'] or Decimal('0')
    opening_value = opening_balance + opening_loading
    total_opening += opening_value

    # Leave taken
    leave_taken_records = IQBDetail.objects.filter(
        upload=iqb_upload,
        employee_code=emp_code
    )
    leave_taken = Decimal('0')
    for record in leave_taken_records:
        gl_account = paycomp_mappings.get(record.pay_comp_code)
        if gl_account == gl_liability:
            leave_taken += record.amount
    total_leave_taken += leave_taken

print(f"\nTotals from FIXED employee breakdown (including ALL employees):")
print(f"  Opening Balance: ${total_opening:,.2f}")
print(f"  Closing Balance: ${total_closing:,.2f}")
print(f"  Leave Taken: ${total_leave_taken:,.2f}")

print(f"\nExpected (from HTML page):")
print(f"  Opening Balance: $2,355,755.82")
print(f"  Closing Balance: $2,338,345.22")
print(f"  Leave Taken: $150,982.91")

# Check if they match
opening_match = abs(total_opening - Decimal('2355755.82')) < Decimal('0.01')
closing_match = abs(total_closing - Decimal('2338345.22')) < Decimal('0.01')
leave_taken_match = abs(total_leave_taken - Decimal('150982.91')) < Decimal('0.01')

print(f"\nMatch Results:")
print(f"  Opening Balance Match: {opening_match} {'PASS' if opening_match else 'FAIL'}")
print(f"  Closing Balance Match: {closing_match} {'PASS' if closing_match else 'FAIL'}")
print(f"  Leave Taken Match: {leave_taken_match} {'PASS' if leave_taken_match else 'FAIL'}")
print(f"  ALL MATCH: {opening_match and closing_match and leave_taken_match} {'PASS' if (opening_match and closing_match and leave_taken_match) else 'FAIL'}")
