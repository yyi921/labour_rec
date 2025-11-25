"""
Check IQB totals including superannuation
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import EmployeeReconciliation, PayPeriod
from django.db.models import Sum
from decimal import Decimal

# Get employee reconciliations for 2025-11-16
pay_period = PayPeriod.objects.get(period_id='2025-11-16')

totals = EmployeeReconciliation.objects.filter(
    pay_period=pay_period
).aggregate(
    iqb_total_cost=Sum('iqb_total_cost'),
    iqb_superannuation=Sum('iqb_superannuation')
)

iqb_total_cost = totals['iqb_total_cost'] or Decimal('0')
iqb_super = totals['iqb_superannuation'] or Decimal('0')
iqb_grand_total = iqb_total_cost + iqb_super

print('IQB Totals from Employee Reconciliation:')
print(f'  IQB Total Cost (excl. Super): ${iqb_total_cost:,.2f}')
print(f'  IQB Superannuation:           ${iqb_super:,.2f}')
print(f'  IQB Grand Total (with Super): ${iqb_grand_total:,.2f}')
print()

# Check journal total
from reconciliation.models import JournalReconciliation, ReconciliationRun

recon_run = ReconciliationRun.objects.filter(
    pay_period=pay_period
).order_by('-started_at').first()

if recon_run:
    journal_total = JournalReconciliation.objects.filter(
        recon_run=recon_run,
        include_in_total_cost=True
    ).aggregate(total=Sum('journal_net'))['total'] or Decimal('0')

    print('Journal Total (marked Y):')
    print(f'  Total: ${journal_total:,.2f}')
    print()
    
    variance = abs(iqb_grand_total - journal_total)
    print(f'Variance: ${variance:,.2f}')
    print(f'  IQB Grand Total:  ${iqb_grand_total:,.2f}')
    print(f'  Journal Total:    ${journal_total:,.2f}')
