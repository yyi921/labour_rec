"""
Re-run reconciliation with fixed journal data
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import PayPeriod
from reconciliation.engine import trigger_reconciliation

# Get the pay period
pay_period = PayPeriod.objects.get(period_id='2025-11-16')

print(f"Re-running reconciliation for {pay_period.period_id}...")
print()

# Run reconciliation
recon_run = trigger_reconciliation(pay_period)

print(f"\nReconciliation completed!")
print(f"Run ID: {recon_run.run_id}")
print(f"Status: {recon_run.status}")
print(f"Total checks: {recon_run.total_checks}")
print(f"Checks passed: {recon_run.checks_passed}")
print(f"Checks failed: {recon_run.checks_failed}")

# Check the journal reconciliation
from reconciliation.models import JournalReconciliation
from decimal import Decimal

journals = JournalReconciliation.objects.filter(
    recon_run=recon_run
).order_by('-journal_net')

print('\n\nJournal Reconciliation Results:')
print(f"{'Description':<45} {'Include?':<10} {'Debit':>15} {'Credit':>15} {'Net':>15}")
print('=' * 105)

total_with_y = Decimal('0')
for j in journals:
    include_flag = 'Y' if j.include_in_total_cost else 'N'
    print(f'{j.description:<45} {include_flag:<10} ${j.journal_debit:>13,.2f} ${j.journal_credit:>13,.2f} ${j.journal_net:>13,.2f}')
    if j.include_in_total_cost:
        total_with_y += j.journal_net

print('=' * 105)
print(f"{'Total (marked Y):':<45} {'':<10} {'':<15} {'':<15} ${total_with_y:>13,.2f}")

print(f'\n\nTotal items marked Y: {journals.filter(include_in_total_cost=True).count()}')
print(f'Total value marked Y: ${total_with_y:,.2f}')
