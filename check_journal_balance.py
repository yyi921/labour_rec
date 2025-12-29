import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import JournalReconciliation, PayPeriod, ReconciliationRun
from decimal import Decimal

def check_journal_balance(period_id):
    print(f"\n=== JOURNAL BALANCE CHECK FOR {period_id} ===")

    pp = PayPeriod.objects.get(period_id=period_id)
    recon = ReconciliationRun.objects.filter(pay_period=pp, status='completed').order_by('-completed_at').first()

    if not recon:
        print('No completed reconciliation run found')
        return

    journal_entries = JournalReconciliation.objects.filter(recon_run=recon)

    debit_total = Decimal('0')
    credit_total = Decimal('0')

    for j in journal_entries:
        if j.journal_debit:
            debit_total += j.journal_debit
        if j.journal_credit:
            credit_total += j.journal_credit

    balance = debit_total - credit_total

    print(f'Total Debits:  ${debit_total:,.2f}')
    print(f'Total Credits: ${credit_total:,.2f}')
    print(f'Balance:       ${balance:,.2f}')
    print(f'Entry Count:   {journal_entries.count()}')

    if balance != 0:
        print(f'\n[!] UNBALANCED by ${balance:,.2f}')

        # Show breakdown by GL account
        print('\nBreakdown by GL Account:')
        gl_breakdown = {}
        for j in journal_entries:
            gl = j.gl_account
            if gl not in gl_breakdown:
                gl_breakdown[gl] = {'debit': Decimal('0'), 'credit': Decimal('0')}
            if j.journal_debit:
                gl_breakdown[gl]['debit'] += j.journal_debit
            if j.journal_credit:
                gl_breakdown[gl]['credit'] += j.journal_credit

        for gl, amounts in sorted(gl_breakdown.items()):
            gl_balance = amounts['debit'] - amounts['credit']
            if gl_balance != 0:
                print(f"  GL {gl}: Debit ${amounts['debit']:,.2f}, Credit ${amounts['credit']:,.2f}, Balance ${gl_balance:,.2f}")
    else:
        print('\n[OK] Journal is balanced')

# Check both periods
check_journal_balance('2025-11-16')
check_journal_balance('2025-11-30')
