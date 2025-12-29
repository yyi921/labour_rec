import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import Upload, IQBLeaveBalance, IQBDetail, PayCompCodeMapping
from django.db.models import Sum
from decimal import Decimal

# Get uploads
pay_period_id = '2025-11-16'
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

print(f"Opening upload: {opening_upload.pay_period.period_id if opening_upload else 'None'}")
print(f"Closing upload: {closing_upload.pay_period.period_id if closing_upload else 'None'}")
print(f"IQB upload: {iqb_upload.pay_period.period_id if iqb_upload else 'None'}")

# Check opening balance for Annual Leave
opening_total = IQBLeaveBalance.objects.filter(
    upload=opening_upload,
    leave_type='Annual Leave'
).aggregate(
    total_balance=Sum('balance_value'),
    total_loading=Sum('leave_loading')
)

print(f"\n=== OPENING BALANCE (Annual Leave) ===")
print(f"Balance Value: ${opening_total['total_balance']:,.2f}")
print(f"Leave Loading: ${opening_total['total_loading']:,.2f}")
print(f"TOTAL (with loading): ${(opening_total['total_balance'] + opening_total['total_loading']):,.2f}")

# Check closing balance for Annual Leave
closing_total = IQBLeaveBalance.objects.filter(
    upload=closing_upload,
    leave_type='Annual Leave'
).aggregate(
    total_balance=Sum('balance_value'),
    total_loading=Sum('leave_loading')
)

print(f"\n=== CLOSING BALANCE (Annual Leave) ===")
print(f"Balance Value: ${closing_total['total_balance']:,.2f}")
print(f"Leave Loading: ${closing_total['total_loading']:,.2f}")
print(f"TOTAL (with loading): ${(closing_total['total_balance'] + closing_total['total_loading']):,.2f}")

# Check leave taken - first check what comp codes map to 2310
print(f"\n=== PAYCOMP CODE MAPPING (GL 2310) ===")
mappings = PayCompCodeMapping.objects.filter(gl_account='2310')
for m in mappings:
    print(f"{m.pay_comp_code} -> {m.gl_account}")

# Check for the specific codes the user mentioned
print(f"\n=== CHECKING SPECIFIC COMP CODES ===")
check_codes = ['Annual', 'LLV', 'TPo93ALG', 'TPo93LLG']
for code in check_codes:
    mapping = PayCompCodeMapping.objects.filter(pay_comp_code=code).first()
    if mapping:
        print(f"{code} -> GL {mapping.gl_account}")
    else:
        print(f"{code} -> NOT FOUND IN MAPPING")

# Calculate leave taken using GL mapping method
print(f"\n=== LEAVE TAKEN (using GL mapping) ===")
paycomp_mappings = {m.pay_comp_code: m.gl_account for m in PayCompCodeMapping.objects.all()}
leave_taken_total = Decimal('0')

for record in IQBDetail.objects.filter(upload=iqb_upload):
    gl_account = paycomp_mappings.get(record.pay_comp_code)
    if gl_account == '2310':
        leave_taken_total += record.amount

print(f"Total leave taken (GL 2310): ${leave_taken_total:,.2f}")

# Calculate leave taken using specific comp codes
print(f"\n=== LEAVE TAKEN (using specific codes) ===")
specific_codes = ['Annual', 'LLV', 'TPo93ALG', 'TPo93LLG']
leave_taken_specific = IQBDetail.objects.filter(
    upload=iqb_upload,
    pay_comp_code__in=specific_codes
).aggregate(total=Sum('amount'))

print(f"Total leave taken (specific codes): ${leave_taken_specific['total']:,.2f}")

# Show all unique comp codes in IQB Detail
print(f"\n=== ALL COMP CODES IN IQB DETAIL ===")
unique_codes = IQBDetail.objects.filter(upload=iqb_upload).values_list('pay_comp_code', flat=True).distinct()
print(f"Unique comp codes: {sorted(set(unique_codes))}")
