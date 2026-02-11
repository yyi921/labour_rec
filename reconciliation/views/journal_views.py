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
    SageLocation, SageDepartment, JournalReconciliation, IQBLeaveBalance,
    IQBDetail, IQBDetailV2, PayCompCodeMapping, JournalDescriptionMapping
)


def load_journal_mapping():
    """Load journal description mappings from database"""
    # Load from database
    mappings = JournalDescriptionMapping.objects.filter(is_active=True)

    mapping = {}
    for m in mappings:
        mapping[m.gl_account] = {
            'description': m.description,
            'needs_proration': m.include_in_total_cost
        }

    # If database is empty, try CSV as fallback
    if not mapping:
        mapping_file = os.path.join(settings.BASE_DIR, 'data', 'Micropay_journal_mapping.csv')
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

    # Get IQB upload for special GL handling (e.g., 4880 uses IQB cost_account_code)
    iqb_upload = Upload.objects.filter(
        pay_period=pay_period,
        source_system='Micropay_IQB',
        is_active=True
    ).first()

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

    # Calculate GL 2317 TIL total from IQBDetailV2 (used to adjust GL 6372)
    # This is needed because snapshot gl_6372 includes TIL amounts that should go to gl_2317
    iqb_2317_total = Decimal('0')
    iqb_2317_records_all = IQBDetailV2.objects.filter(
        period_end_date=pay_period.period_end,
        transaction_type='User Defined Leave',
        leave_reason_description='Time in Lieu Taken'
    )
    for rec in iqb_2317_records_all:
        iqb_2317_total += Decimal(str(rec.amount or 0))

    # Process each unique GL account
    for gl_account, recon_entries_for_gl in gl_groups.items():
        # Use the first entry's metadata (all should have same include_in_total_cost for same GL)
        first_entry = recon_entries_for_gl[0]
        gl_desc = first_entry.description
        include_in_total = first_entry.include_in_total_cost

        if include_in_total:
            # Prorate this GL across employee allocations
            prorated_entries = defaultdict(Decimal)  # {(location, dept): amount}

            # Special handling for GL 2317 - use IQBDetailV2 for Time in Lieu Taken
            if gl_account == '2317':
                # Get IQBDetailV2 records where Transaction Type = 'User Defined Leave'
                # AND Leave Reason = 'Time in Lieu Taken'
                iqb_2317_records = IQBDetailV2.objects.filter(
                    period_end_date=pay_period.period_end,
                    transaction_type='User Defined Leave',
                    leave_reason_description='Time in Lieu Taken'
                )
                for iqb_record in iqb_2317_records:
                    amount = Decimal(str(iqb_record.amount or 0))
                    cost_account = iqb_record.cost_account_code or ''

                    # Parse location/dept from cost_account_code format: "location-deptNN"
                    location_id = ''
                    dept_id = ''
                    if '-' in cost_account:
                        parts = cost_account.split('-')
                        location_id = parts[0]
                        # dept is first 2 chars of second part (e.g., "5000" -> "50")
                        dept_id = parts[1][:2] if len(parts[1]) >= 2 else parts[1]

                    if location_id:
                        key = (location_id, dept_id)
                        prorated_entries[key] += amount

            # Special handling for prorated 23* GLs - use IQBDetail cost_account_code
            elif gl_account.startswith('23') and iqb_upload:
                # Get pay_comp_codes that map to this GL account
                pay_comp_codes = list(PayCompCodeMapping.objects.filter(
                    gl_account=gl_account
                ).values_list('pay_comp_code', flat=True))

                if pay_comp_codes:
                    iqb_records = IQBDetail.objects.filter(
                        upload=iqb_upload,
                        pay_comp_code__in=pay_comp_codes
                    )
                    for iqb_record in iqb_records:
                        amount = iqb_record.amount or Decimal('0')
                        cost_account = iqb_record.cost_account_code or ''

                        # Parse location/dept from cost_account_code format: "location-deptNN"
                        location_id = ''
                        dept_id = ''
                        if '-' in cost_account:
                            parts = cost_account.split('-')
                            location_id = parts[0]
                            # dept is first 2 chars of second part (e.g., "5000" -> "50")
                            dept_id = parts[1][:2] if len(parts[1]) >= 2 else parts[1]

                        if location_id:
                            key = (location_id, dept_id)
                            prorated_entries[key] += amount
            else:
                # Standard prorated processing from employee snapshots
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

                # For GL 6372, subtract the TIL amount (which goes to 2317 instead)
                # The snapshot's gl_6372 includes TIL amounts that are captured separately in 2317
                if gl_account == '6372' and iqb_2317_total != 0 and prorated_entries:
                    total_6372 = sum(prorated_entries.values())
                    if total_6372 != 0:
                        # Subtract proportionally across all entries
                        adjustment_ratio = iqb_2317_total / total_6372
                        for key in prorated_entries:
                            prorated_entries[key] -= prorated_entries[key] * adjustment_ratio

            # Add COY "Employee Deduct" entries from GL Batch directly
            # These are company-level transactions not captured in employee snapshots
            # Use cost_account for location/dept (same approach as Rent/GL 4880)
            for journal in journal_entries_from_db:
                if 'Payroll Liab - Employee Deduct' not in (journal.description or ''):
                    continue
                ledger_account = journal.ledger_account.strip()
                if ledger_account.startswith('-'):
                    entry_gl = ledger_account[1:]
                elif '-' in ledger_account:
                    entry_gl = ledger_account.split('-')[-1]
                else:
                    entry_gl = ledger_account
                if entry_gl != gl_account:
                    continue

                amount = (journal.debit or Decimal('0')) - (journal.credit or Decimal('0'))
                cost_account = (journal.cost_account or '').strip()

                location_id = ''
                dept_id = ''
                if '-' in cost_account:
                    parts = cost_account.split('-')
                    location_id = parts[0]
                    dept_id = parts[1][:2] if len(parts[1]) >= 2 else parts[1]

                if location_id:
                    key = (location_id, dept_id)
                    prorated_entries[key] += amount

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

                # GL accounts starting with '23' (liability accounts) should NOT be on-charged to 1180
                if location_id == '700' and not gl_account.startswith('23'):
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

            # Standard non-prorated processing from Micropay Journal
            # (GL 4880 Rent is handled via GL Batch like other non-prorated GLs)
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

                # GL accounts starting with '23' (liability accounts) should NOT be on-charged to 1180
                if location_id == '700' and not gl_account.startswith('23'):
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

    # Calculate Payroll Tax and Workcover on GL 1180 total
    # Sum all GL 1180 entries
    total_1180 = sum(line['debit'] for line in journal_lines if line['acct_no'] == '1180')

    if total_1180 != 0:
        # Define rates
        PRT_rate = Decimal('0.0495')  # 4.95% Payroll Tax
        workcover_rate = Decimal('0.01384')  # 1.384% Workcover

        # Calculate amounts
        payroll_tax = total_1180 * PRT_rate
        workcover = total_1180 * workcover_rate
        total_adjustment = payroll_tax + workcover

        # Add three lines at the bottom
        # 1. Debit GL 1180 for total adjustment
        journal_lines.append({
            'acct_no': '1180',
            'location_id': '460',
            'dept_id': '20',
            'document': 'GL-Batch',
            'memo': f"{description} - Payroll Tax and Workcover adjustment",
            'debit': total_adjustment,
            'billable': 'T',
            'item_id': 'ICO-RECHARGE',
            'project_id': 'CMG110-001',
            'customer_id': 'CMG110'
        })

        # 2. Credit GL 6335 (Payroll Tax) - represented as negative debit
        journal_lines.append({
            'acct_no': '6335',
            'location_id': '460',
            'dept_id': '20',
            'document': 'GL-Batch',
            'memo': f"{description} - Payroll Tax @ {PRT_rate * 100}%",
            'debit': -payroll_tax,
            'billable': '',
            'item_id': '',
            'project_id': '',
            'customer_id': ''
        })

        # 3. Credit GL 6380 (Workcover) - represented as negative debit
        journal_lines.append({
            'acct_no': '6380',
            'location_id': '460',
            'dept_id': '20',
            'document': 'GL-Batch',
            'memo': f"{description} - Workcover Insurance @ {workcover_rate * 100}%",
            'debit': -workcover,
            'billable': '',
            'item_id': '',
            'project_id': '',
            'customer_id': ''
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

    # Build GL Batch vs Sage Journal comparison table
    # GL Batch totals from Micropay Journal (ledger_account last 4 digits = GL, debit - credit)
    gl_batch_totals = defaultdict(Decimal)
    location_700_entries = []  # For the new Location 700 breakdown table

    for journal in journal_entries_from_db:
        ledger_account = journal.ledger_account.strip()
        # Extract GL account (last part after dash, or whole thing if starts with -)
        if ledger_account.startswith('-'):
            gl_account = ledger_account[1:]
        elif '-' in ledger_account:
            gl_account = ledger_account.split('-')[-1]
        else:
            gl_account = ledger_account

        amount = (journal.debit or Decimal('0')) - (journal.credit or Decimal('0'))
        gl_batch_totals[gl_account] += amount

        # Collect Location 700 entries for breakdown table (Cost Account starts with 700-)
        cost_account = (journal.cost_account or '').strip()
        if cost_account.startswith('700-'):
            location_700_entries.append({
                'ledger_account': ledger_account,
                'cost_account': cost_account,
                'gl_account': gl_account,
                'debit': journal.debit or Decimal('0'),
                'credit': journal.credit or Decimal('0'),
                'net': amount
            })

    # Calculate Location 700 total
    location_700_total = sum(e['net'] for e in location_700_entries)

    # Sage Journal totals - keep both actual GL and mapped-back totals
    sage_journal_totals = defaultdict(Decimal)  # Mapped back to original GLs for comparison
    sage_journal_actual = defaultdict(Decimal)  # Actual GL accounts in Sage Journal

    for line in journal_lines:
        acct_no = line['acct_no']
        sage_journal_actual[acct_no] += line['debit']

        # For comparison, map 1180 back to original GL
        memo = line['memo']
        mapped_acct = acct_no

        # For 1180 entries, the original GL is in the memo
        if acct_no == '1180' and 'Payroll journal' in memo:
            # Extract original GL from memo format: "Payroll journal ending ... {gl_account} {gl_desc}"
            parts = memo.split()
            for i, part in enumerate(parts):
                if part.isdigit() and len(part) == 4:
                    mapped_acct = part
                    break

        sage_journal_totals[mapped_acct] += line['debit']

    # Build comparison list
    all_gl_accounts = sorted(set(gl_batch_totals.keys()) | set(sage_journal_totals.keys()))
    gl_comparison = []

    # Get GL descriptions from journal mapping
    gl_descriptions = {}
    for mapping in JournalDescriptionMapping.objects.all():
        gl_descriptions[mapping.gl_account] = mapping.description

    for gl_account in all_gl_accounts:
        # Skip 1180 - we'll add it manually with actual values
        if gl_account == '1180':
            continue
        batch_total = gl_batch_totals.get(gl_account, Decimal('0'))
        sage_total = sage_journal_totals.get(gl_account, Decimal('0'))
        variance = sage_total - batch_total

        gl_comparison.append({
            'gl_account': gl_account,
            'description': gl_descriptions.get(gl_account, ''),
            'gl_batch': batch_total,
            'sage_journal': sage_total,
            'variance': variance,
            'matched': abs(variance) < Decimal('0.01')
        })

    # Add 1180 row with actual values (GL Batch = Location 700 total, Sage = actual 1180)
    total_1180_sage = sage_journal_actual.get('1180', Decimal('0'))
    variance_1180 = total_1180_sage - location_700_total
    gl_comparison.append({
        'gl_account': '1180',
        'description': 'TECC On-Charge (Location 700)',
        'gl_batch': location_700_total,
        'sage_journal': total_1180_sage,
        'variance': variance_1180,
        'matched': abs(variance_1180) < Decimal('0.01')
    })
    # Re-sort to put 1180 in proper position
    gl_comparison.sort(key=lambda x: x['gl_account'])

    context = {
        'pay_period': pay_period,
        'entries': entries_for_display,
        'total_debit': total_debit,
        'date': date,
        'description': description,
        'balanced': abs(total_debit) < Decimal('0.01'),
        'employee_count': snapshots.count(),
        'journal_entry_count': len(journal_lines),
        'gl_comparison': gl_comparison,
        'total_1180_sage': total_1180_sage,
        'location_700_entries': location_700_entries,
        'location_700_total': location_700_total,
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

    # Get IQB upload for special GL handling (e.g., 4880 uses IQB cost_account_code)
    iqb_upload = Upload.objects.filter(
        pay_period=pay_period,
        source_system='Micropay_IQB',
        is_active=True
    ).first()

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

    # Calculate GL 2317 TIL total from IQBDetailV2 (used to adjust GL 6372)
    # This is needed because snapshot gl_6372 includes TIL amounts that should go to gl_2317
    iqb_2317_total = Decimal('0')
    iqb_2317_records_all = IQBDetailV2.objects.filter(
        period_end_date=pay_period.period_end,
        transaction_type='User Defined Leave',
        leave_reason_description='Time in Lieu Taken'
    )
    for rec in iqb_2317_records_all:
        iqb_2317_total += Decimal(str(rec.amount or 0))

    # Process each unique GL account
    for gl_account, recon_entries_for_gl in gl_groups.items():
        # Use the first entry's metadata (all should have same include_in_total_cost for same GL)
        first_entry = recon_entries_for_gl[0]
        gl_desc = first_entry.description
        include_in_total = first_entry.include_in_total_cost

        if include_in_total:
            # Prorate this GL across employee allocations
            prorated_entries = defaultdict(Decimal)

            # Special handling for GL 2317 - use IQBDetailV2 for Time in Lieu Taken
            if gl_account == '2317':
                # Get IQBDetailV2 records where Transaction Type = 'User Defined Leave'
                # AND Leave Reason = 'Time in Lieu Taken'
                iqb_2317_records = IQBDetailV2.objects.filter(
                    period_end_date=pay_period.period_end,
                    transaction_type='User Defined Leave',
                    leave_reason_description='Time in Lieu Taken'
                )
                for iqb_record in iqb_2317_records:
                    amount = Decimal(str(iqb_record.amount or 0))
                    cost_account = iqb_record.cost_account_code or ''

                    # Parse location/dept from cost_account_code format: "location-deptNN"
                    location_id = ''
                    dept_id = ''
                    if '-' in cost_account:
                        parts = cost_account.split('-')
                        location_id = parts[0]
                        dept_id = parts[1][:2] if len(parts[1]) >= 2 else parts[1]

                    if location_id:
                        key = (location_id, dept_id)
                        prorated_entries[key] += amount

            # Special handling for prorated 23* GLs - use IQBDetail cost_account_code
            elif gl_account.startswith('23') and iqb_upload:
                # Get pay_comp_codes that map to this GL account
                pay_comp_codes = list(PayCompCodeMapping.objects.filter(
                    gl_account=gl_account
                ).values_list('pay_comp_code', flat=True))

                if pay_comp_codes:
                    iqb_records = IQBDetail.objects.filter(
                        upload=iqb_upload,
                        pay_comp_code__in=pay_comp_codes
                    )
                    for iqb_record in iqb_records:
                        amount = iqb_record.amount or Decimal('0')
                        cost_account = iqb_record.cost_account_code or ''

                        # Parse location/dept from cost_account_code format: "location-deptNN"
                        location_id = ''
                        dept_id = ''
                        if '-' in cost_account:
                            parts = cost_account.split('-')
                            location_id = parts[0]
                            # dept is first 2 chars of second part (e.g., "5000" -> "50")
                            dept_id = parts[1][:2] if len(parts[1]) >= 2 else parts[1]

                        if location_id:
                            key = (location_id, dept_id)
                            prorated_entries[key] += amount
            else:
                # Standard prorated processing from employee snapshots
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

                # For GL 6372, subtract the TIL amount (which goes to 2317 instead)
                # The snapshot's gl_6372 includes TIL amounts that are captured separately in 2317
                if gl_account == '6372' and iqb_2317_total != 0 and prorated_entries:
                    total_6372 = sum(prorated_entries.values())
                    if total_6372 != 0:
                        # Subtract proportionally across all entries
                        adjustment_ratio = iqb_2317_total / total_6372
                        for key in prorated_entries:
                            prorated_entries[key] -= prorated_entries[key] * adjustment_ratio

            # Add COY "Employee Deduct" entries from GL Batch directly
            # These are company-level transactions not captured in employee snapshots
            # Use cost_account for location/dept (same approach as Rent/GL 4880)
            for journal in journal_entries_from_db:
                if 'Payroll Liab - Employee Deduct' not in (journal.description or ''):
                    continue
                ledger_account = journal.ledger_account.strip()
                if ledger_account.startswith('-'):
                    entry_gl = ledger_account[1:]
                elif '-' in ledger_account:
                    entry_gl = ledger_account.split('-')[-1]
                else:
                    entry_gl = ledger_account
                if entry_gl != gl_account:
                    continue

                amount = (journal.debit or Decimal('0')) - (journal.credit or Decimal('0'))
                cost_account = (journal.cost_account or '').strip()

                location_id = ''
                dept_id = ''
                if '-' in cost_account:
                    parts = cost_account.split('-')
                    location_id = parts[0]
                    dept_id = parts[1][:2] if len(parts[1]) >= 2 else parts[1]

                if location_id:
                    key = (location_id, dept_id)
                    prorated_entries[key] += amount

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

                # GL accounts starting with '23' (liability accounts) should NOT be on-charged to 1180
                if location_id == '700' and not gl_account.startswith('23'):
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

            # Standard non-prorated processing from Micropay Journal
            # (GL 4880 Rent is handled via GL Batch like other non-prorated GLs)
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

                # GL accounts starting with '23' (liability accounts) should NOT be on-charged to 1180
                if location_id == '700' and not gl_account.startswith('23'):
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

    # Calculate Payroll Tax and Workcover on GL 1180 total
    # Sum all GL 1180 entries
    total_1180 = sum(line['debit'] for line in journal_lines if line['acct_no'] == '1180')

    if total_1180 != 0:
        # Define rates
        PRT_rate = Decimal('0.0495')  # 4.95% Payroll Tax
        workcover_rate = Decimal('0.01384')  # 1.384% Workcover

        # Calculate amounts
        payroll_tax = total_1180 * PRT_rate
        workcover = total_1180 * workcover_rate
        total_adjustment = payroll_tax + workcover

        # Add three lines at the bottom
        # 1. Debit GL 1180 for total adjustment
        journal_lines.append({
            'acct_no': '1180',
            'location_id': '460',
            'dept_id': '20',
            'document': 'GL-Batch',
            'memo': f"{description} - Payroll Tax and Workcover adjustment",
            'debit': total_adjustment,
            'billable': 'T',
            'item_id': 'ICO-RECHARGE',
            'project_id': 'CMG110-001',
            'customer_id': 'CMG110'
        })

        # 2. Credit GL 6335 (Payroll Tax) - represented as negative debit
        journal_lines.append({
            'acct_no': '6335',
            'location_id': '460',
            'dept_id': '20',
            'document': 'GL-Batch',
            'memo': f"{description} - Payroll Tax @ {PRT_rate * 100}%",
            'debit': -payroll_tax,
            'billable': '',
            'item_id': '',
            'project_id': '',
            'customer_id': ''
        })

        # 3. Credit GL 6380 (Workcover) - represented as negative debit
        journal_lines.append({
            'acct_no': '6380',
            'location_id': '460',
            'dept_id': '20',
            'document': 'GL-Batch',
            'memo': f"{description} - Workcover Insurance @ {workcover_rate * 100}%",
            'debit': -workcover,
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


def download_journal_xero(request, pay_period_id):
    """Download journal in Xero format - inter-company entries only (billable = T)"""
    pay_period = get_object_or_404(PayPeriod, period_id=pay_period_id)

    # Get reconciliation run
    recon_run = pay_period.recon_runs.filter(status='completed').order_by('-completed_at').first()
    if not recon_run:
        return HttpResponse("No completed reconciliation run found", status=404)

    # Get all journal reconciliation entries
    journal_recon_entries = JournalReconciliation.objects.filter(recon_run=recon_run)

    # Generate journal entries (same as Sage export)
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

    # Get IQB upload for special GL handling (e.g., 4880 uses IQB cost_account_code)
    iqb_upload = Upload.objects.filter(
        pay_period=pay_period,
        source_system='Micropay_IQB',
        is_active=True
    ).first()

    # Get location and department names
    location_names = {loc.location_id: loc.location_name for loc in SageLocation.objects.all()}
    department_names = {dept.department_id: dept.department_name for dept in SageDepartment.objects.all()}

    # Build GL field mapping
    gl_field_to_account = {}
    for field in EmployeePayPeriodSnapshot._meta.get_fields():
        if field.name.startswith('gl_'):
            parts = field.name.split('_')
            if len(parts) >= 2 and parts[1].isdigit():
                gl_account = parts[1]
                gl_field_to_account[field.name] = gl_account

    journal_lines = []
    date = pay_period.period_end.strftime('%m/%d/%Y')
    description = f"Payroll journal ending {pay_period.period_end.strftime('%Y-%m-%d')}"

    # Group by GL account
    gl_groups = defaultdict(list)
    for recon_entry in journal_recon_entries:
        gl_groups[recon_entry.gl_account].append(recon_entry)

    # Process each unique GL account (same logic as Sage export)
    for gl_account, recon_entries_for_gl in gl_groups.items():
        first_entry = recon_entries_for_gl[0]
        gl_desc = first_entry.description
        include_in_total = first_entry.include_in_total_cost

        if include_in_total:
            prorated_entries = defaultdict(Decimal)

            # Special handling for GL 2317 - use IQBDetailV2 for Time in Lieu Taken
            if gl_account == '2317':
                iqb_2317_records = IQBDetailV2.objects.filter(
                    period_end_date=pay_period.period_end,
                    transaction_type='User Defined Leave',
                    leave_reason_description='Time in Lieu Taken'
                )
                for iqb_record in iqb_2317_records:
                    amount = Decimal(str(iqb_record.amount or 0))
                    cost_account = iqb_record.cost_account_code or ''

                    location_id = ''
                    dept_id = ''
                    if '-' in cost_account:
                        parts = cost_account.split('-')
                        location_id = parts[0]
                        dept_id = parts[1][:2] if len(parts[1]) >= 2 else parts[1]

                    if location_id:
                        key = (location_id, dept_id)
                        prorated_entries[key] += amount

            # Special handling for prorated 23* GLs - use IQBDetail cost_account_code
            elif gl_account.startswith('23') and iqb_upload:
                # Get pay_comp_codes that map to this GL account
                pay_comp_codes = list(PayCompCodeMapping.objects.filter(
                    gl_account=gl_account
                ).values_list('pay_comp_code', flat=True))

                if pay_comp_codes:
                    iqb_records = IQBDetail.objects.filter(
                        upload=iqb_upload,
                        pay_comp_code__in=pay_comp_codes
                    )
                    for iqb_record in iqb_records:
                        amount = iqb_record.amount or Decimal('0')
                        cost_account = iqb_record.cost_account_code or ''

                        location_id = ''
                        dept_id = ''
                        if '-' in cost_account:
                            parts = cost_account.split('-')
                            location_id = parts[0]
                            dept_id = parts[1][:2] if len(parts[1]) >= 2 else parts[1]

                        if location_id:
                            key = (location_id, dept_id)
                            prorated_entries[key] += amount
            else:
                for snapshot in snapshots:
                    cost_allocation = snapshot.cost_allocation
                    if not cost_allocation:
                        continue

                    gl_amount = Decimal('0')
                    for field_name, field_gl in gl_field_to_account.items():
                        if field_gl == gl_account:
                            gl_amount = getattr(snapshot, field_name, Decimal('0'))
                            break

                    if gl_amount and gl_amount != 0:
                        for location_id, departments in cost_allocation.items():
                            for dept_id, percentage in departments.items():
                                allocated_amount = gl_amount * (Decimal(str(percentage)) / Decimal('100'))
                                key = (location_id, dept_id)
                                prorated_entries[key] += allocated_amount

            if not prorated_entries:
                continue

            for (location_id, dept_id), amount in prorated_entries.items():
                memo = f"{description} {gl_account} {gl_desc}"

                acct_no = gl_account
                final_location = location_id
                billable = ''
                item_id = ''
                project_id = ''
                customer_id = ''

                # GL accounts starting with '23' (liability accounts) should NOT be on-charged to 1180
                if location_id == '700' and not gl_account.startswith('23'):
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
            non_prorated_entries = defaultdict(Decimal)

            # Standard non-prorated processing from Micropay Journal
            # (GL 4880 Rent is handled via GL Batch like other non-prorated GLs)
            for journal in journal_entries_from_db:
                ledger_account = journal.ledger_account.strip()

                if ledger_account.startswith('-'):
                    entry_gl = ledger_account[1:]
                else:
                    if '-' in ledger_account:
                        entry_gl = ledger_account.split('-')[-1]
                    else:
                        entry_gl = ledger_account

                if entry_gl != gl_account:
                    continue

                amount = (journal.debit or Decimal('0')) - (journal.credit or Decimal('0'))

                location_id = ''
                dept_id = ''
                if '-' in ledger_account and not ledger_account.startswith('-'):
                    parts = ledger_account.split('-')
                    if len(parts) == 3:
                        location_id = parts[0]
                        dept_id = parts[1]

                key = (location_id, dept_id)
                non_prorated_entries[key] += amount

            if not non_prorated_entries:
                total_net = sum(entry.journal_net for entry in recon_entries_for_gl)
                if total_net != 0:
                    non_prorated_entries[('', '')] = total_net

            for (location_id, dept_id), amount in non_prorated_entries.items():
                memo = f"{description} {gl_account} {gl_desc}"

                acct_no = gl_account
                final_location = location_id
                billable = ''
                item_id = ''
                project_id = ''
                customer_id = ''

                # GL accounts starting with '23' (liability accounts) should NOT be on-charged to 1180
                if location_id == '700' and not gl_account.startswith('23'):
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

    # Calculate Payroll Tax and Workcover on GL 1180 total
    total_1180 = sum(line['debit'] for line in journal_lines if line['acct_no'] == '1180')

    if total_1180 != 0:
        PRT_rate = Decimal('0.0495')
        workcover_rate = Decimal('0.01384')

        payroll_tax = total_1180 * PRT_rate
        workcover = total_1180 * workcover_rate
        total_adjustment = payroll_tax + workcover

        journal_lines.append({
            'acct_no': '1180',
            'location_id': '460',
            'dept_id': '20',
            'document': 'GL-Batch',
            'memo': f"{description} - Payroll Tax and Workcover adjustment",
            'debit': total_adjustment,
            'billable': 'T',
            'item_id': 'ICO-RECHARGE',
            'project_id': 'CMG110-001',
            'customer_id': 'CMG110'
        })

        journal_lines.append({
            'acct_no': '6335',
            'location_id': '460',
            'dept_id': '20',
            'document': 'GL-Batch',
            'memo': f"{description} - Payroll Tax @ {PRT_rate * 100}%",
            'debit': -payroll_tax,
            'billable': '',
            'item_id': '',
            'project_id': '',
            'customer_id': ''
        })

        journal_lines.append({
            'acct_no': '6380',
            'location_id': '460',
            'dept_id': '20',
            'document': 'GL-Batch',
            'memo': f"{description} - Workcover Insurance @ {workcover_rate * 100}%",
            'debit': -workcover,
            'billable': '',
            'item_id': '',
            'project_id': '',
            'customer_id': ''
        })

    # Filter only billable entries (inter-company)
    billable_lines = [line for line in journal_lines if line['billable'] == 'T']

    # Process billable lines to extract correct GL accounts and split adjustment line
    xero_lines = []

    for line in billable_lines:
        memo = line['memo']
        amount = line['debit']

        # Check if this is the combined Payroll Tax and Workcover adjustment
        if 'Payroll Tax and Workcover adjustment' in memo:
            # Split into two lines: 6335 (Payroll Tax) and 6380 (Workcover)
            # Calculate individual amounts based on rates
            PRT_rate = Decimal('0.0495')
            workcover_rate = Decimal('0.01384')
            total_rate = PRT_rate + workcover_rate

            payroll_tax_amount = amount * (PRT_rate / total_rate)
            workcover_amount = amount * (workcover_rate / total_rate)

            # Add Payroll Tax line
            xero_lines.append({
                'narration': f"{description} - Payroll Tax @ {PRT_rate * 100}%",
                'account_code': '6335',
                'amount': payroll_tax_amount
            })

            # Add Workcover line
            xero_lines.append({
                'narration': f"{description} - Workcover Insurance @ {workcover_rate * 100}%",
                'account_code': '6380',
                'amount': workcover_amount
            })
        else:
            # Extract GL account from memo
            # Memo format: "Payroll journal ending YYYY-MM-DD GLNUM Description"
            import re
            gl_match = re.search(r'\d{4}-\d{2}-\d{2}\s+(\d{4})\s+', memo)

            if gl_match:
                gl_account = gl_match.group(1)
            else:
                # Fallback to acct_no if can't parse
                gl_account = line['acct_no']

            xero_lines.append({
                'narration': memo,
                'account_code': gl_account,
                'amount': amount
            })

    # Create Xero CSV format
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="journal_xero_{pay_period_id}.csv"'

    writer = csv.writer(response)

    # Write header row (from Xero template)
    writer.writerow([
        '*Narration', '*Date', 'Description', '*AccountCode', '*TaxRate', '*Amount',
        'TrackingName1', 'TrackingOption1', 'TrackingOption2'
    ])

    # Calculate total debit for billable entries
    total_debit = sum(line['amount'] for line in xero_lines)

    # Write debit lines (all billable entries)
    for line in xero_lines:
        writer.writerow([
            line['narration'],  # *Narration
            date,  # *Date
            '',  # Description (blank)
            line['account_code'],  # *AccountCode
            'BAS Excluded',  # *TaxRate
            f"{line['amount']:.2f}",  # *Amount (positive for debit)
            'Department',  # TrackingName1
            'Event Hire & Service Recoveries',  # TrackingOption1
            '700-2000'  # TrackingOption2
        ])

    # Write credit line (GL 2350 with total opposite sign)
    if total_debit != 0:
        writer.writerow([
            f"{description} - GL 2350 Net Wages Clearing",  # *Narration
            date,  # *Date
            '',  # Description (blank)
            '2350',  # *AccountCode
            'BAS Excluded',  # *TaxRate
            f"{-total_debit:.2f}",  # *Amount (negative for credit)
            'Department',  # TrackingName1
            'Event Hire & Service Recoveries',  # TrackingOption1
            '700-2000'  # TrackingOption2
        ])

    return response


def download_employee_snapshot(request, pay_period_id):
    """
    Download employee pay period snapshot showing cost allocations by GL account
    Each employee gets multiple rows - one for each cost center they're allocated to
    """
    pay_period = get_object_or_404(PayPeriod, period_id=pay_period_id)

    # Get all snapshots for this pay period
    snapshots = EmployeePayPeriodSnapshot.objects.filter(
        pay_period=pay_period
    ).order_by('employee_code')

    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="employee_snapshot_{pay_period_id}.csv"'

    writer = csv.writer(response)

    # Define GL account columns in order
    gl_columns = [
        ('gl_2310_annual_leave', '2310 Annual Leave'),
        ('gl_2317_toil', '2317 TOIL'),
        ('gl_2318_toil_liability', '2318 TOIL Liability (Deprecated)'),
        ('gl_2320_sick_leave', '2320 WorkCover'),
        ('gl_2321_paid_parental', '2321 Paid Parental'),
        ('gl_2325_leasing', '2325 Leasing'),
        ('gl_2330_long_service_leave', '2330 Long Service Leave (Current)'),
        ('gl_2705_long_service_leave', '2705 Long Service Leave (Non-Current)'),
        ('gl_2350_net_wages', '2350 Net Wages'),
        ('gl_2351_other_deductions', '2351 Other Deductions'),
        ('gl_2360_payg_withholding', '2360 PAYG Withholding'),
        ('gl_2391_super_sal_sacrifice', '2391 Super Sal Sacrifice'),
        ('gl_6302', '6302'),
        ('gl_6305', '6305'),
        ('gl_6309', '6309'),
        ('gl_6310', '6310'),
        ('gl_6312', '6312'),
        ('gl_6315', '6315'),
        ('gl_6325', '6325'),
        ('gl_6330', '6330'),
        ('gl_6331', '6331'),
        ('gl_6332', '6332'),
        ('gl_6335', '6335'),
        ('gl_6338', '6338'),
        ('gl_6340', '6340'),
        ('gl_6345_salaries', '6345 Salaries'),
        ('gl_6350', '6350'),
        ('gl_6355_sick_leave', '6355 Sick Leave'),
        ('gl_6370_superannuation', '6370 Superannuation'),
        ('gl_6372_toil', '6372 TOIL'),
        ('gl_6375', '6375'),
        ('gl_6380', '6380'),
    ]

    # Write header
    header = [
        'Employee Code',
        'Employee Name',
        'Location',
        'Department',
        'Allocation %',
        'Allocated Amount',
        'Source'
    ]
    header.extend([label for _, label in gl_columns])
    writer.writerow(header)

    # Get location and department lookups
    location_lookup = {loc.location_id: loc.location_name for loc in SageLocation.objects.all()}
    department_lookup = {dept.department_id: dept.department_name for dept in SageDepartment.objects.all()}

    # Write data rows
    for snapshot in snapshots:
        # Get cost allocation breakdown
        cost_allocation = snapshot.cost_allocation or {}

        # If no cost allocation, create one row with 100%
        if not cost_allocation:
            row = [
                snapshot.employee_code,
                snapshot.employee_name,
                '',
                '',
                '100.00',
                f"{snapshot.total_cost:.2f}",
                snapshot.allocation_source
            ]

            # Add GL amounts (full amounts)
            for field_name, _ in gl_columns:
                amount = getattr(snapshot, field_name, Decimal('0')) or Decimal('0')
                row.append(f"{amount:.2f}")

            writer.writerow(row)
        else:
            # Create a row for each cost center allocation
            for location_id, departments in cost_allocation.items():
                for dept_id, percentage in departments.items():
                    location_name = location_lookup.get(location_id, location_id)
                    dept_name = department_lookup.get(dept_id, dept_id)

                    # Calculate allocated amount for this cost center
                    allocated_amount = float(snapshot.total_cost) * (float(percentage) / 100)

                    row = [
                        snapshot.employee_code,
                        snapshot.employee_name,
                        location_name,
                        dept_name,
                        f"{percentage:.2f}",
                        f"{allocated_amount:.2f}",
                        snapshot.allocation_source
                    ]

                    # Add GL amounts (prorated by allocation percentage)
                    for field_name, _ in gl_columns:
                        amount = getattr(snapshot, field_name, Decimal('0')) or Decimal('0')
                        prorated_amount = float(amount) * (float(percentage) / 100)
                        row.append(f"{prorated_amount:.2f}")

                    writer.writerow(row)

    return response


def _calculate_leave_accruals_for_type(leave_type, gl_liability_account, gl_expense_account,
                                        opening_upload, closing_upload, iqb_upload,
                                        tp_pay_period, transaction_type=None, pay_comp_codes=None,
                                        use_iqb_v2=False, leave_reason_code=None):
    """
    Calculate accruals for a specific leave type using direct transaction type matching

    Args:
        leave_type: 'Annual Leave', 'Long Service Leave', or 'User Defined Leave'
        gl_liability_account: GL account for liability (2310, 2317, 2705, 2330, or None for LSL - determined by years of service)
        gl_expense_account: GL account for expense (6300, 6345, or 6372)
        opening_upload: Opening balance upload (LP)
        closing_upload: Closing balance upload (TP)
        iqb_upload: IQB detail upload (RET002) for TP period
        tp_pay_period: This Period pay period object
        transaction_type: Optional - IQB transaction type for leave taken (defaults to leave_type)
        pay_comp_codes: Optional - List of IQB pay_comp_codes for leave taken (overrides transaction_type)
        use_iqb_v2: If True, use IQBDetailV2 model instead of IQBDetail (for TOIL with leave_reason_code)
        leave_reason_code: Optional - Additional filter for IQBDetailV2 (e.g., 'TIL Taken' for TOIL)

    Returns: List of employee-level accrual dictionaries
    """
    from django.db.models import Sum
    from reconciliation.models import LSLProbability

    accruals = []

    # Default transaction type to leave_type if not specified
    if transaction_type is None:
        transaction_type = leave_type

    # Get ALL unique employees from BOTH opening and closing periods
    # This ensures we include terminated employees (in opening but not closing)
    # and new hires (in closing but not opening)
    opening_employees_set = set(IQBLeaveBalance.objects.filter(
        upload=opening_upload,
        leave_type=leave_type
    ).values_list('employee_code', flat=True))

    closing_employees_set = set(IQBLeaveBalance.objects.filter(
        upload=closing_upload,
        leave_type=leave_type
    ).values_list('employee_code', flat=True))

    all_employees = sorted(opening_employees_set | closing_employees_set)

    for emp_code in all_employees:
        # Closing balance (value in $, including leave loading)
        closing_aggregation = IQBLeaveBalance.objects.filter(
            upload=closing_upload,
            employee_code=emp_code,
            leave_type=leave_type
        ).aggregate(
            total_balance=Sum('balance_value'),
            total_loading=Sum('leave_loading')
        )
        closing_balance = closing_aggregation['total_balance'] or Decimal('0')
        closing_loading = closing_aggregation['total_loading'] or Decimal('0')
        closing_value = closing_balance + closing_loading

        # Get employee name from closing record (or opening if not in closing)
        emp_record = IQBLeaveBalance.objects.filter(
            upload=closing_upload,
            employee_code=emp_code,
            leave_type=leave_type
        ).first()

        if not emp_record:
            # Try opening record if not in closing (terminated employee)
            emp_record = IQBLeaveBalance.objects.filter(
                upload=opening_upload,
                employee_code=emp_code,
                leave_type=leave_type
            ).first()

        emp_name = emp_record.full_name if emp_record else emp_code

        # Get opening balance (value in $, including leave loading)
        # Also get the opening record for years_of_service (needed for LSL probability)
        opening_record = IQBLeaveBalance.objects.filter(
            upload=opening_upload,
            employee_code=emp_code,
            leave_type=leave_type
        ).first()

        opening_aggregation = IQBLeaveBalance.objects.filter(
            upload=opening_upload,
            employee_code=emp_code,
            leave_type=leave_type
        ).aggregate(
            total_balance=Sum('balance_value'),
            total_loading=Sum('leave_loading')
        )

        opening_balance = opening_aggregation['total_balance'] or Decimal('0')
        opening_loading = opening_aggregation['total_loading'] or Decimal('0')
        opening_value = opening_balance + opening_loading

        # Calculate leave taken directly from IQB Detail
        # Use IQBDetailV2 for TOIL (requires leave_reason_code filter)
        if use_iqb_v2 and pay_comp_codes and leave_reason_code:
            # TOIL uses IQBDetailV2 with pay_comp_code and leave_reason_code filters
            leave_taken_aggregation = IQBDetailV2.objects.filter(
                upload=iqb_upload,
                employee_code=emp_code,
                pay_comp_add_ded_code__in=pay_comp_codes,
                leave_reason_code=leave_reason_code
            ).aggregate(
                total_amount=Sum('amount')
            )
        elif pay_comp_codes:
            # Annual Leave and LSL use IQBDetail with pay_comp_codes
            leave_taken_aggregation = IQBDetail.objects.filter(
                upload=iqb_upload,
                employee_code=emp_code,
                pay_comp_code__in=pay_comp_codes
            ).aggregate(
                total_amount=Sum('amount')
            )
        else:
            # Fallback to transaction_type
            leave_taken_aggregation = IQBDetail.objects.filter(
                upload=iqb_upload,
                employee_code=emp_code,
                transaction_type=transaction_type
            ).aggregate(
                total_amount=Sum('amount')
            )

        leave_taken = leave_taken_aggregation['total_amount'] or Decimal('0')

        # Calculate base accrual: Closing - Opening + Leave Taken
        base_accrual = closing_value - opening_value + leave_taken

        # Apply LSL probability if this is Long Service Leave
        if leave_type == 'Long Service Leave':
            # Get closing probability based on closing years of service
            closing_years = emp_record.years_of_service if emp_record else None
            closing_probability = LSLProbability.get_probability(closing_years)

            # Get opening probability based on opening years of service
            opening_years = opening_record.years_of_service if opening_record else None
            opening_probability = LSLProbability.get_probability(opening_years)

            # New formula: (C/B × closing prob) - (O/B × opening prob) + leave taken
            accrual_amount = (closing_value * closing_probability) - (opening_value * opening_probability) + leave_taken

            # Determine GL liability account based on closing years of service
            # If <= 7 years: 2705 (LSL Provision - Non-current)
            # If > 7 years: 2330 (LSL Provision - Current)
            if closing_years is not None and closing_years <= 7:
                gl_liability_account = '2705'
            else:
                gl_liability_account = '2330'
        else:
            closing_years = None
            closing_probability = None
            opening_years = None
            opening_probability = None
            accrual_amount = base_accrual

        # Calculate oncosts
        super_amount = accrual_amount * Decimal('0.12')
        prt_amount = accrual_amount * Decimal('0.0495')
        workcover_amount = accrual_amount * Decimal('0.01384')
        total_with_oncosts = accrual_amount + super_amount + prt_amount + workcover_amount

        # Get employee allocation from TP period snapshot
        try:
            snapshot = EmployeePayPeriodSnapshot.objects.get(
                pay_period=tp_pay_period,
                employee_code=emp_code
            )
            cost_allocation = snapshot.cost_allocation or {}
        except EmployeePayPeriodSnapshot.DoesNotExist:
            # No snapshot - use employee's default cost account
            from reconciliation.models import Employee, CostCenterSplit
            try:
                employee = Employee.objects.get(code=emp_code)
                cost_allocation = {}

                if employee.default_cost_account:
                    # Check if this is a SPL- account
                    if employee.default_cost_account.startswith('SPL-'):
                        # Look up all split targets for this source account
                        splits = CostCenterSplit.objects.filter(
                            source_account=employee.default_cost_account,
                            is_active=True
                        )
                        for split in splits:
                            target_account = split.target_account
                            split_pct = split.percentage
                            # Parse target account (format: location-department)
                            if '-' in target_account:
                                parts = target_account.split('-')
                                if len(parts) >= 2:
                                    location_code = parts[0]
                                    dept_code = parts[1]
                                    if location_code not in cost_allocation:
                                        cost_allocation[location_code] = {}
                                    cost_allocation[location_code][dept_code] = float(split_pct)
                    else:
                        # Parse default_cost_account (format: location-department)
                        if '-' in employee.default_cost_account:
                            parts = employee.default_cost_account.split('-')
                            if len(parts) >= 2:
                                location_code = parts[0]
                                dept_code = parts[1]
                                cost_allocation = {location_code: {dept_code: 100.0}}

                # If still no cost allocation, skip this employee
                if not cost_allocation:
                    continue

                snapshot = None  # No snapshot exists
            except Employee.DoesNotExist:
                # No employee record either - skip
                continue

        accruals.append({
            'employee_code': emp_code,
            'employee_name': emp_name,
            'opening_value': opening_value,
            'closing_value': closing_value,
            'leave_taken': leave_taken,
            'base_accrual': base_accrual,  # Base accrual before probability
            'accrual_amount': accrual_amount,  # Final accrual after probability (if LSL)
            'opening_years_of_service': opening_years,  # For LSL tracking
            'closing_years_of_service': closing_years,  # For LSL tracking
            'opening_probability': opening_probability,  # For LSL tracking
            'closing_probability': closing_probability,  # For LSL tracking
            'super_amount': super_amount,
            'prt_amount': prt_amount,
            'workcover_amount': workcover_amount,
            'total_with_oncosts': total_with_oncosts,
            'cost_allocation': cost_allocation,
            'gl_liability': gl_liability_account,
            'gl_expense': gl_expense_account,
            'snapshot': snapshot  # Keep reference to update later
        })

    return accruals


def _aggregate_journal_by_location_department(accruals, location_lookup, department_lookup):
    """
    Aggregate journal entries by location and department

    For each employee accrual:
    1. Take the accrual_amount (with LSL probability already applied if applicable)
    2. Split according to their cost_allocation percentages
    3. Truncate department ID to first 2 characters (e.g., "4200" → "42")
    4. Create journal entries:
       - DR expense account, CR liability account (using accrual_amount)
       - DR oncost accounts (super/PRT/workcover), CR 2055
    """
    from collections import defaultdict

    aggregated = defaultdict(lambda: Decimal('0'))

    for accrual in accruals:
        for location_id, departments in accrual['cost_allocation'].items():
            for dept_id, percentage in departments.items():
                # Truncate department ID to first 2 characters
                dept_id_truncated = dept_id[:2] if len(dept_id) >= 2 else dept_id

                allocation_pct = Decimal(str(percentage)) / Decimal('100')

                # Base accrual entry
                # DR expense, CR liability
                base = accrual['accrual_amount'] * allocation_pct
                if base != 0:
                    aggregated[(location_id, dept_id_truncated, accrual['gl_expense'], 'debit')] += base
                    aggregated[(location_id, dept_id_truncated, accrual['gl_liability'], 'credit')] += base

                # Oncosts entries
                # DR oncost expense accounts, CR 2055
                for (gl_dr, amount_key) in [('6370', 'super_amount'), ('6335', 'prt_amount'), ('6380', 'workcover_amount')]:
                    amt = accrual[amount_key] * allocation_pct
                    if amt != 0:
                        aggregated[(location_id, dept_id_truncated, gl_dr, 'debit')] += amt
                        aggregated[(location_id, dept_id_truncated, '2055', 'credit')] += amt

    # Convert aggregated dict to list of journal entries
    journal_entries = []
    for (location_id, dept_id, gl_account, dr_cr), amount in aggregated.items():
        existing = next((e for e in journal_entries
                        if e['location_id'] == location_id
                        and e['dept_id'] == dept_id
                        and e['gl_account'] == gl_account), None)

        if existing:
            if dr_cr == 'debit':
                existing['debit'] += amount
            else:
                existing['credit'] += amount
        else:
            journal_entries.append({
                'location_id': location_id,
                'location_name': location_lookup.get(location_id, ''),
                'dept_id': dept_id,
                'dept_name': department_lookup.get(dept_id, ''),
                'gl_account': gl_account,
                'debit': amount if dr_cr == 'debit' else Decimal('0'),
                'credit': amount if dr_cr == 'credit' else Decimal('0')
            })

    journal_entries.sort(key=lambda x: (x['location_id'], x['dept_id'], x['gl_account']))
    return journal_entries


def _render_leave_accrual_from_cache(request, lp_pay_period, tp_pay_period,
                                     opening_upload, closing_upload, iqb_upload):
    """
    Render leave accrual journal from cached data in EmployeePayPeriodSnapshot
    This is much faster than recalculating from scratch
    """
    location_lookup = {loc.location_id: loc.location_name for loc in SageLocation.objects.all()}
    department_lookup = {dept.department_id: dept.department_name for dept in SageDepartment.objects.all()}

    # Retrieve snapshots with accrual data
    snapshots = EmployeePayPeriodSnapshot.objects.filter(
        pay_period=tp_pay_period,
        accrual_period_start=lp_pay_period.period_end,
        accrual_period_end=tp_pay_period.period_end
    ).select_related('pay_period')

    # Rebuild accrual lists from cached data
    annual_leave_accruals = []
    lsl_accruals = []
    toil_accruals = []

    for snapshot in snapshots:
        if not snapshot.cost_allocation:
            continue

        # Get opening/closing/leave taken from original sources
        emp_code = snapshot.employee_code

        # Annual Leave
        if snapshot.accrual_annual_leave != 0:
            opening_agg = IQBLeaveBalance.objects.filter(
                upload=opening_upload, employee_code=emp_code, leave_type='Annual Leave'
            ).aggregate(total_balance=Sum('balance_value'), total_loading=Sum('leave_loading'))
            opening_value = (opening_agg['total_balance'] or Decimal('0')) + (opening_agg['total_loading'] or Decimal('0'))

            closing_agg = IQBLeaveBalance.objects.filter(
                upload=closing_upload, employee_code=emp_code, leave_type='Annual Leave'
            ).aggregate(total_balance=Sum('balance_value'), total_loading=Sum('leave_loading'))
            closing_value = (closing_agg['total_balance'] or Decimal('0')) + (closing_agg['total_loading'] or Decimal('0'))

            # Annual Leave taken includes: Annual, LLV, TPo93ALG, TPo93LLG pay comp codes
            leave_taken_agg = IQBDetail.objects.filter(
                upload=iqb_upload, employee_code=emp_code,
                pay_comp_code__in=['Annual', 'LLV', 'TPo93ALG', 'TPo93LLG']
            ).aggregate(total=Sum('amount'))
            leave_taken = leave_taken_agg['total'] or Decimal('0')

            base_accrual = closing_value - opening_value + leave_taken
            accrual_amount = snapshot.accrual_annual_leave
            super_amount = accrual_amount * Decimal('0.12')
            prt_amount = accrual_amount * Decimal('0.0495')
            workcover_amount = accrual_amount * Decimal('0.01384')

            annual_leave_accruals.append({
                'employee_code': emp_code,
                'employee_name': snapshot.employee_name,
                'opening_value': opening_value,
                'closing_value': closing_value,
                'leave_taken': leave_taken,
                'base_accrual': base_accrual,
                'accrual_amount': accrual_amount,
                'super_amount': super_amount,
                'prt_amount': prt_amount,
                'workcover_amount': workcover_amount,
                'total_with_oncosts': accrual_amount + super_amount + prt_amount + workcover_amount,
                'cost_allocation': snapshot.cost_allocation,
                'gl_liability': '2310',
                'gl_expense': '6300',
                'snapshot': snapshot
            })

        # Long Service Leave
        if snapshot.accrual_long_service_leave != 0:
            opening_agg = IQBLeaveBalance.objects.filter(
                upload=opening_upload, employee_code=emp_code, leave_type='Long Service Leave'
            ).aggregate(total_balance=Sum('balance_value'), total_loading=Sum('leave_loading'))
            opening_value = (opening_agg['total_balance'] or Decimal('0')) + (opening_agg['total_loading'] or Decimal('0'))

            closing_agg = IQBLeaveBalance.objects.filter(
                upload=closing_upload, employee_code=emp_code, leave_type='Long Service Leave'
            ).aggregate(total_balance=Sum('balance_value'), total_loading=Sum('leave_loading'))
            closing_value = (closing_agg['total_balance'] or Decimal('0')) + (closing_agg['total_loading'] or Decimal('0'))

            # Long Service Leave taken includes: LSL, TPo93LSLG pay comp codes
            leave_taken_agg = IQBDetail.objects.filter(
                upload=iqb_upload, employee_code=emp_code,
                pay_comp_code__in=['LSL', 'TPo93LSLG']
            ).aggregate(total=Sum('amount'))
            leave_taken = leave_taken_agg['total'] or Decimal('0')

            base_accrual = closing_value - opening_value + leave_taken
            accrual_amount = snapshot.accrual_long_service_leave
            super_amount = accrual_amount * Decimal('0.12')
            prt_amount = accrual_amount * Decimal('0.0495')
            workcover_amount = accrual_amount * Decimal('0.01384')

            # Determine LSL GL liability account based on closing years of service
            closing_record = IQBLeaveBalance.objects.filter(
                upload=closing_upload, employee_code=emp_code, leave_type='Long Service Leave'
            ).first()
            closing_years = closing_record.years_of_service if closing_record else None
            if closing_years is not None and closing_years <= 7:
                lsl_gl_liability = '2705'
            else:
                lsl_gl_liability = '2330'

            lsl_accruals.append({
                'employee_code': emp_code,
                'employee_name': snapshot.employee_name,
                'opening_value': opening_value,
                'closing_value': closing_value,
                'leave_taken': leave_taken,
                'base_accrual': base_accrual,
                'accrual_amount': accrual_amount,
                'super_amount': super_amount,
                'prt_amount': prt_amount,
                'workcover_amount': workcover_amount,
                'total_with_oncosts': accrual_amount + super_amount + prt_amount + workcover_amount,
                'cost_allocation': snapshot.cost_allocation,
                'gl_liability': lsl_gl_liability,
                'gl_expense': '6345',
                'snapshot': snapshot
            })

        # TOIL
        if snapshot.accrual_toil != 0:
            opening_agg = IQBLeaveBalance.objects.filter(
                upload=opening_upload, employee_code=emp_code, leave_type='User Defined Leave'
            ).aggregate(total_balance=Sum('balance_value'), total_loading=Sum('leave_loading'))
            opening_value = (opening_agg['total_balance'] or Decimal('0')) + (opening_agg['total_loading'] or Decimal('0'))

            closing_agg = IQBLeaveBalance.objects.filter(
                upload=closing_upload, employee_code=emp_code, leave_type='User Defined Leave'
            ).aggregate(total_balance=Sum('balance_value'), total_loading=Sum('leave_loading'))
            closing_value = (closing_agg['total_balance'] or Decimal('0')) + (closing_agg['total_loading'] or Decimal('0'))

            # TOIL taken uses IQBDetailV2 with pay_comp_code='UDLeave' and leave_reason_code='TIL Taken'
            leave_taken_agg = IQBDetailV2.objects.filter(
                upload=iqb_upload, employee_code=emp_code,
                pay_comp_add_ded_code='UDLeave', leave_reason_code='TIL Taken'
            ).aggregate(total=Sum('amount'))
            leave_taken = leave_taken_agg['total'] or Decimal('0')

            base_accrual = closing_value - opening_value + leave_taken
            accrual_amount = snapshot.accrual_toil
            super_amount = accrual_amount * Decimal('0.12')
            prt_amount = accrual_amount * Decimal('0.0495')
            workcover_amount = accrual_amount * Decimal('0.01384')

            toil_accruals.append({
                'employee_code': emp_code,
                'employee_name': snapshot.employee_name,
                'opening_value': opening_value,
                'closing_value': closing_value,
                'leave_taken': leave_taken,
                'base_accrual': base_accrual,
                'accrual_amount': accrual_amount,
                'super_amount': super_amount,
                'prt_amount': prt_amount,
                'workcover_amount': workcover_amount,
                'total_with_oncosts': accrual_amount + super_amount + prt_amount + workcover_amount,
                'cost_allocation': snapshot.cost_allocation,
                'gl_liability': '2317',
                'gl_expense': '6372',
                'snapshot': snapshot
            })

    # Aggregate journal entries
    annual_journal = _aggregate_journal_by_location_department(annual_leave_accruals, location_lookup, department_lookup)
    lsl_journal = _aggregate_journal_by_location_department(lsl_accruals, location_lookup, department_lookup)
    toil_journal = _aggregate_journal_by_location_department(toil_accruals, location_lookup, department_lookup)

    # Calculate totals using the same logic as main view
    def calc_totals(leave_type, gl_liability, accruals, journal, transaction_type=None,
                    pay_comp_codes=None, use_iqb_v2=False, leave_reason_code=None):
        opening_agg = IQBLeaveBalance.objects.filter(
            upload=opening_upload, leave_type=leave_type
        ).aggregate(total_balance=Sum('balance_value'), total_loading=Sum('leave_loading'))
        total_opening = (opening_agg['total_balance'] or Decimal('0')) + (opening_agg['total_loading'] or Decimal('0'))

        closing_agg = IQBLeaveBalance.objects.filter(
            upload=closing_upload, leave_type=leave_type
        ).aggregate(total_balance=Sum('balance_value'), total_loading=Sum('leave_loading'))
        total_closing = (closing_agg['total_balance'] or Decimal('0')) + (closing_agg['total_loading'] or Decimal('0'))

        # Use IQBDetailV2 for TOIL (requires leave_reason_code filter)
        if use_iqb_v2 and pay_comp_codes and leave_reason_code:
            leave_taken_agg = IQBDetailV2.objects.filter(
                upload=iqb_upload, pay_comp_add_ded_code__in=pay_comp_codes, leave_reason_code=leave_reason_code
            ).aggregate(total=Sum('amount'))
        elif pay_comp_codes:
            leave_taken_agg = IQBDetail.objects.filter(
                upload=iqb_upload, pay_comp_code__in=pay_comp_codes
            ).aggregate(total=Sum('amount'))
        else:
            leave_taken_agg = IQBDetail.objects.filter(
                upload=iqb_upload, transaction_type=transaction_type
            ).aggregate(total=Sum('amount'))
        total_leave_taken = leave_taken_agg['total'] or Decimal('0')

        # Calculate base accrual from aggregate totals (formula: Closing - Opening + Leave Taken)
        # This includes ALL employees with leave balances, regardless of whether they have snapshots
        total_base_calculated = total_closing - total_opening + total_leave_taken

        # Calculate oncosts from total_base (includes ALL employees)
        total_super_calculated = total_base_calculated * Decimal('0.12')
        total_prt_calculated = total_base_calculated * Decimal('0.0495')
        total_workcover_calculated = total_base_calculated * Decimal('0.01384')
        total_with_oncosts_calculated = total_base_calculated + total_super_calculated + total_prt_calculated + total_workcover_calculated

        # For LSL, also track the accrual after probability is applied
        total_accrual_from_employees = sum(a['accrual_amount'] for a in accruals)

        return {
            'employee_count': len(accruals),
            'total_opening': total_opening,
            'total_closing': total_closing,
            'total_leave_taken': total_leave_taken,
            'total_base': total_base_calculated,  # Includes ALL employees (aggregate totals)
            'total_accrual': total_accrual_from_employees,  # Sum of individual accruals (with LSL probability applied if applicable)
            'total_super': total_super_calculated,  # 12% of total_base (ALL employees)
            'total_prt': total_prt_calculated,  # 4.95% of total_base (ALL employees)
            'total_workcover': total_workcover_calculated,  # 1.384% of total_base (ALL employees)
            'total_with_oncosts': total_with_oncosts_calculated,  # total_base + oncosts (ALL employees)
            'total_debit': sum(j['debit'] for j in journal),
            'total_credit': sum(j['credit'] for j in journal),
        }

    # Annual Leave taken includes: Annual, LLV, TPo93ALG, TPo93LLG pay comp codes
    annual_totals = calc_totals('Annual Leave', '2310', annual_leave_accruals, annual_journal,
                                pay_comp_codes=['Annual', 'LLV', 'TPo93ALG', 'TPo93LLG'])
    # Long Service Leave taken includes: LSL, TPo93LSLG pay comp codes
    # Note: LSL uses multiple GL accounts (2705 and 2330) based on years of service
    lsl_totals = calc_totals('Long Service Leave', None, lsl_accruals, lsl_journal,
                             pay_comp_codes=['LSL', 'TPo93LSLG'])
    # TOIL taken uses IQBDetailV2 with pay_comp_code='UDLeave' and leave_reason_code='TIL Taken'
    toil_totals = calc_totals('User Defined Leave', '2317', toil_accruals, toil_journal,
                              pay_comp_codes=['UDLeave'], use_iqb_v2=True, leave_reason_code='TIL Taken')

    annual_balanced = abs(annual_totals['total_debit'] - annual_totals['total_credit']) < Decimal('0.01')
    lsl_balanced = abs(lsl_totals['total_debit'] - lsl_totals['total_credit']) < Decimal('0.01')
    toil_balanced = abs(toil_totals['total_debit'] - toil_totals['total_credit']) < Decimal('0.01')

    context = {
        'pay_period': tp_pay_period,
        'lp_pay_period': lp_pay_period,
        'tp_pay_period': tp_pay_period,
        'opening_date': lp_pay_period.period_end,
        'closing_date': tp_pay_period.period_end,
        'annual_accruals': annual_leave_accruals,
        'annual_journal': annual_journal,
        'annual_totals': annual_totals,
        'annual_balanced': annual_balanced,
        'lsl_accruals': lsl_accruals,
        'lsl_journal': lsl_journal,
        'lsl_totals': lsl_totals,
        'lsl_balanced': lsl_balanced,
        'toil_accruals': toil_accruals,
        'toil_journal': toil_journal,
        'toil_totals': toil_totals,
        'toil_balanced': toil_balanced,
        'cached_data': True,  # Flag to show user this was retrieved from cache
    }

    return render(request, 'reconciliation/leave_accrual_journal.html', context)


def leave_accrual_auto_period(request, this_period_id):
    """
    Wrapper view that auto-determines the previous pay period for leave accrual
    Routes to generate_leave_accrual_journal with both period IDs

    Finds the most recent previous period that has an IQB Leave Balance file uploaded.
    """
    tp_pay_period = get_object_or_404(PayPeriod, period_id=this_period_id)

    # Find the most recent previous pay period that has an IQB Leave Balance file
    previous_periods = PayPeriod.objects.filter(
        period_end__lt=tp_pay_period.period_end
    ).order_by('-period_end')

    previous_period = None
    for period in previous_periods:
        # Check if this period has an IQB Leave Balance file
        has_leave_file = Upload.objects.filter(
            pay_period=period,
            source_system='Micropay_IQB_Leave',
            is_active=True
        ).exists()
        if has_leave_file:
            previous_period = period
            break

    if not previous_period:
        return render(request, 'reconciliation/leave_accrual_error.html', {
            'error': f'No previous pay period with IQB Leave Balance file found before {this_period_id}',
            'pay_period': tp_pay_period
        })

    # Route to the main view with both periods
    return generate_leave_accrual_journal(request, previous_period.period_id, this_period_id)


def generate_leave_accrual_journal(request, last_period_id, this_period_id):
    """
    Generate Leave accrual journal entries with oncosts for Annual Leave, LSL, and TOIL

    Formula: Accrual = Closing Balance - Opening Balance + Leave Taken

    Annual Leave:
    - Base: DR 6300, CR 2310
    - Super 12%: DR 6370, CR 2055
    - PRT 4.95%: DR 6335, CR 2055
    - Workcover 1.384%: DR 6380, CR 2055

    Long Service Leave:
    - Base: DR 6345, CR 2705 (if years of service <= 7) or CR 2330 (if years of service > 7)
    - Super/PRT/Workcover: CR 2055

    Time-in-Lieu (User Defined Leave):
    - Base: DR 6372, CR 2317
    - Super/PRT/Workcover: CR 2055

    Args:
        last_period_id: Pay Period ID for Last Period (LP) - opening balance
        this_period_id: Pay Period ID for This Period (TP) - closing balance
    """
    # Get pay periods
    lp_pay_period = get_object_or_404(PayPeriod, period_id=last_period_id)
    tp_pay_period = get_object_or_404(PayPeriod, period_id=this_period_id)

    # Get opening balance upload (LP)
    opening_upload = Upload.objects.filter(
        pay_period=lp_pay_period,
        source_system='Micropay_IQB_Leave',
        is_active=True
    ).first()

    if not opening_upload:
        return render(request, 'reconciliation/leave_accrual_error.html', {
            'error': f'No IQB Leave Balance file (LP) found for pay period {last_period_id}',
            'pay_period': lp_pay_period
        })

    # Get closing balance upload (TP)
    closing_upload = Upload.objects.filter(
        pay_period=tp_pay_period,
        source_system='Micropay_IQB_Leave',
        is_active=True
    ).first()

    if not closing_upload:
        return render(request, 'reconciliation/leave_accrual_error.html', {
            'error': f'No IQB Leave Balance file (TP) found for pay period {this_period_id}',
            'pay_period': tp_pay_period
        })

    # Get IQB Detail upload (RET002) from TP period
    iqb_upload = Upload.objects.filter(
        pay_period=tp_pay_period,
        source_system='Micropay_IQB',
        is_active=True
    ).first()

    if not iqb_upload:
        return render(request, 'reconciliation/leave_accrual_error.html', {
            'error': f'No IQB Detail file (RET002) found for pay period {this_period_id}',
            'pay_period': tp_pay_period
        })

    # Check if user wants to force recalculation
    force_recalc = request.GET.get('recalc', '').lower() == 'true'

    # Check if cached accrual data exists for this period range
    accrual_start_date = lp_pay_period.period_end
    accrual_end_date = tp_pay_period.period_end

    if not force_recalc:
        # Check if we have cached accrual data
        cached_snapshots = EmployeePayPeriodSnapshot.objects.filter(
            pay_period=tp_pay_period,
            accrual_period_start=accrual_start_date,
            accrual_period_end=accrual_end_date
        ).exclude(
            accrual_annual_leave=0,
            accrual_long_service_leave=0,
            accrual_toil=0
        )

        if cached_snapshots.exists():
            # Data exists - retrieve from database instead of recalculating
            return _render_leave_accrual_from_cache(
                request, lp_pay_period, tp_pay_period,
                opening_upload, closing_upload, iqb_upload
            )

    # Location and department lookups
    location_lookup = {loc.location_id: loc.location_name for loc in SageLocation.objects.all()}
    department_lookup = {dept.department_id: dept.department_name for dept in SageDepartment.objects.all()}

    # Calculate accruals for all three leave types
    # Annual Leave taken includes: Annual, LLV, TPo93ALG, TPo93LLG pay comp codes
    annual_leave_accruals = _calculate_leave_accruals_for_type(
        'Annual Leave', '2310', '6300',
        opening_upload, closing_upload, iqb_upload, tp_pay_period,
        pay_comp_codes=['Annual', 'LLV', 'TPo93ALG', 'TPo93LLG']
    )

    # Long Service Leave taken includes: LSL, TPo93LSLG pay comp codes
    # Note: GL liability account will be determined per employee based on years of service
    # (2705 if <= 7 years, 2330 if > 7 years)
    lsl_accruals = _calculate_leave_accruals_for_type(
        'Long Service Leave', None, '6345',
        opening_upload, closing_upload, iqb_upload, tp_pay_period,
        pay_comp_codes=['LSL', 'TPo93LSLG']
    )

    # TOIL taken uses IQBDetailV2 with pay_comp_code='UDLeave' and leave_reason_code='TIL Taken'
    toil_accruals = _calculate_leave_accruals_for_type(
        'User Defined Leave', '2317', '6372',
        opening_upload, closing_upload, iqb_upload, tp_pay_period,
        pay_comp_codes=['UDLeave'], use_iqb_v2=True, leave_reason_code='TIL Taken'
    )

    # Store accruals in EmployeePayPeriodSnapshot for TP period
    from django.utils import timezone
    from datetime import datetime

    # Get period dates for accrual information
    accrual_start_date = lp_pay_period.period_end  # Opening balance date (LP period end)
    accrual_end_date = tp_pay_period.period_end  # Closing balance date (TP period end)

    for accrual in annual_leave_accruals:
        snapshot = accrual['snapshot']
        if snapshot:  # Only save if snapshot exists (not using default cost account)
            snapshot.accrual_annual_leave = accrual['accrual_amount']
            snapshot.accrual_period_start = accrual_start_date
            snapshot.accrual_period_end = accrual_end_date
            snapshot.save(update_fields=['accrual_annual_leave', 'accrual_period_start', 'accrual_period_end'])

    for accrual in lsl_accruals:
        snapshot = accrual['snapshot']
        if snapshot:  # Only save if snapshot exists (not using default cost account)
            snapshot.accrual_long_service_leave = accrual['accrual_amount']
            snapshot.accrual_period_start = accrual_start_date
            snapshot.accrual_period_end = accrual_end_date
            snapshot.save(update_fields=['accrual_long_service_leave', 'accrual_period_start', 'accrual_period_end'])

    for accrual in toil_accruals:
        snapshot = accrual['snapshot']
        if snapshot:  # Only save if snapshot exists (not using default cost account)
            snapshot.accrual_toil = accrual['accrual_amount']
            snapshot.accrual_period_start = accrual_start_date
            snapshot.accrual_period_end = accrual_end_date
            snapshot.save(update_fields=['accrual_toil', 'accrual_period_start', 'accrual_period_end'])

    # Aggregate journal entries by location/department
    annual_journal = _aggregate_journal_by_location_department(annual_leave_accruals, location_lookup, department_lookup)
    lsl_journal = _aggregate_journal_by_location_department(lsl_accruals, location_lookup, department_lookup)
    toil_journal = _aggregate_journal_by_location_department(toil_accruals, location_lookup, department_lookup)

    # Calculate totals for each leave type
    def calc_totals(leave_type, gl_liability, accruals, journal, transaction_type=None,
                    pay_comp_codes=None, use_iqb_v2=False, leave_reason_code=None):
        # Calculate opening/closing/leave taken for ALL employees (not just those with accruals)
        from django.db.models import Sum

        # Opening balance total (ALL employees with this leave type)
        opening_agg = IQBLeaveBalance.objects.filter(
            upload=opening_upload,
            leave_type=leave_type
        ).aggregate(
            total_balance=Sum('balance_value'),
            total_loading=Sum('leave_loading')
        )
        total_opening = (opening_agg['total_balance'] or Decimal('0')) + (opening_agg['total_loading'] or Decimal('0'))

        # Closing balance total (ALL employees with this leave type)
        closing_agg = IQBLeaveBalance.objects.filter(
            upload=closing_upload,
            leave_type=leave_type
        ).aggregate(
            total_balance=Sum('balance_value'),
            total_loading=Sum('leave_loading')
        )
        total_closing = (closing_agg['total_balance'] or Decimal('0')) + (closing_agg['total_loading'] or Decimal('0'))

        # Leave taken total (ALL employees)
        # Use IQBDetailV2 for TOIL (requires leave_reason_code filter)
        if use_iqb_v2 and pay_comp_codes and leave_reason_code:
            leave_taken_agg = IQBDetailV2.objects.filter(
                upload=iqb_upload, pay_comp_add_ded_code__in=pay_comp_codes, leave_reason_code=leave_reason_code
            ).aggregate(total=Sum('amount'))
        elif pay_comp_codes:
            leave_taken_agg = IQBDetail.objects.filter(
                upload=iqb_upload, pay_comp_code__in=pay_comp_codes
            ).aggregate(total=Sum('amount'))
        else:
            leave_taken_agg = IQBDetail.objects.filter(
                upload=iqb_upload, transaction_type=transaction_type
            ).aggregate(total=Sum('amount'))
        total_leave_taken = leave_taken_agg['total'] or Decimal('0')

        # Calculate base accrual from aggregate totals (formula: Closing - Opening + Leave Taken)
        # This includes ALL employees with leave balances, regardless of whether they have snapshots
        total_base_calculated = total_closing - total_opening + total_leave_taken

        # Calculate oncosts from total_base (includes ALL employees)
        total_super_calculated = total_base_calculated * Decimal('0.12')
        total_prt_calculated = total_base_calculated * Decimal('0.0495')
        total_workcover_calculated = total_base_calculated * Decimal('0.01384')
        total_with_oncosts_calculated = total_base_calculated + total_super_calculated + total_prt_calculated + total_workcover_calculated

        # For LSL, also track the accrual after probability is applied
        total_accrual_from_employees = sum(a['accrual_amount'] for a in accruals)

        return {
            'employee_count': len(accruals),
            'total_opening': total_opening,
            'total_closing': total_closing,
            'total_leave_taken': total_leave_taken,
            'total_base': total_base_calculated,  # Includes ALL employees (aggregate totals)
            'total_accrual': total_accrual_from_employees,  # Sum of individual accruals (with LSL probability applied if applicable)
            'total_super': total_super_calculated,  # 12% of total_base (ALL employees)
            'total_prt': total_prt_calculated,  # 4.95% of total_base (ALL employees)
            'total_workcover': total_workcover_calculated,  # 1.384% of total_base (ALL employees)
            'total_with_oncosts': total_with_oncosts_calculated,  # total_base + oncosts (ALL employees)
            'total_debit': sum(j['debit'] for j in journal),
            'total_credit': sum(j['credit'] for j in journal),
        }

    # Annual Leave taken includes: Annual, LLV, TPo93ALG, TPo93LLG pay comp codes
    annual_totals = calc_totals('Annual Leave', '2310', annual_leave_accruals, annual_journal,
                                pay_comp_codes=['Annual', 'LLV', 'TPo93ALG', 'TPo93LLG'])
    # Long Service Leave taken includes: LSL, TPo93LSLG pay comp codes
    # Note: LSL uses multiple GL accounts (2705 and 2330) based on years of service
    lsl_totals = calc_totals('Long Service Leave', None, lsl_accruals, lsl_journal,
                             pay_comp_codes=['LSL', 'TPo93LSLG'])
    # TOIL taken uses IQBDetailV2 with pay_comp_code='UDLeave' and leave_reason_code='TIL Taken'
    toil_totals = calc_totals('User Defined Leave', '2317', toil_accruals, toil_journal,
                              pay_comp_codes=['UDLeave'], use_iqb_v2=True, leave_reason_code='TIL Taken')

    # Check if balanced
    annual_balanced = abs(annual_totals['total_debit'] - annual_totals['total_credit']) < Decimal('0.01')
    lsl_balanced = abs(lsl_totals['total_debit'] - lsl_totals['total_credit']) < Decimal('0.01')
    toil_balanced = abs(toil_totals['total_debit'] - toil_totals['total_credit']) < Decimal('0.01')

    context = {
        'pay_period': tp_pay_period,  # Use TP period as the main period
        'lp_pay_period': lp_pay_period,  # Also pass LP period
        'tp_pay_period': tp_pay_period,
        'opening_date': lp_pay_period.period_end,
        'closing_date': tp_pay_period.period_end,

        # Annual Leave
        'annual_accruals': annual_leave_accruals,
        'annual_journal': annual_journal,
        'annual_totals': annual_totals,
        'annual_balanced': annual_balanced,

        # Long Service Leave
        'lsl_accruals': lsl_accruals,
        'lsl_journal': lsl_journal,
        'lsl_totals': lsl_totals,
        'lsl_balanced': lsl_balanced,

        # Time-in-Lieu
        'toil_accruals': toil_accruals,
        'toil_journal': toil_journal,
        'toil_totals': toil_totals,
        'toil_balanced': toil_balanced,
    }

    return render(request, 'reconciliation/leave_accrual_journal.html', context)



def download_leave_journal_sage(request, last_period_id, this_period_id, leave_type):
    """Download leave accrual journal in Sage Intacct format"""
    # Map leave type to correct parameters (same as employee breakdown CSV and main journal view)
    leave_configs = {
        'annual': {
            'name': 'Annual Leave',
            'liability': '2310',
            'expense': '6300',
            'pay_comp_codes': ['Annual', 'LLV', 'TPo93ALG', 'TPo93LLG'],
            'use_iqb_v2': False
        },
        'lsl': {
            'name': 'Long Service Leave',
            'liability': None,  # Determined per employee based on years of service (2705 or 2330)
            'expense': '6345',
            'pay_comp_codes': ['LSL', 'TPo93LSLG'],
            'use_iqb_v2': False
        },
        'toil': {
            'name': 'User Defined Leave',
            'liability': '2317',
            'expense': '6372',
            'pay_comp_codes': ['UDLeave'],
            'use_iqb_v2': True,
            'leave_reason_code': 'TIL Taken'
        },
    }

    if leave_type not in leave_configs:
        return HttpResponse("Invalid leave type", status=400)

    config = leave_configs[leave_type]
    lp_pay_period = get_object_or_404(PayPeriod, period_id=last_period_id)
    tp_pay_period = get_object_or_404(PayPeriod, period_id=this_period_id)

    # Get uploads from specific periods
    opening_upload = Upload.objects.filter(
        pay_period=lp_pay_period, source_system='Micropay_IQB_Leave', is_active=True
    ).first()
    closing_upload = Upload.objects.filter(
        pay_period=tp_pay_period, source_system='Micropay_IQB_Leave', is_active=True
    ).first()
    iqb_upload = Upload.objects.filter(
        pay_period=tp_pay_period, source_system='Micropay_IQB', is_active=True
    ).first()

    if not all([closing_upload, opening_upload, iqb_upload]):
        return HttpResponse("Missing required uploads", status=400)

    location_lookup = {loc.location_id: loc.location_name for loc in SageLocation.objects.all()}
    department_lookup = {dept.department_id: dept.department_name for dept in SageDepartment.objects.all()}

    # Calculate accruals using the same logic as employee breakdown and main journal view
    accruals = _calculate_leave_accruals_for_type(
        config['name'], config['liability'], config['expense'],
        opening_upload, closing_upload, iqb_upload, tp_pay_period,
        pay_comp_codes=config['pay_comp_codes'],
        use_iqb_v2=config.get('use_iqb_v2', False),
        leave_reason_code=config.get('leave_reason_code', None)
    )
    
    journal = _aggregate_journal_by_location_department(accruals, location_lookup, department_lookup)

    # Generate Sage Intacct CSV
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{leave_type}_journal_sage_{last_period_id}_to_{this_period_id}.csv"'

    writer = csv.writer(response)

    # Write header row in Sage Intacct format
    writer.writerow([
        'DONOTIMPORT', 'JOURNAL', 'DATE', 'DESCRIPTION', 'REFERENCE_NO', 'LINE_NO',
        'ACCT_NO', 'LOCATION_ID', 'DEPT_ID', 'DOCUMENT', 'MEMO', 'DEBIT',
        'BILLABLE', 'GLENTRY_ITEMID', 'GLENTRY_PROJECTID', 'GLENTRY_CUSTOMERID'
    ])

    # Common values
    journal_id = f"{leave_type.upper()}-{this_period_id}"
    date = tp_pay_period.period_end.strftime('%m/%d/%Y')
    description = f"{config['name']} Accrual - {last_period_id} to {this_period_id}"

    line_no = 1
    for entry in journal:
        location_id = entry['location_id']
        dept_id = entry['dept_id']
        gl_account = entry['gl_account']

        # Handle location 700 special case for DEBIT entries
        if location_id == '700' and entry['debit'] != 0:
            # For location 700, debit amounts go to GL 1180 with billable fields
            debit_amount = entry['debit']
            donotimport = '#' if debit_amount == 0 else ''

            writer.writerow([
                donotimport,
                journal_id,
                date,
                description,
                '',  # REFERENCE_NO
                line_no,
                '1180',  # Changed from original GL account to 1180
                location_id,
                dept_id,
                'GL-Batch',
                f"{config['name']} Accrual",
                f"{debit_amount:.2f}",
                'T',  # BILLABLE = T
                'ICO-RECHARGE',  # GLENTRY_ITEMID
                'CMG110-001',  # GLENTRY_PROJECTID
                'CMG110'  # GLENTRY_CUSTOMERID
            ])
            line_no += 1
        elif entry['debit'] != 0:
            # Regular debit entry
            debit_amount = entry['debit']
            donotimport = '#' if debit_amount == 0 else ''

            writer.writerow([
                donotimport,
                journal_id,
                date,
                description,
                '',  # REFERENCE_NO
                line_no,
                gl_account,
                location_id,
                dept_id,
                'GL-Batch',
                f"{config['name']} Accrual",
                f"{debit_amount:.2f}",
                '',  # BILLABLE (blank)
                '',  # GLENTRY_ITEMID (blank)
                '',  # GLENTRY_PROJECTID (blank)
                ''   # GLENTRY_CUSTOMERID (blank)
            ])
            line_no += 1

        # Credit entry (represented as negative debit)
        if entry['credit'] != 0:
            credit_amount = -entry['credit']  # Make it negative
            donotimport = '#' if credit_amount == 0 else ''

            writer.writerow([
                donotimport,
                journal_id,
                date,
                description,
                '',  # REFERENCE_NO
                line_no,
                gl_account,
                location_id,
                dept_id,
                'GL-Batch',
                f"{config['name']} Accrual",
                f"{credit_amount:.2f}",
                '',  # BILLABLE (blank)
                '',  # GLENTRY_ITEMID (blank)
                '',  # GLENTRY_PROJECTID (blank)
                ''   # GLENTRY_CUSTOMERID (blank)
            ])
            line_no += 1

    return response


def download_leave_employee_breakdown(request, last_period_id, this_period_id, leave_type):
    """Download employee-level leave accrual breakdown - combined for all leave types"""
    lp_pay_period = get_object_or_404(PayPeriod, period_id=last_period_id)
    tp_pay_period = get_object_or_404(PayPeriod, period_id=this_period_id)

    # Get uploads from specific periods
    opening_upload = Upload.objects.filter(
        pay_period=lp_pay_period, source_system='Micropay_IQB_Leave', is_active=True
    ).first()
    closing_upload = Upload.objects.filter(
        pay_period=tp_pay_period, source_system='Micropay_IQB_Leave', is_active=True
    ).first()
    iqb_upload = Upload.objects.filter(
        pay_period=tp_pay_period, source_system='Micropay_IQB', is_active=True
    ).first()

    if not all([opening_upload, closing_upload, iqb_upload]):
        return HttpResponse("Missing required uploads", status=400)

    from django.db.models import Sum

    # All leave type configurations with pay_comp_codes for leave taken
    leave_configs = {
        'annual': {
            'name': 'Annual Leave',
            'pay_comp_codes': ['Annual', 'LLV', 'TPo93ALG', 'TPo93LLG'],
            'use_iqb_v2': False
        },
        'lsl': {
            'name': 'Long Service Leave',
            'pay_comp_codes': ['LSL', 'TPo93LSLG'],
            'use_iqb_v2': False
        },
        'toil': {
            'name': 'User Defined Leave',
            'pay_comp_codes': ['UDLeave'],
            'use_iqb_v2': True,
            'leave_reason_code': 'TIL Taken'
        },
    }

    # Get ALL unique employee codes from all leave types
    all_employee_codes = set()
    for config in leave_configs.values():
        closing_emp_codes = set(IQBLeaveBalance.objects.filter(
            upload=closing_upload,
            leave_type=config['name']
        ).values_list('employee_code', flat=True).distinct())
        opening_emp_codes = set(IQBLeaveBalance.objects.filter(
            upload=opening_upload,
            leave_type=config['name']
        ).values_list('employee_code', flat=True).distinct())
        all_employee_codes.update(closing_emp_codes | opening_emp_codes)

    all_employee_codes = sorted(all_employee_codes)

    # Generate combined employee breakdown CSV
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="all_leave_employees_{last_period_id}_to_{this_period_id}.csv"'

    writer = csv.writer(response)

    # Header row with all leave types
    writer.writerow([
        'Employee Code', 'Employee Name', 'Years of Service (Closing)', 'Years of Service (Opening)',
        'Annual Leave - Opening', 'Annual Leave - Closing', 'Annual Leave - Taken', 'Annual Leave - Accrual', 'Annual Leave - Total with Oncosts',
        'LSL - Opening', 'LSL - Closing', 'LSL - Taken', 'LSL - Opening Probability', 'LSL - Closing Probability', 'LSL - Accrual', 'LSL - Total with Oncosts',
        'TOIL - Opening', 'TOIL - Closing', 'TOIL - Taken', 'TOIL - Accrual', 'TOIL - Total with Oncosts',
        'Total Accrual (All Leave)', 'Total with Oncosts (All Leave)'
    ])

    for emp_code in all_employee_codes:
        row_data = [emp_code]

        # Get employee name and years of service from both closing and opening (try to find from any leave type)
        emp_name = emp_code
        closing_years_of_service = Decimal('0')
        opening_years_of_service = Decimal('0')

        for config in leave_configs.values():
            # Get closing record
            closing_emp_record = IQBLeaveBalance.objects.filter(
                upload=closing_upload,
                employee_code=emp_code,
                leave_type=config['name']
            ).first()
            if closing_emp_record:
                emp_name = closing_emp_record.full_name
                closing_years_of_service = closing_emp_record.years_of_service or Decimal('0')

            # Get opening record
            opening_emp_record = IQBLeaveBalance.objects.filter(
                upload=opening_upload,
                employee_code=emp_code,
                leave_type=config['name']
            ).first()
            if opening_emp_record:
                if not emp_name or emp_name == emp_code:
                    emp_name = opening_emp_record.full_name
                opening_years_of_service = opening_emp_record.years_of_service or Decimal('0')

            # Break if we found both
            if closing_emp_record or opening_emp_record:
                break

        row_data.append(emp_name)
        row_data.append(f"{closing_years_of_service:.2f}")
        row_data.append(f"{opening_years_of_service:.2f}")

        total_accrual = Decimal('0')
        total_with_oncosts_all = Decimal('0')

        # Process each leave type
        for leave_key in ['annual', 'lsl', 'toil']:
            config = leave_configs[leave_key]

            # Closing balance (with leave loading)
            closing_aggregation = IQBLeaveBalance.objects.filter(
                upload=closing_upload,
                employee_code=emp_code,
                leave_type=config['name']
            ).aggregate(
                total_balance=Sum('balance_value'),
                total_loading=Sum('leave_loading')
            )
            closing_balance = closing_aggregation['total_balance'] or Decimal('0')
            closing_loading = closing_aggregation['total_loading'] or Decimal('0')
            closing_value = closing_balance + closing_loading

            # Opening balance (with leave loading)
            opening_aggregation = IQBLeaveBalance.objects.filter(
                upload=opening_upload,
                employee_code=emp_code,
                leave_type=config['name']
            ).aggregate(
                total_balance=Sum('balance_value'),
                total_loading=Sum('leave_loading')
            )
            opening_balance = opening_aggregation['total_balance'] or Decimal('0')
            opening_loading = opening_aggregation['total_loading'] or Decimal('0')
            opening_value = opening_balance + opening_loading

            # Leave taken using pay_comp_codes
            if config.get('use_iqb_v2'):
                # TOIL uses IQBDetailV2 with pay_comp_add_ded_code and leave_reason_code
                leave_taken_aggregation = IQBDetailV2.objects.filter(
                    upload=iqb_upload,
                    employee_code=emp_code,
                    pay_comp_add_ded_code__in=config['pay_comp_codes'],
                    leave_reason_code=config['leave_reason_code']
                ).aggregate(total_amount=Sum('amount'))
            else:
                # Annual Leave and LSL use IQBDetail with pay_comp_codes
                leave_taken_aggregation = IQBDetail.objects.filter(
                    upload=iqb_upload,
                    employee_code=emp_code,
                    pay_comp_code__in=config['pay_comp_codes']
                ).aggregate(total_amount=Sum('amount'))
            leave_taken = leave_taken_aggregation['total_amount'] or Decimal('0')

            # Calculate base accrual
            base_accrual = closing_value - opening_value + leave_taken

            # Apply LSL probability if this is LSL
            from reconciliation.models import LSLProbability
            if leave_key == 'lsl':
                # Get separate probabilities for opening and closing
                opening_probability = LSLProbability.get_probability(opening_years_of_service)
                closing_probability = LSLProbability.get_probability(closing_years_of_service)
                # New formula: (C/B × closing prob) - (O/B × opening prob) + leave taken
                accrual_amount = (closing_value * closing_probability) - (opening_value * opening_probability) + leave_taken
            else:
                opening_probability = Decimal('1.0')  # Not used for non-LSL
                closing_probability = Decimal('1.0')  # Not used for non-LSL
                accrual_amount = base_accrual

            # Calculate oncosts
            super_amount = accrual_amount * Decimal('0.12')
            prt_amount = accrual_amount * Decimal('0.0495')
            workcover_amount = accrual_amount * Decimal('0.01384')
            total_with_oncosts = accrual_amount + super_amount + prt_amount + workcover_amount

            # Add to row - special handling for LSL with extra columns
            if leave_key == 'lsl':
                row_data.extend([
                    f"{opening_value:.2f}",
                    f"{closing_value:.2f}",
                    f"{leave_taken:.2f}",
                    f"{opening_probability:.4f}",  # Opening probability
                    f"{closing_probability:.4f}",  # Closing probability
                    f"{accrual_amount:.2f}",       # Final accrual with new formula
                    f"{total_with_oncosts:.2f}",
                ])
            else:
                row_data.extend([
                    f"{opening_value:.2f}",
                    f"{closing_value:.2f}",
                    f"{leave_taken:.2f}",
                    f"{accrual_amount:.2f}",
                    f"{total_with_oncosts:.2f}",
                ])

            total_accrual += accrual_amount
            total_with_oncosts_all += total_with_oncosts

        # Add totals
        row_data.extend([
            f"{total_accrual:.2f}",
            f"{total_with_oncosts_all:.2f}"
        ])

        writer.writerow(row_data)

    return response


def download_employee_cost_allocation(request, last_period_id, this_period_id):
    """Download employee cost allocation breakdown showing snapshot allocations or default cost accounts"""
    lp_pay_period = get_object_or_404(PayPeriod, period_id=last_period_id)
    tp_pay_period = get_object_or_404(PayPeriod, period_id=this_period_id)

    # Get uploads from specific periods
    opening_upload = Upload.objects.filter(
        pay_period=lp_pay_period, source_system='Micropay_IQB_Leave', is_active=True
    ).first()
    closing_upload = Upload.objects.filter(
        pay_period=tp_pay_period, source_system='Micropay_IQB_Leave', is_active=True
    ).first()

    if not all([opening_upload, closing_upload]):
        return HttpResponse("Missing required uploads", status=400)

    from django.db.models import Sum

    # All leave type configurations
    leave_configs = {
        'annual': {'name': 'Annual Leave'},
        'lsl': {'name': 'Long Service Leave'},
        'toil': {'name': 'User Defined Leave'},
    }

    # Get ALL unique employee codes from all leave types
    all_employee_codes = set()
    for config in leave_configs.values():
        closing_emp_codes = set(IQBLeaveBalance.objects.filter(
            upload=closing_upload,
            leave_type=config['name']
        ).values_list('employee_code', flat=True).distinct())
        opening_emp_codes = set(IQBLeaveBalance.objects.filter(
            upload=opening_upload,
            leave_type=config['name']
        ).values_list('employee_code', flat=True).distinct())
        all_employee_codes.update(closing_emp_codes | opening_emp_codes)

    all_employee_codes = sorted(all_employee_codes)

    # Get location and department lookups for display names
    location_lookup = {loc.location_id: loc.location_name for loc in SageLocation.objects.all()}
    department_lookup = {dept.department_id: dept.department_name for dept in SageDepartment.objects.all()}

    # Generate CSV
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="employee_cost_allocation_{last_period_id}_to_{this_period_id}.csv"'

    writer = csv.writer(response)

    # Header row
    writer.writerow([
        'Employee Code', 'Employee Name', 'Location ID', 'Location Name',
        'Department ID', 'Department Name', 'Allocation %', 'Source'
    ])

    for emp_code in all_employee_codes:
        # Get employee name (try to find from any leave type)
        emp_name = emp_code
        for config in leave_configs.values():
            emp_record = IQBLeaveBalance.objects.filter(
                upload=closing_upload,
                employee_code=emp_code,
                leave_type=config['name']
            ).first()
            if emp_record:
                emp_name = emp_record.full_name
                break

        # Try to get cost allocation from snapshot first
        cost_allocation = {}
        source = 'Unknown'

        try:
            snapshot = EmployeePayPeriodSnapshot.objects.get(
                pay_period=tp_pay_period,
                employee_code=emp_code
            )
            cost_allocation = snapshot.cost_allocation or {}
            if cost_allocation:
                source = f'Snapshot ({tp_pay_period.period_id})'
        except EmployeePayPeriodSnapshot.DoesNotExist:
            pass

        # If no snapshot allocation, use employee's default cost account
        if not cost_allocation:
            from reconciliation.models import Employee, CostCenterSplit
            try:
                employee = Employee.objects.get(code=emp_code)
                if employee.default_cost_account:
                    source = 'Default Cost Account'

                    # Check if this is a SPL- account
                    if employee.default_cost_account.startswith('SPL-'):
                        # Look up all split targets for this source account
                        splits = CostCenterSplit.objects.filter(
                            source_account=employee.default_cost_account,
                            is_active=True
                        )
                        for split in splits:
                            target_account = split.target_account
                            split_pct = split.percentage
                            # Parse target account (format: location-department)
                            if '-' in target_account:
                                parts = target_account.split('-')
                                if len(parts) >= 2:
                                    location_code = parts[0]
                                    dept_code = parts[1]
                                    if location_code not in cost_allocation:
                                        cost_allocation[location_code] = {}
                                    cost_allocation[location_code][dept_code] = float(split_pct)
                    else:
                        # Parse default_cost_account (format: location-department)
                        if '-' in employee.default_cost_account:
                            parts = employee.default_cost_account.split('-')
                            if len(parts) >= 2:
                                location_code = parts[0]
                                dept_code = parts[1]
                                cost_allocation = {location_code: {dept_code: 100.0}}
            except Employee.DoesNotExist:
                pass

        # Write rows for each allocation
        if cost_allocation:
            for location_id, departments in cost_allocation.items():
                for dept_id, percentage in departments.items():
                    writer.writerow([
                        emp_code,
                        emp_name,
                        location_id,
                        location_lookup.get(location_id, ''),
                        dept_id,
                        department_lookup.get(dept_id, ''),
                        f"{percentage:.2f}",
                        source
                    ])
        else:
            # No allocation found
            writer.writerow([
                emp_code,
                emp_name,
                '',
                '',
                '',
                '',
                '',
                'No Allocation Found'
            ])

    return response
