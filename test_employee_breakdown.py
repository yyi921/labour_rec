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

print("=== SIMULATING EMPLOYEE BREAKDOWN DOWNLOAD ===\n")

leave_type = 'Annual Leave'
gl_liability = '2310'

# Get ALL employees with closing balances
closing_employees = IQBLeaveBalance.objects.filter(
    upload=closing_upload,
    leave_type=leave_type
).values('employee_code').annotate(
    total_balance=Sum('balance_value'),
    total_loading=Sum('leave_loading')
).order_by('employee_code')

print(f"Total employees in breakdown: {closing_employees.count()}")

# Calculate totals from the breakdown
total_opening = Decimal('0')
total_closing = Decimal('0')
total_leave_taken = Decimal('0')

for emp_data in closing_employees:
    emp_code = emp_data['employee_code']
    
    # Closing
    closing_balance = emp_data['total_balance'] or Decimal('0')
    closing_loading = emp_data['total_loading'] or Decimal('0')
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

print(f"\nTotals from employee breakdown:")
print(f"  Opening Balance: ${total_opening:,.2f}")
print(f"  Closing Balance: ${total_closing:,.2f}")
print(f"  Leave Taken: ${total_leave_taken:,.2f}")

print(f"\nExpected (from HTML page):")
print(f"  Opening Balance: $2,355,755.82")
print(f"  Closing Balance: $2,338,345.22")
print(f"  Leave Taken: $150,982.91")

print(f"\nMatch: {total_opening == Decimal('2355755.82') and total_closing == Decimal('2338345.22') and total_leave_taken == Decimal('150982.91')}")
