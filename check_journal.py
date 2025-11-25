"""
Check journal reconciliation data
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import JournalReconciliation, ReconciliationRun
from decimal import Decimal

# Get the latest recon run for 2025-11-16
recon_run = ReconciliationRun.objects.filter(
    pay_period__period_id='2025-11-16'
).order_by('-started_at').first()

if recon_run:
    print(f'Reconciliation Run: {recon_run.run_id}')
    print(f'Pay Period: {recon_run.pay_period.period_id}')
    print()

    # Get all journal reconciliations
    journals = JournalReconciliation.objects.filter(
        recon_run=recon_run
    ).order_by('-journal_net')

    print('All Journal Entries:')
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
    print()

    # Show only items marked with Y
    print('\nItems marked with Y (include_in_total_cost=True):')
    y_items = journals.filter(include_in_total_cost=True)
    for j in y_items:
        print(f'  {j.description:<45} ${j.journal_net:>13,.2f}')

    print(f'\nTotal items marked Y: {y_items.count()}')
    print(f'Total value marked Y: ${total_with_y:,.2f}')
else:
    print('No reconciliation run found for 2025-11-16')
