"""
Journal generation views
Generates prorated journal entries from Micropay_Journal based on Employee Pay Period Snapshots
"""
import csv
import os
from decimal import Decimal
from collections import defaultdict
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.db.models import Sum
from reconciliation.models import (
    PayPeriod, EmployeePayPeriodSnapshot, JournalEntry, Upload,
    SageLocation, SageDepartment
)


def load_journal_mapping():
    """Load the Micropay_journal_mapping.csv file"""
    csv_path = os.path.join(settings.BASE_DIR, 'data', 'Micropay_journal_mapping.csv')

    mapping = {}
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('GL Account'):
                gl_account = row['GL Account'].strip()
                mapping[gl_account] = {
                    'description': row['Description'],
                    'needs_proration': row.get('Total Cost', '').strip() == 'Y'
                }

    return mapping


def generate_journal(request, pay_period_id):
    """
    Generate prorated journal entries for the pay period
    Takes Micropay_Journal entries and prorates labour GLs by location/department
    """
    pay_period = get_object_or_404(PayPeriod, period_id=pay_period_id)

    # Get employee snapshots
    snapshots = EmployeePayPeriodSnapshot.objects.filter(pay_period=pay_period)

    if not snapshots.exists():
        return render(request, 'reconciliation/journal_error.html', {
            'pay_period': pay_period,
            'error': 'No employee snapshots found. Please save cost allocations first.'
        })

    # Get Micropay journal entries
    journal_upload = Upload.objects.filter(
        pay_period=pay_period,
        source_system='Micropay_Journal',
        is_active=True
    ).first()

    if not journal_upload:
        return render(request, 'reconciliation/journal_error.html', {
            'pay_period': pay_period,
            'error': 'No Micropay Journal file uploaded for this pay period.'
        })

    journal_entries = JournalEntry.objects.filter(upload=journal_upload)

    # Load journal mapping
    journal_mapping = load_journal_mapping()

    # Get location and department names
    location_names = {loc.location_id: loc.location_name for loc in SageLocation.objects.all()}
    department_names = {dept.department_id: dept.department_name for dept in SageDepartment.objects.all()}

    # Map GL field names to GL account numbers (remove minus sign for matching)
    gl_field_to_account = {
        'gl_2310_annual_leave': '2310',
        'gl_2317_long_service_leave': '2317',
        'gl_2318_toil_liability': '2318',
        'gl_2320_sick_leave': '2320',
        'gl_6302': '6302',
        'gl_6305': '6305',
        'gl_6309': '6309',
        'gl_6310': '6310',
        'gl_6312': '6312',
        'gl_6315': '6315',
        'gl_6325': '6325',
        'gl_6330': '6330',
        'gl_6331': '6331',
        'gl_6332': '6332',
        'gl_6335': '6335',
        'gl_6338': '6338',
        'gl_6340': '6340',
        'gl_6345_salaries': '6345',
        'gl_6350': '6350',
        'gl_6355_sick_leave': '6355',
        'gl_6370_superannuation': '6370',
        'gl_6372_toil': '6372',
        'gl_6375': '6375',
        'gl_6380': '6380',
    }

    # Structure: {(location, department, gl_account): {'debit': amount, 'credit': amount, 'description': str}}
    prorated_entries = defaultdict(lambda: {'debit': Decimal('0'), 'credit': Decimal('0'), 'description': ''})
    non_prorated_entries = []

    # Process journal entries
    for journal in journal_entries:
        ledger_account = journal.ledger_account.strip()

        # Determine GL account (remove minus sign for 6xxx accounts)
        if ledger_account.startswith('-'):
            gl_account = ledger_account[1:]  # Remove minus sign
            is_credit = True
        else:
            # For accounts like "100-10-2310", extract the last part
            if '-' in ledger_account:
                gl_account = ledger_account.split('-')[-1]
            else:
                gl_account = ledger_account
            is_credit = False

        # Check if this GL needs proration
        needs_proration = journal_mapping.get(gl_account, {}).get('needs_proration', False)
        description = journal_mapping.get(gl_account, {}).get('description', f'GL {gl_account}')

        amount = journal.debit if journal.debit else Decimal('0')

        if needs_proration and amount > 0:
            # Prorate this amount across employee allocations
            # Get total amount for this GL across all employees
            total_gl_amount = Decimal('0')
            field_name = None

            # Find matching field
            for fname, acc in gl_field_to_account.items():
                if acc == gl_account:
                    field_name = fname
                    total_gl_amount = snapshots.aggregate(
                        total=Sum(fname)
                    )['total'] or Decimal('0')
                    break

            if field_name and total_gl_amount > 0:
                # Prorate across each employee's allocation
                for snapshot in snapshots:
                    employee_gl_amount = getattr(snapshot, field_name, Decimal('0'))

                    if employee_gl_amount > 0:
                        # Calculate this employee's share of the journal amount
                        employee_share = amount * (employee_gl_amount / total_gl_amount)

                        # Distribute across employee's cost allocation
                        cost_allocation = snapshot.cost_allocation
                        if cost_allocation:
                            for location_id, departments in cost_allocation.items():
                                for dept_id, percentage in departments.items():
                                    allocated_amount = employee_share * (Decimal(str(percentage)) / Decimal('100'))

                                    key = (location_id, dept_id, gl_account)
                                    if is_credit:
                                        prorated_entries[key]['credit'] += allocated_amount
                                    else:
                                        prorated_entries[key]['debit'] += allocated_amount
                                    prorated_entries[key]['description'] = description
        else:
            # Non-prorated entry - add as is
            non_prorated_entries.append({
                'location_id': '',
                'location_name': '',
                'department_id': '',
                'department_name': '',
                'gl_account': gl_account,
                'description': description,
                'cost_center': '',
                'debit': amount if not is_credit else Decimal('0'),
                'credit': amount if is_credit else Decimal('0'),
            })

    # Build consolidated entries list
    consolidated_entries = []

    # Add prorated entries
    for (location_id, dept_id, gl_account), amounts in sorted(prorated_entries.items()):
        location_name = location_names.get(location_id, location_id)
        dept_name = department_names.get(dept_id, dept_id)
        cost_center = f'{location_id}-{dept_id}00'

        consolidated_entries.append({
            'location_id': location_id,
            'location_name': location_name,
            'department_id': dept_id,
            'department_name': dept_name,
            'gl_account': gl_account,
            'description': amounts['description'],
            'cost_center': cost_center,
            'debit': amounts['debit'],
            'credit': amounts['credit'],
        })

    # Add non-prorated entries
    consolidated_entries.extend(non_prorated_entries)

    # Calculate totals
    total_debits = sum(entry['debit'] for entry in consolidated_entries)
    total_credits = sum(entry['credit'] for entry in consolidated_entries)

    context = {
        'pay_period': pay_period,
        'entries': consolidated_entries,
        'total_debits': total_debits,
        'total_credits': total_credits,
        'balanced': abs(total_debits - total_credits) < Decimal('0.01'),
        'employee_count': snapshots.count(),
        'journal_entry_count': len(consolidated_entries)
    }

    return render(request, 'reconciliation/journal_generated.html', context)


def download_journal_sage(request, pay_period_id):
    """Download journal in Sage Intacct format"""
    pay_period = get_object_or_404(PayPeriod, period_id=pay_period_id)

    # Generate journal entries
    snapshots = EmployeePayPeriodSnapshot.objects.filter(pay_period=pay_period)
    journal_upload = Upload.objects.filter(
        pay_period=pay_period,
        source_system='Micropay_Journal',
        is_active=True
    ).first()

    journal_entries_from_db = JournalEntry.objects.filter(upload=journal_upload) if journal_upload else []
    journal_mapping = load_journal_mapping()

    # GL field mapping
    gl_field_to_account = {
        'gl_2310_annual_leave': '2310',
        'gl_2317_long_service_leave': '2317',
        'gl_2318_toil_liability': '2318',
        'gl_2320_sick_leave': '2320',
        'gl_6302': '6302',
        'gl_6305': '6305',
        'gl_6309': '6309',
        'gl_6310': '6310',
        'gl_6312': '6312',
        'gl_6315': '6315',
        'gl_6325': '6325',
        'gl_6330': '6330',
        'gl_6331': '6331',
        'gl_6332': '6332',
        'gl_6335': '6335',
        'gl_6338': '6338',
        'gl_6340': '6340',
        'gl_6345_salaries': '6345',
        'gl_6350': '6350',
        'gl_6355_sick_leave': '6355',
        'gl_6370_superannuation': '6370',
        'gl_6372_toil': '6372',
        'gl_6375': '6375',
        'gl_6380': '6380',
    }

    # Get GL accounts that exist in snapshots (need proration)
    gl_accounts_to_prorate = set()
    for field_name in gl_field_to_account.keys():
        total = snapshots.aggregate(total=Sum(field_name))['total'] or Decimal('0')
        if total > 0:
            gl_accounts_to_prorate.add(gl_field_to_account[field_name])

    # Structure: list of journal line dictionaries
    journal_lines = []

    # Common values
    journal_id = f"PAYROLL-{pay_period_id}"
    date = pay_period.period_end.strftime('%m/%d/%Y')
    description = f"Payroll journal ending {pay_period.period_end.strftime('%Y-%m-%d')}"

    # 1. Generate prorated entries from employee snapshots
    prorated_entries = defaultdict(Decimal)  # {(location, dept, gl): amount}

    for snapshot in snapshots:
        cost_allocation = snapshot.cost_allocation
        if not cost_allocation:
            continue

        for field_name, gl_account in gl_field_to_account.items():
            if gl_account not in gl_accounts_to_prorate:
                continue

            gl_amount = getattr(snapshot, field_name, Decimal('0'))
            if not gl_amount or gl_amount == 0:
                continue

            # Distribute across cost allocation
            for location_id, departments in cost_allocation.items():
                for dept_id, percentage in departments.items():
                    allocated_amount = gl_amount * (Decimal(str(percentage)) / Decimal('100'))
                    key = (location_id, dept_id, gl_account)
                    prorated_entries[key] += allocated_amount

    # Add prorated entries to journal lines
    for (location_id, dept_id, gl_account), amount in sorted(prorated_entries.items()):
        gl_desc = journal_mapping.get(gl_account, {}).get('description', f'GL {gl_account}')
        memo = f"{description} {gl_account} {gl_desc}"

        # Handle Location 700 special case
        acct_no = gl_account
        final_location = location_id
        billable = ''
        item_id = ''
        project_id = ''
        customer_id = ''

        if location_id == '700':
            acct_no = '1180'
            final_location = '10'
            billable = 'T'
            item_id = 'ICO-RECHARGE'
            project_id = 'CMG110-001'
            customer_id = 'CMG110'

        journal_lines.append({
            'acct_no': acct_no,
            'location_id': final_location,
            'dept_id': dept_id,
            'document': 'IQB',
            'memo': memo,
            'debit': amount,
            'billable': billable,
            'item_id': item_id,
            'project_id': project_id,
            'customer_id': customer_id
        })

    # 2. Add non-prorated entries from Micropay_Journal
    for journal in journal_entries_from_db:
        ledger_account = journal.ledger_account.strip()

        # Determine GL account
        if ledger_account.startswith('-'):
            gl_account = ledger_account[1:]
        else:
            if '-' in ledger_account:
                gl_account = ledger_account.split('-')[-1]
            else:
                gl_account = ledger_account

        # Skip if this GL is prorated (already handled above)
        if gl_account in gl_accounts_to_prorate:
            continue

        amount = journal.debit if journal.debit else Decimal('0')
        gl_desc = journal_mapping.get(gl_account, {}).get('description', f'GL {gl_account}')
        memo = f"{description} {gl_account} {gl_desc}"

        # Parse location/dept from cost_account if available
        location_id = ''
        dept_id = ''
        if journal.cost_account and '-' in journal.cost_account:
            parts = journal.cost_account.split('-')
            location_id = parts[0]
            if len(parts) > 1 and len(parts[1]) >= 2:
                dept_id = parts[1][:2]

        # Handle Location 700 special case
        acct_no = gl_account
        final_location = location_id
        billable = ''
        item_id = ''
        project_id = ''
        customer_id = ''

        if location_id == '700':
            acct_no = '1180'
            final_location = '10'
            billable = 'T'
            item_id = 'ICO-RECHARGE'
            project_id = 'CMG110-001'
            customer_id = 'CMG110'

        journal_lines.append({
            'acct_no': acct_no,
            'location_id': final_location,
            'dept_id': dept_id,
            'document': 'GL-Batch',
            'memo': memo,
            'debit': amount,
            'billable': billable,
            'item_id': item_id,
            'project_id': project_id,
            'customer_id': customer_id
        })

    # 3. Add balancing entry (reverse total to make sum = 0)
    total_debits = sum(line['debit'] for line in journal_lines)
    if abs(total_debits) > Decimal('0.01'):
        journal_lines.append({
            'acct_no': '2350',  # Payroll clearing account
            'location_id': '100',
            'dept_id': '10',
            'document': 'GL-Batch',
            'memo': f"{description} Payroll Liab - Net Wages Clearing",
            'debit': -total_debits,
            'billable': '',
            'item_id': '',
            'project_id': '',
            'customer_id': ''
        })

    # Create CSV response in Sage Intacct format
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="journal_sage_{pay_period_id}.csv"'

    writer = csv.writer(response)

    # Write header row
    writer.writerow([
        'DONOTIMPORT', 'JOURNAL', 'DATE', 'DESCRIPTION', 'REFERENCE_NO', 'LINE_NO',
        'ACCT_NO', 'LOCATION_ID', 'DEPT_ID', 'DOCUMENT', 'MEMO', 'DEBIT',
        'BILLABLE', 'GLENTRY_ITEMID', 'GLENTRY_PROJECTID', 'GLENTRY_CUSTOMERID'
    ])

    # Write data rows
    line_no = 1
    for line in journal_lines:
        donotimport = '#' if line['debit'] == 0 else ''
        debit_formatted = f"{line['debit']:.2f}"

        writer.writerow([
            donotimport,
            journal_id,
            date,
            description,
            '',  # REFERENCE_NO (blank)
            line_no,
            line['acct_no'],
            line['location_id'],
            line['dept_id'],
            line['document'],
            line['memo'],
            debit_formatted,
            line['billable'],
            line['item_id'],
            line['project_id'],
            line['customer_id']
        ])
        line_no += 1

    return response


def download_journal(request, pay_period_id):
    """Download journal as CSV file (simple format)"""
    pay_period = get_object_or_404(PayPeriod, period_id=pay_period_id)

    # Get employee snapshots
    snapshots = EmployeePayPeriodSnapshot.objects.filter(pay_period=pay_period)

    # Get Micropay journal entries
    journal_upload = Upload.objects.filter(
        pay_period=pay_period,
        source_system='Micropay_Journal',
        is_active=True
    ).first()

    journal_entries = JournalEntry.objects.filter(upload=journal_upload)
    journal_mapping = load_journal_mapping()
    location_names = {loc.location_id: loc.location_name for loc in SageLocation.objects.all()}
    department_names = {dept.department_id: dept.department_name for dept in SageDepartment.objects.all()}

    gl_field_to_account = {
        'gl_2310_annual_leave': '2310',
        'gl_2317_long_service_leave': '2317',
        'gl_2318_toil_liability': '2318',
        'gl_2320_sick_leave': '2320',
        'gl_6302': '6302',
        'gl_6305': '6305',
        'gl_6309': '6309',
        'gl_6310': '6310',
        'gl_6312': '6312',
        'gl_6315': '6315',
        'gl_6325': '6325',
        'gl_6330': '6330',
        'gl_6331': '6331',
        'gl_6332': '6332',
        'gl_6335': '6335',
        'gl_6338': '6338',
        'gl_6340': '6340',
        'gl_6345_salaries': '6345',
        'gl_6350': '6350',
        'gl_6355_sick_leave': '6355',
        'gl_6370_superannuation': '6370',
        'gl_6372_toil': '6372',
        'gl_6375': '6375',
        'gl_6380': '6380',
    }

    prorated_entries = defaultdict(lambda: {'debit': Decimal('0'), 'credit': Decimal('0'), 'description': ''})
    non_prorated_entries = []

    # Same logic as generate_journal
    for journal in journal_entries:
        ledger_account = journal.ledger_account.strip()

        if ledger_account.startswith('-'):
            gl_account = ledger_account[1:]
            is_credit = True
        else:
            if '-' in ledger_account:
                gl_account = ledger_account.split('-')[-1]
            else:
                gl_account = ledger_account
            is_credit = False

        needs_proration = journal_mapping.get(gl_account, {}).get('needs_proration', False)
        description = journal_mapping.get(gl_account, {}).get('description', f'GL {gl_account}')
        amount = journal.debit if journal.debit else Decimal('0')

        if needs_proration and amount > 0:
            total_gl_amount = Decimal('0')
            field_name = None

            for fname, acc in gl_field_to_account.items():
                if acc == gl_account:
                    field_name = fname
                    total_gl_amount = snapshots.aggregate(total=Sum(fname))['total'] or Decimal('0')
                    break

            if field_name and total_gl_amount > 0:
                for snapshot in snapshots:
                    employee_gl_amount = getattr(snapshot, field_name, Decimal('0'))

                    if employee_gl_amount > 0:
                        employee_share = amount * (employee_gl_amount / total_gl_amount)
                        cost_allocation = snapshot.cost_allocation

                        if cost_allocation:
                            for location_id, departments in cost_allocation.items():
                                for dept_id, percentage in departments.items():
                                    allocated_amount = employee_share * (Decimal(str(percentage)) / Decimal('100'))
                                    key = (location_id, dept_id, gl_account)

                                    if is_credit:
                                        prorated_entries[key]['credit'] += allocated_amount
                                    else:
                                        prorated_entries[key]['debit'] += allocated_amount
                                    prorated_entries[key]['description'] = description
        else:
            non_prorated_entries.append((gl_account, description, amount if not is_credit else Decimal('0'), amount if is_credit else Decimal('0')))

    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="journal_{pay_period_id}.csv"'

    writer = csv.writer(response)
    writer.writerow(['Location ID', 'Location Name', 'Department ID', 'Department Name',
                     'Cost Center', 'GL Account', 'Description', 'Debit', 'Credit'])

    # Write prorated entries
    for (location_id, dept_id, gl_account), amounts in sorted(prorated_entries.items()):
        location_name = location_names.get(location_id, location_id)
        dept_name = department_names.get(dept_id, dept_id)
        cost_center = f'{location_id}-{dept_id}00'

        writer.writerow([
            location_id, location_name, dept_id, dept_name, cost_center,
            gl_account, amounts['description'],
            f"{amounts['debit']:.2f}", f"{amounts['credit']:.2f}"
        ])

    # Write non-prorated entries
    for gl_account, description, debit, credit in non_prorated_entries:
        writer.writerow(['', '', '', '', '', gl_account, description, f"{debit:.2f}", f"{credit:.2f}"])

    return response
