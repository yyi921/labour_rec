"""
Payroll Tax & Workcover Dashboard Views
Handles PRT/WC calculation dashboards using IQB Details V2 data
"""
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from django.db.models import Sum, Q, F, Value, Case, When, CharField
from decimal import Decimal
import csv

from reconciliation.models import PayPeriod, IQBDetailV2, Employee, PayCompCodeMapping, CostCenterSplit


def prt_wc_dashboard(request, period_id):
    """
    Payroll Tax & Workcover Dashboard

    Shows three cost breakdowns by PRT Category × State:
    1. Non-Apprentice (excluding parental leave)
    2. Apprentice (all costs)
    3. Parental Leave (Non-Apprentice only)

    Validation: Sum of all three = Total Actual Payroll Cost
    """
    pay_period = get_object_or_404(PayPeriod, period_id=period_id)

    # Verify this is a PRT/WC period
    if pay_period.process_type != 'payroll_tax_wc':
        return render(request, 'reconciliation/error.html', {
            'message': 'This dashboard is only for Payroll Tax & Workcover periods.'
        })

    # Get month from period_end
    year = pay_period.period_end.year
    month = pay_period.period_end.month

    # Get all IQB records for this month
    iqb_records = IQBDetailV2.objects.filter(
        period_end_date__year=year,
        period_end_date__month=month,
        include_in_costs=True  # Only include records flagged for cost inclusion
    ).select_related()

    # Create employee lookup (code -> employee object)
    employees = {emp.code: emp for emp in Employee.objects.all()}

    # Create pay comp code mapping lookup (pay_comp_code -> mapping object)
    pay_comp_mappings = {m.pay_comp_code: m for m in PayCompCodeMapping.objects.all()}

    # Track unmapped employees
    unmapped_employees = set()
    unmapped_employee_details = []

    # Helper function to categorize employee
    def is_apprentice(employee_code):
        emp = employees.get(employee_code)
        if not emp:
            unmapped_employees.add(employee_code)
            return False
        return 'apprentice' in (emp.job_classification or '').lower()

    def get_employee_state(employee_code):
        emp = employees.get(employee_code)
        if not emp:
            unmapped_employees.add(employee_code)
            return 'QLD'  # Default to QLD
        return emp.state or 'QLD'

    def is_parental_leave(record):
        """Check if record is parental leave"""
        # Check pay comp description
        if 'parental' in (record.pay_comp_add_ded_desc or '').lower():
            return True
        # Check leave reason
        if record.leave_reason_description == 'MG - Paid Parental Lve':
            return True
        return False

    # Initialize data structures for three tables
    # Structure: {prt_category: {state: amount}}
    non_apprentice_data = {}
    apprentice_data = {}
    parental_leave_data = {}

    # Process each IQB record
    for record in iqb_records:
        # Get PRT category from pay comp code mapping
        mapping = pay_comp_mappings.get(record.pay_comp_add_ded_code)
        if not mapping:
            prt_category = 'Unmapped'
        else:
            prt_category = mapping.prt_category or 'Uncategorized'

        # Get employee details
        emp_code = record.employee_code
        state = get_employee_state(emp_code)
        is_app = is_apprentice(emp_code)
        is_parental = is_parental_leave(record)

        amount = record.amount or Decimal('0')

        # Categorize into the three tables
        if is_app:
            # Table 2: All apprentice costs (including parental)
            if prt_category not in apprentice_data:
                apprentice_data[prt_category] = {'NSW': Decimal('0'), 'QLD': Decimal('0'), 'VIC': Decimal('0')}
            apprentice_data[prt_category][state] += amount
        elif is_parental:
            # Table 3: Parental leave for non-apprentice
            if prt_category not in parental_leave_data:
                parental_leave_data[prt_category] = {'NSW': Decimal('0'), 'QLD': Decimal('0'), 'VIC': Decimal('0')}
            parental_leave_data[prt_category][state] += amount
        else:
            # Table 1: Non-apprentice excluding parental
            if prt_category not in non_apprentice_data:
                non_apprentice_data[prt_category] = {'NSW': Decimal('0'), 'QLD': Decimal('0'), 'VIC': Decimal('0')}
            non_apprentice_data[prt_category][state] += amount

    # Calculate grand totals for each table
    def add_grand_totals(data_dict):
        """Add grand total column to each PRT category row"""
        for category in data_dict:
            data_dict[category]['grand_total'] = (
                data_dict[category]['NSW'] +
                data_dict[category]['QLD'] +
                data_dict[category]['VIC']
            )
        return data_dict

    non_apprentice_data = add_grand_totals(non_apprentice_data)
    apprentice_data = add_grand_totals(apprentice_data)
    parental_leave_data = add_grand_totals(parental_leave_data)

    # Calculate totals for validation
    def calculate_table_total(data_dict):
        """Calculate total of all amounts in table"""
        total = Decimal('0')
        for category in data_dict:
            total += data_dict[category]['grand_total']
        return total

    non_apprentice_total = calculate_table_total(non_apprentice_data)
    apprentice_total = calculate_table_total(apprentice_data)
    parental_leave_total = calculate_table_total(parental_leave_data)

    calculated_total = non_apprentice_total + apprentice_total + parental_leave_total
    expected_total = pay_period.total_payroll_cost or Decimal('0')

    # Check if totals match (within 0.01 tolerance for rounding)
    variance = abs(calculated_total - expected_total)
    totals_match = variance < Decimal('0.01')

    # Collect details for unmapped employees
    if unmapped_employees:
        # Get unique employee records and their total amounts
        employee_amounts = {}
        for record in iqb_records:
            if record.employee_code in unmapped_employees:
                if record.employee_code not in employee_amounts:
                    employee_amounts[record.employee_code] = {
                        'code': record.employee_code,
                        'name': record.full_name or 'Unknown',
                        'total_amount': Decimal('0')
                    }
                employee_amounts[record.employee_code]['total_amount'] += (record.amount or Decimal('0'))

        unmapped_employee_details = sorted(employee_amounts.values(), key=lambda x: x['code'])

    context = {
        'pay_period': pay_period,
        'month_name': pay_period.period_end.strftime('%B %Y'),

        # Table 1: Non-Apprentice (excluding parental)
        'non_apprentice_data': dict(sorted(non_apprentice_data.items())),
        'non_apprentice_total': non_apprentice_total,

        # Table 2: Apprentice (all)
        'apprentice_data': dict(sorted(apprentice_data.items())),
        'apprentice_total': apprentice_total,

        # Table 3: Parental Leave (Non-Apprentice)
        'parental_leave_data': dict(sorted(parental_leave_data.items())),
        'parental_leave_total': parental_leave_total,

        # Validation
        'calculated_total': calculated_total,
        'expected_total': expected_total,
        'variance': variance,
        'totals_match': totals_match,

        # Workcover info
        'workcover_percentage': pay_period.workcover_percentage,

        # Unmapped employees
        'unmapped_employees': unmapped_employee_details,
        'unmapped_count': len(unmapped_employee_details),
    }

    return render(request, 'reconciliation/prt_wc_dashboard.html', context)


def download_prt_wc_employee_breakdown(request, period_id):
    """
    Download employee-level breakdown for PRT/WC period
    Shows all relevant fields with total amounts per employee
    """
    pay_period = get_object_or_404(PayPeriod, period_id=period_id)

    # Get month from period_end
    year = pay_period.period_end.year
    month = pay_period.period_end.month

    # Get all IQB records for this month
    iqb_records = IQBDetailV2.objects.filter(
        period_end_date__year=year,
        period_end_date__month=month,
        include_in_costs=True
    ).order_by('employee_code', 'pay_comp_add_ded_code')

    # Create employee lookup
    employees = {emp.code: emp for emp in Employee.objects.all()}
    pay_comp_mappings = {m.pay_comp_code: m for m in PayCompCodeMapping.objects.all()}

    # Prepare CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="PRT_WC_Employee_Breakdown_{period_id}.csv"'

    writer = csv.writer(response)

    # Write header
    writer.writerow([
        'Employee Code',
        'Employee Name',
        'State',
        'Job Classification',
        'Is Apprentice',
        'Location ID',
        'Department Code',
        'Pay Comp Code',
        'Pay Comp Desc',
        'Transaction Type',
        'PRT Category',
        'Is Parental Leave',
        'Leave Reason',
        'Amount',
        'GL Account',
        'GL Name'
    ])

    # Write data rows
    total_amount = Decimal('0')
    for record in iqb_records:
        emp = employees.get(record.employee_code)
        mapping = pay_comp_mappings.get(record.pay_comp_add_ded_code)

        is_apprentice_flag = False
        job_classification = ''
        state = 'QLD'

        if emp:
            job_classification = emp.job_classification or ''
            is_apprentice_flag = 'apprentice' in job_classification.lower()
            state = emp.state or 'QLD'

        # Check if parental leave
        is_parental = (
            'parental' in (record.pay_comp_add_ded_desc or '').lower() or
            record.leave_reason_description == 'MG - Paid Parental Lve'
        )

        prt_category = mapping.prt_category if mapping else 'Unmapped'
        gl_account = mapping.gl_account if mapping else ''
        gl_name = mapping.gl_name if mapping else ''

        amount = record.amount or Decimal('0')
        total_amount += amount

        writer.writerow([
            record.employee_code,
            record.full_name or '',
            state,
            job_classification,
            'Yes' if is_apprentice_flag else 'No',
            record.location_id or '',
            record.department_code or '',
            record.pay_comp_add_ded_code or '',
            record.pay_comp_add_ded_desc or '',
            mapping.transaction_type if mapping else '',
            prt_category,
            'Yes' if is_parental else 'No',
            record.leave_reason_description or '',
            f'{amount:.2f}',
            gl_account,
            gl_name
        ])

    # Write total row
    writer.writerow([])
    writer.writerow(['', '', '', '', '', '', '', '', '', '', '', 'TOTAL:', f'{total_amount:.2f}', '', ''])
    writer.writerow([])
    writer.writerow(['Expected Total (from input):', '', '', '', '', '', '', '', '', '', '', '', f'{pay_period.total_payroll_cost:.2f}', '', ''])
    writer.writerow(['Variance:', '', '', '', '', '', '', '', '', '', '', '', f'{abs(total_amount - (pay_period.total_payroll_cost or Decimal(0))):.2f}', '', ''])

    return response


def download_prt_wc_sage_journal(request, period_id):
    """
    Generate and download Sage journal for PRT/WC period

    Pro-rata allocation logic:
    - PRT allocation = Final_PRT × (Location_Dept_Amount / Total_Payroll_Cost)
    - Workcover allocation = (Workcover% × Total_Payroll_Cost) × (Location_Dept_Amount / Total_Payroll_Cost)

    Journal entries:
    - PRT: Debit 6335 (by location/dept), Credit 2370
    - Workcover: Debit 6380 (by location/dept), Credit 1147
    """
    pay_period = get_object_or_404(PayPeriod, period_id=period_id)

    # Get final PRT amount from query parameter
    try:
        final_prt_amount = Decimal(request.GET.get('final_prt_amount', '0'))
    except:
        return HttpResponse("Invalid final PRT amount", status=400)

    if final_prt_amount <= 0:
        return HttpResponse("Final PRT amount must be greater than 0", status=400)

    # Get month from period_end
    year = pay_period.period_end.year
    month = pay_period.period_end.month

    # Get all IQB records for this month
    iqb_records = IQBDetailV2.objects.filter(
        period_end_date__year=year,
        period_end_date__month=month,
        include_in_costs=True
    ).select_related()

    # Calculate total payroll cost
    total_payroll_cost = sum(record.amount or Decimal('0') for record in iqb_records)

    if total_payroll_cost == 0:
        return HttpResponse("Total payroll cost is 0, cannot allocate", status=400)

    # Calculate workcover total
    workcover_percentage = pay_period.workcover_percentage or Decimal('1.384')
    workcover_total = total_payroll_cost * (workcover_percentage / Decimal('100'))

    # Load all SPL split rules upfront
    split_rules = {}
    for split in CostCenterSplit.objects.filter(is_active=True):
        if split.source_account not in split_rules:
            split_rules[split.source_account] = []
        split_rules[split.source_account].append({
            'target': split.target_account,
            'percentage': split.percentage
        })

    # Group by location and department, expanding SPL- codes
    # Structure: {(location_id, dept_id): total_amount}
    location_dept_totals = {}

    for record in iqb_records:
        location_id = record.location_id or ''
        dept_id = record.department_code or ''
        amount = record.amount or Decimal('0')

        # Determine the cost account identifier
        # SPL codes can appear as: location alone, dept alone, or "location-dept" combination
        is_spl = False
        cost_account = ''

        # Check if location_id itself is an SPL code
        if location_id.startswith('SPL-'):
            is_spl = True
            cost_account = location_id
        # Check if department_code itself is an SPL code
        elif dept_id.startswith('SPL-'):
            is_spl = True
            cost_account = dept_id
        # Check if the combination is an SPL code
        elif location_id and dept_id:
            combined = f"{location_id}-{dept_id}"
            if combined.startswith('SPL-'):
                is_spl = True
                cost_account = combined

        if is_spl:
            # This is a split account - expand it using split rules
            if cost_account in split_rules:
                for split in split_rules[cost_account]:
                    target_account = split['target']
                    split_percentage = split['percentage']

                    # Parse target account (format: "location-dept")
                    if '-' in target_account:
                        parts = target_account.split('-')
                        target_loc = parts[0]
                        target_dept = parts[1][:2] if len(parts[1]) >= 2 else parts[1]
                    else:
                        # If no dash, treat entire string as location
                        target_loc = target_account
                        target_dept = ''

                    key = (target_loc, target_dept)
                    if key not in location_dept_totals:
                        location_dept_totals[key] = Decimal('0')

                    # Allocate amount based on split percentage
                    location_dept_totals[key] += amount * split_percentage
            else:
                # SPL code but no mapping found - use original location/dept
                # This handles unmapped SPL codes gracefully
                key = (location_id, dept_id)
                if key not in location_dept_totals:
                    location_dept_totals[key] = Decimal('0')
                location_dept_totals[key] += amount
        else:
            # Regular location/department - use as is
            key = (location_id, dept_id)
            if key not in location_dept_totals:
                location_dept_totals[key] = Decimal('0')
            location_dept_totals[key] += amount

    # Calculate pro-rata allocations for each location/department
    prt_allocations = {}  # {(location, dept): amount}
    wc_allocations = {}   # {(location, dept): amount}

    for (location_id, dept_id), location_dept_amount in location_dept_totals.items():
        # Pro-rata allocation based on location/dept amount as percentage of total
        allocation_ratio = location_dept_amount / total_payroll_cost

        prt_allocations[(location_id, dept_id)] = final_prt_amount * allocation_ratio
        wc_allocations[(location_id, dept_id)] = workcover_total * allocation_ratio

    # Generate journal lines
    journal_lines = []

    # Common values
    journal_id = f"PRT-WC-{period_id}"
    date = pay_period.period_end.strftime('%m/%d/%Y')
    description = f"Payroll Tax & Workcover {pay_period.period_end.strftime('%B %Y')}"

    # PRT entries
    prt_total = Decimal('0')
    for (location_id, dept_id), amount in prt_allocations.items():
        if amount != 0:
            journal_lines.append({
                'acct_no': '6335',
                'location_id': location_id,
                'dept_id': dept_id,
                'document': 'GL-Batch',
                'memo': f"{description} - Payroll Tax",
                'debit': amount,
                'billable': '',
                'item_id': '',
                'project_id': '',
                'customer_id': ''
            })
            prt_total += amount

    # PRT credit entry (2370)
    if prt_total != 0:
        journal_lines.append({
            'acct_no': '2370',
            'location_id': '',
            'dept_id': '',
            'document': 'GL-Batch',
            'memo': f"{description} - Payroll Tax Liability",
            'debit': -prt_total,  # Credit is negative debit
            'billable': '',
            'item_id': '',
            'project_id': '',
            'customer_id': ''
        })

    # Workcover entries
    wc_total = Decimal('0')
    for (location_id, dept_id), amount in wc_allocations.items():
        if amount != 0:
            journal_lines.append({
                'acct_no': '6380',
                'location_id': location_id,
                'dept_id': dept_id,
                'document': 'GL-Batch',
                'memo': f"{description} - Workcover @ {workcover_percentage}%",
                'debit': amount,
                'billable': '',
                'item_id': '',
                'project_id': '',
                'customer_id': ''
            })
            wc_total += amount

    # Workcover credit entry (1147)
    if wc_total != 0:
        journal_lines.append({
            'acct_no': '1147',
            'location_id': '',
            'dept_id': '',
            'document': 'GL-Batch',
            'memo': f"{description} - Workcover Liability",
            'debit': -wc_total,  # Credit is negative debit
            'billable': '',
            'item_id': '',
            'project_id': '',
            'customer_id': ''
        })

    # Create CSV response in Sage Intacct format
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="PRT_WC_Sage_Journal_{period_id}.csv"'

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
