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

print("=== TESTING NEW CALC_TOTALS LOGIC ===\n")

# Annual Leave totals
leave_type = 'Annual Leave'
gl_liability = '2310'

# Opening balance total (ALL employees)
opening_agg = IQBLeaveBalance.objects.filter(
    upload=opening_upload,
    leave_type=leave_type
).aggregate(
    total_balance=Sum('balance_value'),
    total_loading=Sum('leave_loading')
)
total_opening = (opening_agg['total_balance'] or Decimal('0')) + (opening_agg['total_loading'] or Decimal('0'))

# Closing balance total (ALL employees)
closing_agg = IQBLeaveBalance.objects.filter(
    upload=closing_upload,
    leave_type=leave_type
).aggregate(
    total_balance=Sum('balance_value'),
    total_loading=Sum('leave_loading')
)
total_closing = (closing_agg['total_balance'] or Decimal('0')) + (closing_agg['total_loading'] or Decimal('0'))

# Leave taken total (ALL employees)
total_leave_taken = Decimal('0')
for record in IQBDetail.objects.filter(upload=iqb_upload):
    gl_account = paycomp_mappings.get(record.pay_comp_code)
    if gl_account == gl_liability:
        total_leave_taken += record.amount

print(f"Annual Leave - Opening Balance: ${total_opening:,.2f}")
print(f"Annual Leave - Closing Balance: ${total_closing:,.2f}")
print(f"Annual Leave - Leave Taken: ${total_leave_taken:,.2f}")
print(f"\nExpected:")
print(f"  Opening: $2,355,755.82")
print(f"  Closing: $2,338,345.22")
print(f"  Leave Taken: $150,982.91")
