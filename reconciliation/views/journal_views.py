"""
Journal generation views
Generates prorated journal entries from JournalReconciliation based on Employee Pay Period Snapshots
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
    SageLocation, SageDepartment, JournalReconciliation
)


def load_journal_mapping():
    """Load the Micropay_journal_mapping.csv file"""
    mapping_file = os.path.join(settings.BASE_DIR, 'data', 'Micropay_journal_mapping.csv')
    mapping = {}

    if os.path.exists(mapping_file):
        import csv
        with open(mapping_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                gl_account = row.get('GL Account', '').strip()
                if gl_account:
                    mapping[gl_account] = {
                        'description': row.get('Description', '').strip(),
                        'needs_proration': row.get('Total Cost', '').strip().upper() == 'Y'
                    }

    return mapping


def generate_journal(request, pay_period_id):
    """
    Generate journal entries for display
    Uses JournalReconciliation as source of truth
    """
    pay_period = get_object_or_404(PayPeriod, period_id=pay_period_id)

    # Get reconciliation run
    recon_run = pay_period.recon_runs.filter(status='completed').order_by('-completed_at').first()
    if not recon_run:
        return render(request, 'reconciliation/journal_error.html', {
            'pay_period': pay_period,
            'error': 'No completed reconciliation run found.'
        })

    # Get all journal reconciliation entries
    journal_recon_entries = JournalReconciliation.objects.filter(recon_run=recon_run)

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

    journal_entries_from_db = JournalEntry.objects.filter(upload=journal_upload)
    journal_mapping = load_journal_mapping()

    # Get location and department names
    location_names = {loc.location_id: loc.location_name for loc in SageLocation.objects.all()}
    department_names = {dept.department_id: dept.department_name for dept in SageDepartment.objects.all()}

    # Build GL field mapping dynamically from EmployeePayPeriodSnapshot fields
    gl_field_to_account = {}
    for field in EmployeePayPeriodSnapshot._meta.get_fields():
        if field.name.startswith('gl_'):
            # Extract GL number from field name (e.g., 'gl_2310_annual_leave' -> '2310')
            parts = field.name.split('_')
            if len(parts) >= 2 and parts[1].isdigit():
                gl_account = parts[1]
                gl_field_to_account[field.name] = gl_account

    # Structure: list of journal line dictionaries
    journal_lines = []

    # Common values
    date = pay_period.period_end.strftime('%m/%d/%Y')
    description = f"Payroll journal ending {pay_period.period_end.strftime('%Y-%m-%d')}"

    # Group JournalReconciliation entries by GL account to avoid duplicates
    gl_groups = defaultdict(list)
    for recon_entry in journal_recon_entries:
        gl_groups[recon_entry.gl_account].append(recon_entry)

    # Process each unique GL account
    for gl_account, recon_entries_for_gl in gl_groups.items():
        # Use the first entry's metadata (all should have same include_in_total_cost for same GL)
        first_entry = recon_entries_for_gl[0]
        gl_desc = first_entry.description
        include_in_total = first_entry.include_in_total_cost

        if include_in_total:
            # Prorate this GL across employee allocations
            prorated_entries = defaultdict(Decimal)  # {(location, dept): amount}

            for snapshot in snapshots:
                cost_allocation = snapshot.cost_allocation
                if not cost_allocation:
                    continue

                # Find the matching GL field in the snapshot
                gl_amount = Decimal('0')
                for field_name, field_gl in gl_field_to_account.items():
                    if field_gl == gl_account:
                        gl_amount = getattr(snapshot, field_name, Decimal('0'))
                        break

                if gl_amount and gl_amount != 0:
                    # Distribute across cost allocation
                    for location_id, departments in cost_allocation.items():
                        for dept_id, percentage in departments.items():
                            allocated_amount = gl_amount * (Decimal(str(percentage)) / Decimal('100'))
                            key = (location_id, dept_id)
                            prorated_entries[key] += allocated_amount

            # If no prorated entries were generated, skip this GL entirely
            if not prorated_entries:
                continue

            # Convert prorated entries to journal lines
            for (location_id, dept_id), amount in prorated_entries.items():
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
        else:
            # Non-prorated: use journal entries directly from Micropay_Journal
            # Group by location-dept from ledger_account
            non_prorated_entries = defaultdict(Decimal)  # {(location, dept): amount}

            for journal in journal_entries_from_db:
                ledger_account = journal.ledger_account.strip()

                # Determine GL account
                if ledger_account.startswith('-'):
                    entry_gl = ledger_account[1:]
                else:
                    if '-' in ledger_account:
                        entry_gl = ledger_account.split('-')[-1]
                    else:
                        entry_gl = ledger_account

                # Only process entries matching this GL account
                if entry_gl != gl_account:
                    continue

                # Calculate net amount (debit - credit)
                amount = (journal.debit or Decimal('0')) - (journal.credit or Decimal('0'))

                # Parse location/dept from ledger_account format: "location-dept-GL"
                location_id = ''
                dept_id = ''
                if '-' in ledger_account and not ledger_account.startswith('-'):
                    parts = ledger_account.split('-')
                    if len(parts) == 3:  # Format: location-dept-GL
                        location_id = parts[0]
                        dept_id = parts[1]

                key = (location_id, dept_id)
                non_prorated_entries[key] += amount

            # If no journal entries found, use journal_net from JournalReconciliation
            if not non_prorated_entries:
                total_net = sum(entry.journal_net for entry in recon_entries_for_gl)
                if total_net != 0:
                    non_prorated_entries[('', '')] = total_net

            # Convert consolidated non-prorated entries to journal lines
            for (location_id, dept_id), amount in non_prorated_entries.items():
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
                    'document': 'GL-Batch',
                    'memo': memo,
                    'debit': amount,
                    'billable': billable,
                    'item_id': item_id,
                    'project_id': project_id,
                    'customer_id': customer_id
                })

    # Calculate total
    total_debit = sum(line['debit'] for line in journal_lines)

    # Prepare context for template with Sage Intacct fields
    entries_for_display = []
    for line in journal_lines:
        location_name = location_names.get(line['location_id'], line['location_id'])
        dept_name = department_names.get(line['dept_id'], line['dept_id'])

        entries_for_display.append({
            'acct_no': line['acct_no'],
            'location_id': line['location_id'],
            'location_name': location_name,
            'dept_id': line['dept_id'],
            'dept_name': dept_name,
            'document': line['document'],
            'memo': line['memo'],
            'debit': line['debit'],
            'billable': line['billable'],
            'item_id': line['item_id'],
            'project_id': line['project_id'],
            'customer_id': line['customer_id'],
        })

    context = {
        'pay_period': pay_period,
        'entries': entries_for_display,
        'total_debit': total_debit,
        'date': date,
        'description': description,
        'balanced': abs(total_debit) < Decimal('0.01'),
        'employee_count': snapshots.count(),
        'journal_entry_count': len(journal_lines)
    }

    return render(request, 'reconciliation/journal_generated.html', context)


def download_journal_sage(request, pay_period_id):
    """Download journal in Sage Intacct format"""
    # Use same logic as generate_journal but output CSV
    pay_period = get_object_or_404(PayPeriod, period_id=pay_period_id)

    # Get reconciliation run
    recon_run = pay_period.recon_runs.filter(status='completed').order_by('-completed_at').first()
    if not recon_run:
        return HttpResponse("No completed reconciliation run found", status=404)

    # Get all journal reconciliation entries
    journal_recon_entries = JournalReconciliation.objects.filter(recon_run=recon_run)

    # Generate journal entries
    snapshots = EmployeePayPeriodSnapshot.objects.filter(pay_period=pay_period)
    journal_upload = Upload.objects.filter(
        pay_period=pay_period,
        source_system='Micropay_Journal',
        is_active=True
    ).first()

    if not journal_upload:
        return HttpResponse("No Micropay Journal upload found", status=404)

    journal_entries_from_db = JournalEntry.objects.filter(upload=journal_upload)
    journal_mapping = load_journal_mapping()

    # Build GL field mapping dynamically from EmployeePayPeriodSnapshot fields
    gl_field_to_account = {}
    for field in EmployeePayPeriodSnapshot._meta.get_fields():
        if field.name.startswith('gl_'):
            # Extract GL number from field name
            parts = field.name.split('_')
            if len(parts) >= 2 and parts[1].isdigit():
                gl_account = parts[1]
                gl_field_to_account[field.name] = gl_account

    # Structure: list of journal line dictionaries
    journal_lines = []

    # Common values
    journal_id = f"PAYROLL-{pay_period_id}"
    date = pay_period.period_end.strftime('%m/%d/%Y')
    description = f"Payroll journal ending {pay_period.period_end.strftime('%Y-%m-%d')}"

    # Group JournalReconciliation entries by GL account to avoid duplicates
    gl_groups = defaultdict(list)
    for recon_entry in journal_recon_entries:
        gl_groups[recon_entry.gl_account].append(recon_entry)

    # Process each unique GL account
    for gl_account, recon_entries_for_gl in gl_groups.items():
        # Use the first entry's metadata (all should have same include_in_total_cost for same GL)
        first_entry = recon_entries_for_gl[0]
        gl_desc = first_entry.description
        include_in_total = first_entry.include_in_total_cost

        if include_in_total:
            # Prorate this GL across employee allocations
            prorated_entries = defaultdict(Decimal)

            for snapshot in snapshots:
                cost_allocation = snapshot.cost_allocation
                if not cost_allocation:
                    continue

                # Find the matching GL field in the snapshot
                gl_amount = Decimal('0')
                for field_name, field_gl in gl_field_to_account.items():
                    if field_gl == gl_account:
                        gl_amount = getattr(snapshot, field_name, Decimal('0'))
                        break

                if gl_amount and gl_amount != 0:
                    # Distribute across cost allocation
                    for location_id, departments in cost_allocation.items():
                        for dept_id, percentage in departments.items():
                            allocated_amount = gl_amount * (Decimal(str(percentage)) / Decimal('100'))
                            key = (location_id, dept_id)
                            prorated_entries[key] += allocated_amount

            # If no prorated entries were generated, skip this GL entirely
            if not prorated_entries:
                continue

            # Convert prorated entries to journal lines
            for (location_id, dept_id), amount in prorated_entries.items():
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
        else:
            # Non-prorated: use journal entries directly
            non_prorated_entries = defaultdict(Decimal)

            for journal in journal_entries_from_db:
                ledger_account = journal.ledger_account.strip()

                # Determine GL account
                if ledger_account.startswith('-'):
                    entry_gl = ledger_account[1:]
                else:
                    if '-' in ledger_account:
                        entry_gl = ledger_account.split('-')[-1]
                    else:
                        entry_gl = ledger_account

                # Only process entries matching this GL account
                if entry_gl != gl_account:
                    continue

                # Calculate net amount (debit - credit)
                amount = (journal.debit or Decimal('0')) - (journal.credit or Decimal('0'))

                # Parse location/dept from ledger_account format: "location-dept-GL"
                location_id = ''
                dept_id = ''
                if '-' in ledger_account and not ledger_account.startswith('-'):
                    parts = ledger_account.split('-')
                    if len(parts) == 3:
                        location_id = parts[0]
                        dept_id = parts[1]

                key = (location_id, dept_id)
                non_prorated_entries[key] += amount

            # If no journal entries found, use journal_net from JournalReconciliation
            if not non_prorated_entries:
                total_net = sum(entry.journal_net for entry in recon_entries_for_gl)
                if total_net != 0:
                    non_prorated_entries[('', '')] = total_net

            # Convert consolidated non-prorated entries to journal lines
            for (location_id, dept_id), amount in non_prorated_entries.items():
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
                    'document': 'GL-Batch',
                    'memo': memo,
                    'debit': amount,
                    'billable': billable,
                    'item_id': item_id,
                    'project_id': project_id,
                    'customer_id': customer_id
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
    """Download simple CSV journal format"""
    pay_period = get_object_or_404(PayPeriod, period_id=pay_period_id)

    # Get reconciliation run
    recon_run = pay_period.recon_runs.filter(status='completed').order_by('-completed_at').first()
    if not recon_run:
        return HttpResponse("No completed reconciliation run found", status=404)

    journal_recon_entries = JournalReconciliation.objects.filter(recon_run=recon_run)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="journal_simple_{pay_period_id}.csv"'

    writer = csv.writer(response)
    writer.writerow(['GL Account', 'Description', 'Journal Net', 'Include in Total Cost'])

    for entry in journal_recon_entries:
        writer.writerow([
            entry.gl_account,
            entry.description,
            f"{entry.journal_net:.2f}",
            'Yes' if entry.include_in_total_cost else 'No'
        ])

    return response
