"""
Reconciliation Dashboard Views
"""
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Sum, Count, Avg, Q
from decimal import Decimal
import json

from reconciliation.models import (
    PayPeriod, ReconciliationRun, EmployeeReconciliation,
    JournalReconciliation, EmployeePayPeriodSnapshot, CostCenterSplit
)
from django.http import HttpResponse
import csv
from collections import defaultdict
from datetime import timedelta


def reconciliation_dashboard(request, pay_period_id):
    """
    Main reconciliation dashboard showing all summary tables
    Auto-triggers reconciliation if not already run

    Routes to accrual dashboard if this is an accrual period
    """
    pay_period = get_object_or_404(PayPeriod, period_id=pay_period_id)

    # Check if this is an accrual period
    if pay_period.period_type == 'accrual' or pay_period.status == 'accrual_processed':
        return accrual_dashboard(request, pay_period)

    # Get the latest reconciliation run for this pay period
    recon_run = ReconciliationRun.objects.filter(
        pay_period=pay_period
    ).order_by('-started_at').first()

    # Auto-trigger reconciliation if not found
    if not recon_run:
        from reconciliation.engine import trigger_reconciliation
        try:
            recon_run = trigger_reconciliation(pay_period)
        except Exception as e:
            return render(request, 'reconciliation/dashboard.html', {
                'pay_period': pay_period,
                'error': f'Failed to run reconciliation: {str(e)}'
            })

    # Table 1: Overall Summary
    overall_summary = _get_overall_summary(pay_period)

    # Table 2: Summary by Employment Type
    employment_type_summary = _get_employment_type_summary(pay_period)
    employment_type_totals = _calculate_employment_type_totals(employment_type_summary)

    # Table 3: Journal vs IQB Comparison
    journal_comparison = _get_journal_comparison(recon_run, pay_period)

    context = {
        'pay_period': pay_period,
        'recon_run': recon_run,
        'overall_summary': overall_summary,
        'employment_type_summary': employment_type_summary,
        'employment_type_totals': employment_type_totals,
        'journal_comparison': journal_comparison,
    }

    return render(request, 'reconciliation/dashboard.html', context)


def _get_overall_summary(pay_period):
    """
    Get overall reconciliation summary totals
    """
    totals = EmployeeReconciliation.objects.filter(
        pay_period=pay_period
    ).aggregate(
        total_employees=Count('employee_id'),
        tanda_total_cost=Sum('tanda_total_cost'),
        tanda_total_hours=Sum('tanda_total_hours'),
        iqb_total_cost=Sum('iqb_total_cost'),
        iqb_total_hours=Sum('iqb_total_hours'),
        iqb_superannuation=Sum('iqb_superannuation'),
        auto_pay_total=Sum('auto_pay_amount'),
        hours_match_count=Count('employee_id', filter=Q(hours_match=True)),
        cost_match_count=Count('employee_id', filter=Q(cost_match=True)),
    )

    # Calculate variances
    tanda_total = totals['tanda_total_cost'] or Decimal('0')
    iqb_total = totals['iqb_total_cost'] or Decimal('0')
    auto_pay_total = totals['auto_pay_total'] or Decimal('0')

    # For cost variance, we need to check which employees are salaried
    salaried_auto_pay = EmployeeReconciliation.objects.filter(
        pay_period=pay_period,
        is_salaried=True
    ).aggregate(total=Sum('auto_pay_amount'))['total'] or Decimal('0')

    hourly_tanda = EmployeeReconciliation.objects.filter(
        pay_period=pay_period,
        is_salaried=False
    ).aggregate(total=Sum('tanda_total_cost'))['total'] or Decimal('0')

    expected_cost = salaried_auto_pay + hourly_tanda
    cost_variance = abs(expected_cost - iqb_total)

    hours_variance = abs((totals['tanda_total_hours'] or Decimal('0')) - (totals['iqb_total_hours'] or Decimal('0')))

    return {
        'total_employees': totals['total_employees'],
        'tanda_total_cost': tanda_total,
        'tanda_total_hours': totals['tanda_total_hours'] or Decimal('0'),
        'iqb_total_cost': iqb_total,
        'iqb_total_hours': totals['iqb_total_hours'] or Decimal('0'),
        'iqb_superannuation': totals['iqb_superannuation'] or Decimal('0'),
        'iqb_grand_total': iqb_total + (totals['iqb_superannuation'] or Decimal('0')),
        'expected_cost': expected_cost,
        'cost_variance': cost_variance,
        'hours_variance': hours_variance,
        'hours_match_count': totals['hours_match_count'],
        'cost_match_count': totals['cost_match_count'],
        'hours_match_pct': (totals['hours_match_count'] / totals['total_employees'] * 100) if totals['total_employees'] > 0 else 0,
        'cost_match_pct': (totals['cost_match_count'] / totals['total_employees'] * 100) if totals['total_employees'] > 0 else 0,
    }


def _get_employment_type_summary(pay_period):
    """
    Get summary by employment type
    """
    summary = EmployeeReconciliation.objects.filter(
        pay_period=pay_period
    ).values('employment_type').annotate(
        employee_count=Count('employee_id'),
        tanda_total_cost=Sum('tanda_total_cost'),
        tanda_total_hours=Sum('tanda_total_hours'),
        iqb_total_cost=Sum('iqb_total_cost'),
        iqb_total_hours=Sum('iqb_total_hours'),
        iqb_superannuation=Sum('iqb_superannuation'),
        auto_pay_total=Sum('auto_pay_amount'),
        salaried_count=Count('employee_id', filter=Q(is_salaried=True)),
    ).order_by('-employee_count')

    # Calculate variances for each employment type
    for item in summary:
        # For each employment type, expected cost is:
        # - Auto pay for salaried employees
        # - Tanda cost for hourly employees
        salaried_auto_pay = EmployeeReconciliation.objects.filter(
            pay_period=pay_period,
            employment_type=item['employment_type'],
            is_salaried=True
        ).aggregate(total=Sum('auto_pay_amount'))['total'] or Decimal('0')

        hourly_tanda = EmployeeReconciliation.objects.filter(
            pay_period=pay_period,
            employment_type=item['employment_type'],
            is_salaried=False
        ).aggregate(total=Sum('tanda_total_cost'))['total'] or Decimal('0')

        expected_cost = salaried_auto_pay + hourly_tanda

        item['expected_cost'] = expected_cost
        item['cost_variance'] = abs(expected_cost - (item['iqb_total_cost'] or Decimal('0')))
        item['hours_variance'] = abs((item['tanda_total_hours'] or Decimal('0')) - (item['iqb_total_hours'] or Decimal('0')))
        item['iqb_grand_total'] = (item['iqb_total_cost'] or Decimal('0')) + (item['iqb_superannuation'] or Decimal('0'))

    return summary


def _calculate_employment_type_totals(employment_type_summary):
    """
    Calculate totals row for employment type summary
    """
    totals = {
        'total_employees': 0,
        'total_expected_cost': Decimal('0'),
        'total_iqb_cost': Decimal('0'),
        'total_iqb_super': Decimal('0'),
        'total_cost_variance': Decimal('0'),
        'total_tanda_hours': Decimal('0'),
        'total_iqb_hours': Decimal('0'),
        'total_hours_variance': Decimal('0'),
    }

    for item in employment_type_summary:
        totals['total_employees'] += item['employee_count']
        totals['total_expected_cost'] += item['expected_cost']
        totals['total_iqb_cost'] += item['iqb_total_cost'] or Decimal('0')
        totals['total_iqb_super'] += item['iqb_superannuation'] or Decimal('0')
        totals['total_cost_variance'] += item['cost_variance']
        totals['total_tanda_hours'] += item['tanda_total_hours'] or Decimal('0')
        totals['total_iqb_hours'] += item['iqb_total_hours'] or Decimal('0')
        totals['total_hours_variance'] += item['hours_variance']

    return totals


def _get_journal_comparison(recon_run, pay_period):
    """
    Get IQB vs Journal comparison
    """
    # Get IQB grand total from employee reconciliation
    iqb_totals = EmployeeReconciliation.objects.filter(
        pay_period=pay_period
    ).aggregate(
        iqb_total_cost=Sum('iqb_total_cost'),
        iqb_superannuation=Sum('iqb_superannuation')
    )

    iqb_total = (iqb_totals['iqb_total_cost'] or Decimal('0'))
    iqb_super = (iqb_totals['iqb_superannuation'] or Decimal('0'))
    iqb_grand_total = iqb_total + iqb_super

    # Get Journal total (only descriptions marked as "Y" for Total Cost)
    journal_total_cost = JournalReconciliation.objects.filter(
        recon_run=recon_run,
        include_in_total_cost=True
    ).aggregate(total=Sum('journal_net'))['total'] or Decimal('0')

    # Get all journal reconciliations for details
    journal_items = JournalReconciliation.objects.filter(
        recon_run=recon_run
    ).order_by('-journal_net')

    # Get unmapped descriptions
    unmapped_items = JournalReconciliation.objects.filter(
        recon_run=recon_run,
        is_mapped=False
    ).order_by('-journal_net')

    variance = abs(iqb_grand_total - journal_total_cost)

    # Calculate totals for journal items breakdown
    journal_totals = journal_items.aggregate(
        total_debit=Sum('journal_debit'),
        total_credit=Sum('journal_credit'),
        total_net=Sum('journal_net')
    )

    return {
        'iqb_total_cost': iqb_total,
        'iqb_superannuation': iqb_super,
        'iqb_grand_total': iqb_grand_total,
        'journal_total_cost': journal_total_cost,
        'variance': variance,
        'variance_pct': (variance / journal_total_cost * 100) if journal_total_cost > 0 else 0,
        'journal_items': journal_items,
        'journal_totals': journal_totals,
        'unmapped_items': unmapped_items,
        'unmapped_count': unmapped_items.count(),
    }


def pay_period_list(request):
    """
    List all pay periods with reconciliation status
    """
    pay_periods = PayPeriod.objects.all().order_by('-period_end')

    # Annotate with reconciliation run info
    for pp in pay_periods:
        pp.latest_recon = ReconciliationRun.objects.filter(
            pay_period=pp
        ).order_by('-started_at').first()

    return render(request, 'reconciliation/pay_period_list.html', {
        'pay_periods': pay_periods
    })


@require_http_methods(["POST"])
def delete_pay_periods(request):
    """
    Delete selected pay periods and all associated data
    """
    try:
        data = json.loads(request.body)
        period_ids = data.get('period_ids', [])

        if not period_ids:
            return JsonResponse({
                'success': False,
                'error': 'No pay periods specified'
            }, status=400)

        # Delete pay periods (cascading deletes will handle related data)
        deleted_count = 0
        for period_id in period_ids:
            try:
                pay_period = PayPeriod.objects.get(period_id=period_id)
                pay_period.delete()
                deleted_count += 1
            except PayPeriod.DoesNotExist:
                continue

        return JsonResponse({
            'success': True,
            'deleted_count': deleted_count,
            'message': f'Successfully deleted {deleted_count} pay period(s)'
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


def accrual_dashboard(request, pay_period):
    """
    Accrual dashboard showing employee breakdown with GL costs
    """
    # Get all employee snapshots for this accrual period
    snapshots = EmployeePayPeriodSnapshot.objects.filter(
        pay_period=pay_period
    ).order_by('employee_code')

    # Calculate summary totals
    summary = {
        'total_employees': snapshots.count(),
        'total_base_wages': Decimal('0'),
        'total_superannuation': Decimal('0'),
        'total_annual_leave': Decimal('0'),
        'total_payroll_tax': Decimal('0'),
        'total_workcover': Decimal('0'),
        'total_accrued': Decimal('0'),
    }

    # Build employee data with location/department info
    employee_data = []
    for snapshot in snapshots:
        # Extract location and department from cost_allocation
        location = 'N/A'
        department = 'N/A'
        if snapshot.cost_allocation:
            # Get first location and department
            for loc_code, depts in snapshot.cost_allocation.items():
                location = loc_code
                for dept_code in depts.keys():
                    department = dept_code
                    break
                break

        employee_data.append({
            'employee_code': snapshot.employee_code,
            'employee_name': snapshot.employee_name,
            'employee_type': snapshot.accrual_employee_type or snapshot.employment_status,
            'location': location,
            'department': department,
            'gl_6345_salaries': snapshot.gl_6345_salaries,
            'gl_6300_annual_leave': snapshot.gl_6300,
            'gl_6370_superannuation': snapshot.gl_6370_superannuation,
            'gl_6380_workcover': snapshot.gl_6380,
            'gl_6335_payroll_tax': snapshot.gl_6335,
            'total': snapshot.accrual_total,
            'source': snapshot.accrual_source,
        })

        # Update summary totals
        summary['total_base_wages'] += snapshot.gl_6345_salaries
        summary['total_superannuation'] += snapshot.gl_6370_superannuation
        summary['total_annual_leave'] += snapshot.gl_6300
        summary['total_payroll_tax'] += snapshot.gl_6335
        summary['total_workcover'] += snapshot.gl_6380
        summary['total_accrued'] += snapshot.accrual_total

    context = {
        'pay_period': pay_period,
        'summary': summary,
        'employee_data': employee_data,
        'is_accrual': True,
    }

    return render(request, 'reconciliation/accrual_dashboard.html', context)


def download_employee_accrual_breakdown(request, pay_period_id):
    """
    Download Employee Accrual Breakdown as CSV
    """
    pay_period = get_object_or_404(PayPeriod, period_id=pay_period_id)

    # Get all employee snapshots
    snapshots = EmployeePayPeriodSnapshot.objects.filter(
        pay_period=pay_period
    ).order_by('employee_code')

    # Prepare CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="Employee_Accrual_Breakdown_{pay_period_id}.csv"'

    writer = csv.writer(response)

    # Write header
    writer.writerow([
        'Employee Code', 'Employee Name', 'Employee Type', 'Department', 'Location',
        '6345 Salaries', '6300 Annual Leave', '6370 Superannuation',
        '6380 WorkCover', '6335 Payroll Tax', 'Total', 'Source'
    ])

    # Track totals
    total_6345 = Decimal('0')
    total_6300 = Decimal('0')
    total_6370 = Decimal('0')
    total_6380 = Decimal('0')
    total_6335 = Decimal('0')
    total_accrued = Decimal('0')

    # Write employee rows
    for snapshot in snapshots:
        # Extract location and department from cost_allocation
        location = 'N/A'
        department = 'N/A'
        if snapshot.cost_allocation:
            for loc_code, depts in snapshot.cost_allocation.items():
                location = loc_code
                for dept_code in depts.keys():
                    department = dept_code
                    break
                break

        # Determine source label
        if snapshot.accrual_source == 'tanda_auto_pay':
            source = 'Auto Pay'
        elif snapshot.accrual_source == 'tanda_shift_cost':
            source = 'Tanda'
        else:
            source = 'Default'

        writer.writerow([
            snapshot.employee_code,
            snapshot.employee_name,
            snapshot.accrual_employee_type or snapshot.employment_status,
            department,
            location,
            float(snapshot.gl_6345_salaries),
            float(snapshot.gl_6300),
            float(snapshot.gl_6370_superannuation),
            float(snapshot.gl_6380),
            float(snapshot.gl_6335),
            float(snapshot.accrual_total),
            source
        ])

        # Accumulate totals
        total_6345 += snapshot.gl_6345_salaries
        total_6300 += snapshot.gl_6300
        total_6370 += snapshot.gl_6370_superannuation
        total_6380 += snapshot.gl_6380
        total_6335 += snapshot.gl_6335
        total_accrued += snapshot.accrual_total

    # Write totals row
    writer.writerow([
        'TOTAL', '', '', '', '',
        float(total_6345),
        float(total_6300),
        float(total_6370),
        float(total_6380),
        float(total_6335),
        float(total_accrued),
        ''
    ])

    return response


def download_accrual_sage_journal(request, pay_period_id):
    """
    Download Sage Intacct format journal for accrual wages
    """
    pay_period = get_object_or_404(PayPeriod, period_id=pay_period_id)

    # Get all employee snapshots
    snapshots = EmployeePayPeriodSnapshot.objects.filter(
        pay_period=pay_period
    ).order_by('employee_code')

    # Prepare CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="Accrual_Journal_{pay_period_id}.csv"'

    writer = csv.writer(response)

    # Write header (matching Sage template with Reversed column)
    writer.writerow([
        'DONOTIMPORT', 'JOURNAL', 'DATE', 'Reversed', 'DESCRIPTION', 'REFERENCE_NO', 'LINE_NO',
        'ACCT_NO', 'LOCATION_ID', 'DEPT_ID', 'DOCUMENT', 'MEMO',
        'DEBIT', 'BILLABLE', 'GLENTRY_ITEMID', 'GLENTRY_PROJECTID', 'GLENTRY_CUSTOMERID'
    ])

    # Calculate dates
    from datetime import datetime
    journal_date_obj = datetime.strptime(pay_period_id, '%Y-%m-%d').date()
    reversed_date_obj = journal_date_obj + timedelta(days=1)
    journal_date = journal_date_obj.strftime('%d/%m/%Y')
    reversed_date = reversed_date_obj.strftime('%d/%m/%Y')

    # Group by location-department for consolidated entries
    # Need to handle SPL- accounts
    location_dept_totals = defaultdict(lambda: {
        'gl_6345': Decimal('0'),
        'gl_6300': Decimal('0'),
        'gl_6370': Decimal('0'),
        'gl_6335': Decimal('0'),
        'gl_6380': Decimal('0'),
    })

    for snapshot in snapshots:
        # Get location-department combinations
        if snapshot.cost_allocation:
            for location, depts in snapshot.cost_allocation.items():
                for dept, percentage in depts.items():
                    # Check if this is a SPL- account
                    cost_account = f"{location}-{dept}"

                    if cost_account.startswith('SPL-'):
                        # Look up all split targets for this source account
                        splits = CostCenterSplit.objects.filter(
                            source_account=cost_account,
                            is_active=True
                        )

                        for split in splits:
                            target_account = split.target_account
                            split_pct = split.percentage * 100  # Convert to percentage

                            # Parse target account
                            if '-' in target_account:
                                parts = target_account.split('-')
                                target_loc = parts[0]
                                target_dept = parts[1][:2] if len(parts[1]) >= 2 else parts[1]

                                key = (target_loc, target_dept)

                                # Combined percentage: allocation % * split %
                                combined_pct = Decimal(str(percentage)) / 100 * Decimal(str(split_pct)) / 100

                                location_dept_totals[key]['gl_6345'] += snapshot.gl_6345_salaries * combined_pct
                                location_dept_totals[key]['gl_6300'] += snapshot.gl_6300 * combined_pct
                                location_dept_totals[key]['gl_6370'] += snapshot.gl_6370_superannuation * combined_pct
                                location_dept_totals[key]['gl_6335'] += snapshot.gl_6335 * combined_pct
                                location_dept_totals[key]['gl_6380'] += snapshot.gl_6380 * combined_pct
                    else:
                        # Regular account
                        key = (location, dept)

                        # Allocate amounts based on percentage
                        pct = Decimal(str(percentage)) / 100
                        location_dept_totals[key]['gl_6345'] += snapshot.gl_6345_salaries * pct
                        location_dept_totals[key]['gl_6300'] += snapshot.gl_6300 * pct
                        location_dept_totals[key]['gl_6370'] += snapshot.gl_6370_superannuation * pct
                        location_dept_totals[key]['gl_6335'] += snapshot.gl_6335 * pct
                        location_dept_totals[key]['gl_6380'] += snapshot.gl_6380 * pct

    # Write journal entries
    line_no = 1
    journal_id = f"ACCRUAL-{pay_period_id}"
    description = f"Wage Accrual {pay_period_id}"

    # Track total debits to ensure balance
    total_debit = Decimal('0')

    # Debit entries for each location-department
    for (location, dept), totals in sorted(location_dept_totals.items()):
        # Determine if billable (only for location 700)
        billable = 'T' if location == '700' else ''

        # GL 6345 - Salaries
        if totals['gl_6345'] > 0:
            amount = totals['gl_6345'].quantize(Decimal('0.01'))
            total_debit += amount
            writer.writerow([
                '', journal_id, journal_date, reversed_date, description, '', line_no,
                '6345', location, dept, 'Accrual', f"Salaries - {location}-{dept}",
                float(amount), billable, '', '', ''
            ])
            line_no += 1

        # GL 6300 - Annual Leave
        if totals['gl_6300'] > 0:
            amount = totals['gl_6300'].quantize(Decimal('0.01'))
            total_debit += amount
            writer.writerow([
                '', journal_id, journal_date, reversed_date, description, '', line_no,
                '6300', location, dept, 'Accrual', f"Annual Leave - {location}-{dept}",
                float(amount), billable, '', '', ''
            ])
            line_no += 1

        # GL 6370 - Superannuation
        if totals['gl_6370'] > 0:
            amount = totals['gl_6370'].quantize(Decimal('0.01'))
            total_debit += amount
            writer.writerow([
                '', journal_id, journal_date, reversed_date, description, '', line_no,
                '6370', location, dept, 'Accrual', f"Superannuation - {location}-{dept}",
                float(amount), billable, '', '', ''
            ])
            line_no += 1

        # GL 6335 - Payroll Tax
        if totals['gl_6335'] > 0:
            amount = totals['gl_6335'].quantize(Decimal('0.01'))
            total_debit += amount
            writer.writerow([
                '', journal_id, journal_date, reversed_date, description, '', line_no,
                '6335', location, dept, 'Accrual', f"Payroll Tax - {location}-{dept}",
                float(amount), billable, '', '', ''  # billable for location 700
            ])
            line_no += 1

        # GL 6380 - Workcover
        if totals['gl_6380'] > 0:
            amount = totals['gl_6380'].quantize(Decimal('0.01'))
            total_debit += amount
            writer.writerow([
                '', journal_id, journal_date, reversed_date, description, '', line_no,
                '6380', location, dept, 'Accrual', f"Workcover - {location}-{dept}",
                float(amount), billable, '', '', ''  # billable for location 700
            ])
            line_no += 1

    # Credit entry - GL 2055 (Accrued Expenses)
    # Use exact negative of total debits to ensure balance
    credit_amount = -total_debit
    writer.writerow([
        '', journal_id, journal_date, reversed_date, description, '', line_no,
        '2055', '460', '20', 'Accrual', f"Accrued Employment Expenses",
        float(credit_amount), '', '', '', ''
    ])

    return response


def monthly_dashboard(request):
    """
    Monthly Dashboard with three sections:
    1. Top: Single month filter with transaction type breakdown
    2. Middle: Range A vs Range B comparison with employee details
    3. Bottom: Bridge/waterfall chart showing movement from Range A to Range B
    """
    from reconciliation.models import IQBDetailV2, SageLocation, SageDepartment
    from datetime import datetime
    from django.db.models import Sum, Count, Q, F
    from collections import defaultdict

    # Get filter parameters
    selected_month = request.GET.get('month')
    range_a_months = request.GET.getlist('range_a_months[]')
    range_b_months = request.GET.getlist('range_b_months[]')
    selected_department = request.GET.get('department')
    selected_location = request.GET.get('location')

    # Generate month options (July 2022 to June 2030)
    month_options = []
    start_year = 2022
    end_year = 2030
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            if year == 2022 and month < 7:  # Start from July 2022
                continue
            if year == 2030 and month > 6:  # End at June 2030
                break
            date = datetime(year, month, 1)
            month_options.append({
                'value': date.strftime('%Y-%m'),
                'label': date.strftime('%B %Y')
            })

    # Get all available locations and departments for filters
    locations = SageLocation.objects.all().order_by('location_name')
    departments = SageDepartment.objects.all().order_by('department_name')

    context = {
        'month_options': month_options,
        'locations': locations,
        'departments': departments,
        'selected_month': selected_month,
        'range_a_months': range_a_months,
        'range_b_months': range_b_months,
        'selected_department': selected_department,
        'selected_location': selected_location,
    }

    # SECTION 1: Single Month Breakdown
    if selected_month:
        year, month = map(int, selected_month.split('-'))

        # Filter records for selected month
        month_records = IQBDetailV2.objects.filter(
            period_end_date__year=year,
            period_end_date__month=month,
            include_in_costs=True
        )

        # Total costs
        total_costs = month_records.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')

        # Breakdown by transaction type
        transaction_breakdown = month_records.values('transaction_type').annotate(
            total_amount=Sum('amount'),
            record_count=Count('id')
        ).order_by('-total_amount')

        context['section1'] = {
            'total_costs': total_costs,
            'transaction_breakdown': transaction_breakdown,
            'selected_month_label': datetime(year, month, 1).strftime('%B %Y')
        }

    # SECTION 2: Range A vs Range B Comparison
    if range_a_months and range_b_months:
        # Build filters
        range_a_filter = Q()
        for month_str in range_a_months:
            year, month = map(int, month_str.split('-'))
            range_a_filter |= Q(period_end_date__year=year, period_end_date__month=month)

        range_b_filter = Q()
        for month_str in range_b_months:
            year, month = map(int, month_str.split('-'))
            range_b_filter |= Q(period_end_date__year=year, period_end_date__month=month)

        # Additional filters
        extra_filters = Q(include_in_costs=True)
        if selected_department:
            extra_filters &= Q(department_code=selected_department)
        if selected_location:
            extra_filters &= Q(location_id=selected_location)

        # Get Range A data
        range_a_data = IQBDetailV2.objects.filter(
            range_a_filter & extra_filters
        ).values('employee_code', 'full_name').annotate(
            total_cost=Sum('amount')
        ).order_by('employee_code')

        # Get Range B data
        range_b_data = IQBDetailV2.objects.filter(
            range_b_filter & extra_filters
        ).values('employee_code', 'full_name').annotate(
            total_cost=Sum('amount')
        ).order_by('employee_code')

        # Combine into comparison table
        employee_comparison = {}

        for record in range_a_data:
            emp_code = record['employee_code']
            employee_comparison[emp_code] = {
                'employee_code': emp_code,
                'full_name': record['full_name'],
                'range_a_cost': record['total_cost'] or Decimal('0'),
                'range_b_cost': Decimal('0'),
                'variance': Decimal('0')
            }

        for record in range_b_data:
            emp_code = record['employee_code']
            if emp_code in employee_comparison:
                employee_comparison[emp_code]['range_b_cost'] = record['total_cost'] or Decimal('0')
            else:
                employee_comparison[emp_code] = {
                    'employee_code': emp_code,
                    'full_name': record['full_name'],
                    'range_a_cost': Decimal('0'),
                    'range_b_cost': record['total_cost'] or Decimal('0'),
                    'variance': Decimal('0')
                }

        # Calculate variances
        for emp_code in employee_comparison:
            emp_data = employee_comparison[emp_code]
            emp_data['variance'] = emp_data['range_b_cost'] - emp_data['range_a_cost']

        # Convert to list and sort by variance (descending)
        comparison_list = sorted(
            employee_comparison.values(),
            key=lambda x: abs(x['variance']),
            reverse=True
        )

        # Calculate totals
        range_a_total = sum(emp['range_a_cost'] for emp in comparison_list)
        range_b_total = sum(emp['range_b_cost'] for emp in comparison_list)
        total_variance = range_b_total - range_a_total

        context['section2'] = {
            'comparison_list': comparison_list,
            'range_a_total': range_a_total,
            'range_b_total': range_b_total,
            'total_variance': total_variance,
            'range_a_labels': [datetime(int(m.split('-')[0]), int(m.split('-')[1]), 1).strftime('%b %Y') for m in range_a_months],
            'range_b_labels': [datetime(int(m.split('-')[0]), int(m.split('-')[1]), 1).strftime('%b %Y') for m in range_b_months],
        }

    # SECTION 3: Bridge/Waterfall Chart Data
    if range_a_months and range_b_months:
        # Build filters (same as section 2)
        range_a_filter = Q()
        for month_str in range_a_months:
            year, month = map(int, month_str.split('-'))
            range_a_filter |= Q(period_end_date__year=year, period_end_date__month=month)

        range_b_filter = Q()
        for month_str in range_b_months:
            year, month = map(int, month_str.split('-'))
            range_b_filter |= Q(period_end_date__year=year, period_end_date__month=month)

        extra_filters = Q(include_in_costs=True)
        if selected_department:
            extra_filters &= Q(department_code=selected_department)
        if selected_location:
            extra_filters &= Q(location_id=selected_location)

        # Get employees in Range A
        range_a_employees = set(
            IQBDetailV2.objects.filter(range_a_filter & extra_filters)
            .values_list('employee_code', flat=True)
            .distinct()
        )

        # Get employees in Range B
        range_b_employees = set(
            IQBDetailV2.objects.filter(range_b_filter & extra_filters)
            .values_list('employee_code', flat=True)
            .distinct()
        )

        # Categorize employees
        continuing_employees = range_a_employees & range_b_employees  # In both ranges
        new_employees = range_b_employees - range_a_employees  # Only in Range B
        departed_employees = range_a_employees - range_b_employees  # Only in Range A

        # Calculate costs for each category

        # 1. Opening Balance (Range A total)
        opening_balance = context['section2']['range_a_total']

        # 2. Existing headcount increment/decrement by location
        location_deltas = {}
        for emp_code in continuing_employees:
            # Get Range A cost
            range_a_cost = IQBDetailV2.objects.filter(
                range_a_filter & extra_filters & Q(employee_code=emp_code)
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

            # Get Range B cost and location
            range_b_records = IQBDetailV2.objects.filter(
                range_b_filter & extra_filters & Q(employee_code=emp_code)
            ).aggregate(
                total=Sum('amount'),
            )
            range_b_cost = range_b_records['total'] or Decimal('0')

            # Get primary location for this employee in Range B
            primary_location = IQBDetailV2.objects.filter(
                range_b_filter & extra_filters & Q(employee_code=emp_code)
            ).values('location_id', 'location_name').annotate(
                total=Sum('amount')
            ).order_by('-total').first()

            if primary_location:
                location_key = f"{primary_location['location_id']} - {primary_location['location_name']}"
                if location_key not in location_deltas:
                    location_deltas[location_key] = Decimal('0')
                location_deltas[location_key] += (range_b_cost - range_a_cost)

        # 3. Additional headcount (new employees)
        new_headcount_cost = IQBDetailV2.objects.filter(
            range_b_filter & extra_filters & Q(employee_code__in=new_employees)
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        # 4. Decreased headcount (departed employees) - negative value
        departed_headcount_cost = -(IQBDetailV2.objects.filter(
            range_a_filter & extra_filters & Q(employee_code__in=departed_employees)
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0'))

        # 5. Closing Balance (Range B total)
        closing_balance = context['section2']['range_b_total']

        # Prepare waterfall chart data
        waterfall_data = {
            'opening_balance': float(opening_balance),
            'location_deltas': {k: float(v) for k, v in location_deltas.items() if v != 0},
            'new_headcount': float(new_headcount_cost),
            'departed_headcount': float(departed_headcount_cost),
            'closing_balance': float(closing_balance),
            'continuing_count': len(continuing_employees),
            'new_count': len(new_employees),
            'departed_count': len(departed_employees),
        }

        context['section3'] = waterfall_data

    return render(request, 'reconciliation/monthly_dashboard.html', context)


@require_http_methods(["GET"])
def download_comparison_data(request):
    """
    Download comparison data as CSV
    """
    from reconciliation.models import IQBDetailV2
    from datetime import datetime
    from django.db.models import Q
    import csv

    range_a_months = request.GET.getlist('range_a_months[]')
    range_b_months = request.GET.getlist('range_b_months[]')
    selected_department = request.GET.get('department')
    selected_location = request.GET.get('location')

    if not range_a_months or not range_b_months:
        return JsonResponse({'error': 'Missing range parameters'}, status=400)

    # Build filters
    range_a_filter = Q()
    for month_str in range_a_months:
        year, month = map(int, month_str.split('-'))
        range_a_filter |= Q(period_end_date__year=year, period_end_date__month=month)

    range_b_filter = Q()
    for month_str in range_b_months:
        year, month = map(int, month_str.split('-'))
        range_b_filter |= Q(period_end_date__year=year, period_end_date__month=month)

    extra_filters = Q(include_in_costs=True)
    if selected_department:
        extra_filters &= Q(department_code=selected_department)
    if selected_location:
        extra_filters &= Q(location_id=selected_location)

    # Get all records for both ranges
    records = IQBDetailV2.objects.filter(
        (range_a_filter | range_b_filter) & extra_filters
    ).select_related().order_by('employee_code', 'period_end_date', 'transaction_type')

    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="comparison_data.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Employee ID', 'Employee Name', 'Period Start Date', 'Period End Date',
        'Transaction Type', 'Amount', 'Location', 'Department', 'Range'
    ])

    for record in records:
        # Determine which range this record belongs to
        record_month = f"{record.period_end_date.year}-{record.period_end_date.month:02d}"
        if record_month in range_a_months:
            range_label = 'Range A'
        elif record_month in range_b_months:
            range_label = 'Range B'
        else:
            continue

        writer.writerow([
            record.employee_code,
            record.full_name,
            record.period_start_date.strftime('%Y-%m-%d') if record.period_start_date else '',
            record.period_end_date.strftime('%Y-%m-%d') if record.period_end_date else '',
            record.transaction_type,
            float(record.amount),
            f"{record.location_id} - {record.location_name}",
            f"{record.department_code} - {record.department_name}",
            range_label
        ])

    return response


def fne_dashboard(request):
    """
    FNE Payroll Comparison Dashboard
    Compare employee payroll costs between two pay periods from EmployeePayPeriodSnapshot
    Shows variance by department/location, headcount changes, and significant cost changes
    """
    from reconciliation.models import EmployeePayPeriodSnapshot, PayPeriod, SageLocation, SageDepartment
    from django.db.models import Sum, Count, Q, F, DecimalField
    from django.db.models.functions import Coalesce
    from collections import defaultdict
    import json

    # Get filter parameters
    period_a = request.GET.get('period_a')
    period_b = request.GET.get('period_b')

    # Get all available pay periods that have snapshots (actual_pay_period type only)
    available_periods = PayPeriod.objects.filter(
        process_type='actual_pay_period',
        employee_snapshots__isnull=False
    ).distinct().order_by('-period_end')

    # Build period options for dropdown
    period_options = []
    for period in available_periods:
        if period.period_start:
            label = f"{period.period_end.strftime('%Y-%m-%d')} ({period.period_start.strftime('%d %b')} - {period.period_end.strftime('%d %b %Y')})"
        else:
            label = f"{period.period_end.strftime('%Y-%m-%d')} (ending {period.period_end.strftime('%d %b %Y')})"
        period_options.append({
            'value': period.period_id,
            'label': label
        })

    # Get locations and departments for filtering
    locations = SageLocation.objects.all().order_by('location_name')
    departments = SageDepartment.objects.all().order_by('department_name')

    # Cache location names for lookup
    location_cache = {loc.location_id: loc.location_name for loc in locations}
    dept_cache = {dept.department_id: dept.department_name for dept in departments}

    context = {
        'period_options': period_options,
        'locations': locations,
        'departments': departments,
        'period_a': period_a,
        'period_b': period_b,
    }

    # If both periods selected, run comparison
    if period_a and period_b:
        # Get snapshots for both periods
        period_a_snapshots = list(EmployeePayPeriodSnapshot.objects.filter(
            pay_period_id=period_a
        ).select_related('pay_period'))

        period_b_snapshots = list(EmployeePayPeriodSnapshot.objects.filter(
            pay_period_id=period_b
        ).select_related('pay_period'))

        # Get period labels
        period_a_obj = PayPeriod.objects.filter(period_id=period_a).first()
        period_b_obj = PayPeriod.objects.filter(period_id=period_b).first()

        period_a_label = period_a_obj.period_end.strftime('%d %b %Y') if period_a_obj else period_a
        period_b_label = period_b_obj.period_end.strftime('%d %b %Y') if period_b_obj else period_b

        # Category breakdown - calculate GL totals for each category
        category_breakdown = {
            'salaries': {'name': 'Labour - Salaries', 'period_a': Decimal('0'), 'period_b': Decimal('0'), 'variance': Decimal('0')},
            'superannuation': {'name': 'Labour - Superannuation', 'period_a': Decimal('0'), 'period_b': Decimal('0'), 'variance': Decimal('0')},
            'al_provision': {'name': 'Payroll Liab - AL Provision', 'period_a': Decimal('0'), 'period_b': Decimal('0'), 'variance': Decimal('0')},
            'bonuses': {'name': 'Labour - Bonuses', 'period_a': Decimal('0'), 'period_b': Decimal('0'), 'variance': Decimal('0')},
            'other': {'name': 'Other', 'period_a': Decimal('0'), 'period_b': Decimal('0'), 'variance': Decimal('0')},
        }

        # Calculate category totals for Period A
        for snapshot in period_a_snapshots:
            category_breakdown['salaries']['period_a'] += snapshot.gl_6345_salaries or Decimal('0')
            category_breakdown['superannuation']['period_a'] += snapshot.gl_6370_superannuation or Decimal('0')
            category_breakdown['al_provision']['period_a'] += snapshot.gl_2310_annual_leave or Decimal('0')
            category_breakdown['bonuses']['period_a'] += snapshot.gl_6305 or Decimal('0')
            # Other = total_cost - (salaries + super + al + bonuses)
            known_cats = (snapshot.gl_6345_salaries or Decimal('0')) + \
                        (snapshot.gl_6370_superannuation or Decimal('0')) + \
                        (snapshot.gl_2310_annual_leave or Decimal('0')) + \
                        (snapshot.gl_6305 or Decimal('0'))
            category_breakdown['other']['period_a'] += (snapshot.total_cost or Decimal('0')) - known_cats

        # Calculate category totals for Period B
        for snapshot in period_b_snapshots:
            category_breakdown['salaries']['period_b'] += snapshot.gl_6345_salaries or Decimal('0')
            category_breakdown['superannuation']['period_b'] += snapshot.gl_6370_superannuation or Decimal('0')
            category_breakdown['al_provision']['period_b'] += snapshot.gl_2310_annual_leave or Decimal('0')
            category_breakdown['bonuses']['period_b'] += snapshot.gl_6305 or Decimal('0')
            # Other = total_cost - (salaries + super + al + bonuses)
            known_cats = (snapshot.gl_6345_salaries or Decimal('0')) + \
                        (snapshot.gl_6370_superannuation or Decimal('0')) + \
                        (snapshot.gl_2310_annual_leave or Decimal('0')) + \
                        (snapshot.gl_6305 or Decimal('0'))
            category_breakdown['other']['period_b'] += (snapshot.total_cost or Decimal('0')) - known_cats

        # Calculate variances for categories
        for cat_key in category_breakdown:
            category_breakdown[cat_key]['variance'] = category_breakdown[cat_key]['period_b'] - category_breakdown[cat_key]['period_a']

        # Convert to list for template
        category_list = [
            category_breakdown['salaries'],
            category_breakdown['superannuation'],
            category_breakdown['al_provision'],
            category_breakdown['bonuses'],
            category_breakdown['other'],
        ]

        # Build employee comparison dictionary with location info
        employee_comparison = {}
        period_a_by_code = {s.employee_code: s for s in period_a_snapshots}
        period_b_by_code = {s.employee_code: s for s in period_b_snapshots}

        # Helper function to get primary location from allocation
        def get_primary_location(allocation):
            if not allocation:
                return None, None
            max_loc = None
            max_pct = Decimal('0')
            for loc_id, depts in allocation.items():
                loc_total = sum(Decimal(str(pct)) for pct in depts.values())
                if loc_total > max_pct:
                    max_pct = loc_total
                    max_loc = loc_id
            if max_loc:
                loc_name = location_cache.get(max_loc, max_loc)
                return max_loc, f"{max_loc} - {loc_name}"
            return None, None

        # Process all employees
        all_employee_codes = set(period_a_by_code.keys()) | set(period_b_by_code.keys())

        for emp_code in all_employee_codes:
            snap_a = period_a_by_code.get(emp_code)
            snap_b = period_b_by_code.get(emp_code)

            cost_a = (snap_a.total_cost or Decimal('0')) if snap_a else Decimal('0')
            cost_b = (snap_b.total_cost or Decimal('0')) if snap_b else Decimal('0')

            # Get location - prefer period B, fall back to period A
            alloc = snap_b.cost_allocation if snap_b else (snap_a.cost_allocation if snap_a else {})
            loc_id, loc_key = get_primary_location(alloc)

            employee_comparison[emp_code] = {
                'employee_code': emp_code,
                'employee_name': (snap_b.employee_name if snap_b else snap_a.employee_name) if (snap_b or snap_a) else '',
                'period_a_cost': cost_a,
                'period_b_cost': cost_b,
                'variance': cost_b - cost_a,
                'location_id': loc_id,
                'location_key': loc_key or 'Unknown',
            }

        # Categorize employees
        period_a_employees = set(period_a_by_code.keys())
        period_b_employees = set(period_b_by_code.keys())
        continuing_employees = period_a_employees & period_b_employees
        new_employees = period_b_employees - period_a_employees
        departed_employees = period_a_employees - period_b_employees

        # Sort by absolute variance
        comparison_list = sorted(
            employee_comparison.values(),
            key=lambda x: abs(x['variance']),
            reverse=True
        )

        # Calculate totals
        period_a_total = sum(emp['period_a_cost'] for emp in comparison_list)
        period_b_total = sum(emp['period_b_cost'] for emp in comparison_list)
        total_variance = period_b_total - period_a_total

        # Calculate cost breakdown by location (using cached names)
        location_breakdown = defaultdict(lambda: {'period_a': Decimal('0'), 'period_b': Decimal('0'), 'variance': Decimal('0')})

        for snapshot in period_a_snapshots:
            if snapshot.cost_allocation:
                for loc_id, depts in snapshot.cost_allocation.items():
                    total_pct = sum(Decimal(str(pct)) for pct in depts.values())
                    allocated_cost = (snapshot.total_cost or Decimal('0')) * total_pct / 100
                    loc_name = location_cache.get(loc_id, loc_id)
                    location_breakdown[f"{loc_id} - {loc_name}"]['period_a'] += allocated_cost

        for snapshot in period_b_snapshots:
            if snapshot.cost_allocation:
                for loc_id, depts in snapshot.cost_allocation.items():
                    total_pct = sum(Decimal(str(pct)) for pct in depts.values())
                    allocated_cost = (snapshot.total_cost or Decimal('0')) * total_pct / 100
                    loc_name = location_cache.get(loc_id, loc_id)
                    location_breakdown[f"{loc_id} - {loc_name}"]['period_b'] += allocated_cost

        # Calculate variances for locations
        for loc_key in location_breakdown:
            location_breakdown[loc_key]['variance'] = (
                location_breakdown[loc_key]['period_b'] - location_breakdown[loc_key]['period_a']
            )

        # Sort location breakdown by absolute variance
        location_breakdown_list = sorted(
            [{'location': k, **v} for k, v in location_breakdown.items()],
            key=lambda x: abs(x['variance']),
            reverse=True
        )

        # Calculate cost breakdown by department
        dept_breakdown = defaultdict(lambda: {'period_a': Decimal('0'), 'period_b': Decimal('0'), 'variance': Decimal('0')})

        for snapshot in period_a_snapshots:
            if snapshot.cost_allocation:
                for loc_id, depts in snapshot.cost_allocation.items():
                    for dept_id, pct in depts.items():
                        allocated_cost = (snapshot.total_cost or Decimal('0')) * Decimal(str(pct)) / 100
                        dept_name = dept_cache.get(dept_id, dept_id)
                        dept_breakdown[f"{dept_id} - {dept_name}"]['period_a'] += allocated_cost

        for snapshot in period_b_snapshots:
            if snapshot.cost_allocation:
                for loc_id, depts in snapshot.cost_allocation.items():
                    for dept_id, pct in depts.items():
                        allocated_cost = (snapshot.total_cost or Decimal('0')) * Decimal(str(pct)) / 100
                        dept_name = dept_cache.get(dept_id, dept_id)
                        dept_breakdown[f"{dept_id} - {dept_name}"]['period_b'] += allocated_cost

        # Calculate variances for departments
        for dept_key in dept_breakdown:
            dept_breakdown[dept_key]['variance'] = (
                dept_breakdown[dept_key]['period_b'] - dept_breakdown[dept_key]['period_a']
            )

        # Sort department breakdown by absolute variance
        dept_breakdown_list = sorted(
            [{'department': k, **v} for k, v in dept_breakdown.items()],
            key=lambda x: abs(x['variance']),
            reverse=True
        )

        # Build location movement table with new/departed employee details
        location_movement = defaultdict(lambda: {
            'new_count': 0, 'new_value': Decimal('0'),
            'departed_count': 0, 'departed_value': Decimal('0'),
            'variance': Decimal('0'),
            'new_employees': [], 'departed_employees': []
        })

        # Process new employees
        for emp_code in new_employees:
            emp_data = employee_comparison[emp_code]
            loc_key = emp_data['location_key']
            location_movement[loc_key]['new_count'] += 1
            location_movement[loc_key]['new_value'] += emp_data['period_b_cost']
            location_movement[loc_key]['new_employees'].append({
                'employee_code': emp_code,
                'employee_name': emp_data['employee_name'],
                'value': emp_data['period_b_cost']
            })

        # Process departed employees
        for emp_code in departed_employees:
            emp_data = employee_comparison[emp_code]
            loc_key = emp_data['location_key']
            location_movement[loc_key]['departed_count'] += 1
            location_movement[loc_key]['departed_value'] += emp_data['period_a_cost']
            location_movement[loc_key]['departed_employees'].append({
                'employee_code': emp_code,
                'employee_name': emp_data['employee_name'],
                'value': emp_data['period_a_cost']
            })

        # Calculate variance for each location in movement table
        for loc_key in location_movement:
            loc_data = location_movement[loc_key]
            loc_data['variance'] = loc_data['new_value'] - loc_data['departed_value']

        # Sort location movement by absolute variance and convert to list
        location_movement_list = sorted(
            [{'location': k, **v} for k, v in location_movement.items()],
            key=lambda x: abs(x['variance']),
            reverse=True
        )

        # Calculate totals for location movement
        total_new_count = sum(loc['new_count'] for loc in location_movement_list)
        total_new_value = sum(loc['new_value'] for loc in location_movement_list)
        total_departed_count = sum(loc['departed_count'] for loc in location_movement_list)
        total_departed_value = sum(loc['departed_value'] for loc in location_movement_list)
        total_movement_variance = total_new_value - total_departed_value

        # Prepare JSON data for JavaScript (expandable rows)
        location_employees_json = {}
        for loc in location_movement_list:
            location_employees_json[loc['location']] = {
                'new_employees': [
                    {'code': e['employee_code'], 'name': e['employee_name'], 'value': float(e['value'])}
                    for e in loc['new_employees']
                ],
                'departed_employees': [
                    {'code': e['employee_code'], 'name': e['employee_name'], 'value': float(e['value'])}
                    for e in loc['departed_employees']
                ]
            }

        context['comparison'] = {
            'comparison_list': comparison_list,
            'period_a_total': period_a_total,
            'period_b_total': period_b_total,
            'total_variance': total_variance,
            'period_a_label': period_a_label,
            'period_b_label': period_b_label,
            'location_breakdown': location_breakdown_list,
            'dept_breakdown': dept_breakdown_list,
            'category_breakdown': category_list,
        }

        context['headcount'] = {
            'continuing_count': len(continuing_employees),
            'new_count': len(new_employees),
            'departed_count': len(departed_employees),
            'period_a_count': len(period_a_employees),
            'period_b_count': len(period_b_employees),
        }

        context['location_movement'] = {
            'locations': location_movement_list,
            'total_new_count': total_new_count,
            'total_new_value': total_new_value,
            'total_departed_count': total_departed_count,
            'total_departed_value': total_departed_value,
            'total_variance': total_movement_variance,
            'employees_json': json.dumps(location_employees_json),
        }

    return render(request, 'reconciliation/fne_dashboard.html', context)


@require_http_methods(["GET"])
def download_fne_comparison(request):
    """
    Download FNE comparison data as CSV
    """
    from reconciliation.models import EmployeePayPeriodSnapshot, PayPeriod
    import csv

    period_a = request.GET.get('period_a')
    period_b = request.GET.get('period_b')

    if not period_a or not period_b:
        return JsonResponse({'error': 'Missing period parameters'}, status=400)

    # Get snapshots for both periods
    period_a_snapshots = {
        s.employee_code: s for s in
        EmployeePayPeriodSnapshot.objects.filter(pay_period_id=period_a)
    }
    period_b_snapshots = {
        s.employee_code: s for s in
        EmployeePayPeriodSnapshot.objects.filter(pay_period_id=period_b)
    }

    # Get all employee codes
    all_employees = set(period_a_snapshots.keys()) | set(period_b_snapshots.keys())

    # Get period labels
    period_a_obj = PayPeriod.objects.filter(period_id=period_a).first()
    period_b_obj = PayPeriod.objects.filter(period_id=period_b).first()

    period_a_label = period_a_obj.period_end.strftime('%Y-%m-%d') if period_a_obj else period_a
    period_b_label = period_b_obj.period_end.strftime('%Y-%m-%d') if period_b_obj else period_b

    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="fne_comparison_{period_a}_vs_{period_b}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Employee Code', 'Employee Name', 'Status',
        f'Period A ({period_a_label}) Cost', f'Period B ({period_b_label}) Cost',
        'Variance', 'Variance %',
        'Period A Allocation', 'Period B Allocation'
    ])

    for emp_code in sorted(all_employees):
        snap_a = period_a_snapshots.get(emp_code)
        snap_b = period_b_snapshots.get(emp_code)

        cost_a = float(snap_a.total_cost or 0) if snap_a else 0
        cost_b = float(snap_b.total_cost or 0) if snap_b else 0
        variance = cost_b - cost_a
        variance_pct = (variance / cost_a * 100) if cost_a != 0 else (100 if cost_b > 0 else 0)

        # Determine status
        if snap_a and snap_b:
            status = 'Continuing'
        elif snap_b and not snap_a:
            status = 'New'
        else:
            status = 'Departed'

        emp_name = snap_b.employee_name if snap_b else (snap_a.employee_name if snap_a else '')

        # Get allocation summaries
        alloc_a = snap_a.get_allocation_summary() if snap_a else ''
        alloc_b = snap_b.get_allocation_summary() if snap_b else ''

        writer.writerow([
            emp_code,
            emp_name,
            status,
            f'{cost_a:.2f}',
            f'{cost_b:.2f}',
            f'{variance:.2f}',
            f'{variance_pct:.1f}%',
            alloc_a,
            alloc_b
        ])

    return response


@require_http_methods(["POST"])
def ai_cost_analysis(request):
    """
    AI-Powered cost analysis endpoint
    Supports both structured queries and natural language
    """
    import os
    from mcp_server.server import analyze_location_costs_detailed, list_locations, list_pay_periods

    try:
        data = json.loads(request.body)
        query = data.get('query', '').strip()
        mode = data.get('mode', 'auto')  # 'auto', 'structured', 'natural'

        if not query:
            return JsonResponse({'error': 'Query is required'}, status=400)

        # Mode 1: Structured query (direct parameters)
        if mode == 'structured':
            location = data.get('location')
            period_a = data.get('period_a')
            period_b = data.get('period_b')

            if not all([location, period_a, period_b]):
                return JsonResponse({
                    'error': 'Structured mode requires location, period_a, and period_b'
                }, status=400)

            result = analyze_location_costs_detailed(location, period_a, period_b)

            return JsonResponse({
                'success': True,
                'mode': 'structured',
                'result': result,
                'query': f"Analyzing {location} between {period_a} and {period_b}"
            })

        # Mode 2: Natural language query using Claude API
        elif mode == 'natural' or mode == 'auto':
            import anthropic

            api_key = os.environ.get('ANTHROPIC_API_KEY')
            if not api_key:
                return JsonResponse({
                    'error': 'ANTHROPIC_API_KEY not configured'
                }, status=500)

            client = anthropic.Anthropic(api_key=api_key)

            # Get available locations and periods for context
            locations_list = list_locations()
            periods_list = list_pay_periods(limit=20)

            # Ask Claude to parse the query and extract parameters
            parse_response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=1000,
                temperature=0,
                system=f"""You are a payroll data analysis assistant. Extract location and period information from user queries.

Available locations:
{locations_list}

Available pay periods:
{periods_list}

Return a JSON object with these fields:
- "location": the location name (match to available locations)
- "period_a": first period ID in YYYY-MM-DD format
- "period_b": second period ID in YYYY-MM-DD format
- "intent": brief description of what the user wants

If the query is unclear or missing information, return an error message in the "error" field instead.""",
                messages=[{
                    "role": "user",
                    "content": query
                }]
            )

            # Parse Claude's response
            try:
                parsed = json.loads(parse_response.content[0].text)

                if 'error' in parsed:
                    return JsonResponse({
                        'success': False,
                        'error': parsed['error'],
                        'mode': 'natural'
                    })

                location = parsed.get('location')
                period_a = parsed.get('period_a')
                period_b = parsed.get('period_b')
                intent = parsed.get('intent', query)

                # Call the MCP function
                result = analyze_location_costs_detailed(location, period_a, period_b)

                return JsonResponse({
                    'success': True,
                    'mode': 'natural',
                    'result': result,
                    'query': intent,
                    'parsed': {
                        'location': location,
                        'period_a': period_a,
                        'period_b': period_b
                    }
                })

            except json.JSONDecodeError:
                return JsonResponse({
                    'error': 'Failed to parse AI response',
                    'mode': 'natural'
                }, status=500)

    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)


@require_http_methods(["GET"])
def get_analysis_options(request):
    """
    Get available locations and periods for the AI analysis interface
    """
    from reconciliation.models import SageLocation, PayPeriod

    # Get locations
    locations = list(SageLocation.objects.all().order_by('location_name').values('location_id', 'location_name'))

    # Get available pay periods
    periods = list(PayPeriod.objects.filter(
        process_type='actual_pay_period',
        employee_snapshots__isnull=False
    ).distinct().order_by('-period_end').values('period_id', 'period_start', 'period_end')[:20])

    # Format periods for display
    period_options = []
    for p in periods:
        if p['period_start']:
            label = f"{p['period_id']} ({p['period_start'].strftime('%d %b')} - {p['period_end'].strftime('%d %b %Y')})"
        else:
            label = f"{p['period_id']} (ending {p['period_end'].strftime('%d %b %Y')})"
        period_options.append({
            'value': p['period_id'],
            'label': label
        })

    return JsonResponse({
        'locations': locations,
        'periods': period_options
    })


@require_http_methods(["POST"])
def get_department_employee_changes(request):
    """
    Get employee-level changes for a specific department and location between two periods
    Shows who joined, left, and stayed
    """
    from reconciliation.models import EmployeePayPeriodSnapshot, SageDepartment
    from collections import defaultdict

    try:
        data = json.loads(request.body)
        location_id = data.get('location_id')
        department_id = data.get('department_id')
        period_a = data.get('period_a')
        period_b = data.get('period_b')

        if not all([location_id, department_id, period_a, period_b]):
            return JsonResponse({'error': 'Missing required parameters'}, status=400)

        # Get department name
        dept = SageDepartment.objects.filter(department_id=department_id).first()
        dept_name = dept.department_name if dept else department_id

        # Get snapshots for both periods
        snapshots_a = EmployeePayPeriodSnapshot.objects.filter(pay_period_id=period_a)
        snapshots_b = EmployeePayPeriodSnapshot.objects.filter(pay_period_id=period_b)

        # Helper to extract employees in specific department at location
        def get_dept_employees(snapshots):
            employees = {}
            for snap in snapshots:
                if not snap.cost_allocation:
                    continue

                allocation = snap.cost_allocation
                if isinstance(allocation, str):
                    allocation = json.loads(allocation)

                # Check if employee is in this location and department
                if location_id in allocation:
                    dept_alloc = allocation[location_id]
                    if department_id in dept_alloc:
                        pct = Decimal(str(dept_alloc[department_id]))
                        allocated_cost = (snap.total_cost or Decimal('0')) * pct / 100

                        employees[snap.employee_code] = {
                            'employee_code': snap.employee_code,
                            'employee_name': snap.employee_name,
                            'cost': float(allocated_cost),
                            'allocation_pct': float(pct)
                        }
            return employees

        employees_a = get_dept_employees(snapshots_a)
        employees_b = get_dept_employees(snapshots_b)

        # Categorize employees
        codes_a = set(employees_a.keys())
        codes_b = set(employees_b.keys())

        new_employees = []
        departed_employees = []
        continuing_employees = []

        # New employees (in B but not in A)
        for code in codes_b - codes_a:
            new_employees.append(employees_b[code])

        # Departed employees (in A but not in B)
        for code in codes_a - codes_b:
            departed_employees.append(employees_a[code])

        # Continuing employees (in both)
        for code in codes_a & codes_b:
            emp_a = employees_a[code]
            emp_b = employees_b[code]
            continuing_employees.append({
                'employee_code': code,
                'employee_name': emp_b['employee_name'],
                'cost_a': emp_a['cost'],
                'cost_b': emp_b['cost'],
                'cost_change': emp_b['cost'] - emp_a['cost'],
                'allocation_pct_a': emp_a['allocation_pct'],
                'allocation_pct_b': emp_b['allocation_pct']
            })

        # Sort by cost
        new_employees.sort(key=lambda x: -x['cost'])
        departed_employees.sort(key=lambda x: -x['cost'])
        continuing_employees.sort(key=lambda x: -abs(x['cost_change']))

        return JsonResponse({
            'success': True,
            'department_name': dept_name,
            'department_id': department_id,
            'new_employees': new_employees,
            'departed_employees': departed_employees,
            'continuing_employees': continuing_employees,
            'summary': {
                'new_count': len(new_employees),
                'departed_count': len(departed_employees),
                'continuing_count': len(continuing_employees),
                'new_total': sum(e['cost'] for e in new_employees),
                'departed_total': sum(e['cost'] for e in departed_employees)
            }
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def monthly_snapshot_dashboard(request):
    """
    Monthly snapshot dashboard showing aggregated employee payroll data
    for all pay periods where period_end falls in the selected month.
    """
    from django.db.models.functions import TruncMonth
    from reconciliation.models import SageLocation, SageDepartment

    selected_month = request.GET.get('month')

    # Get distinct months from pay periods with snapshots
    months_with_data = PayPeriod.objects.filter(
        process_type='actual_pay_period',
        employee_snapshots__isnull=False
    ).annotate(
        month=TruncMonth('period_end')
    ).values('month').distinct().order_by('-month')

    month_options = []
    for m in months_with_data:
        if m['month']:
            month_options.append({
                'value': m['month'].strftime('%Y-%m'),
                'label': m['month'].strftime('%B %Y')
            })

    # Cache location/department names
    location_cache = {loc.location_id: loc.location_name for loc in SageLocation.objects.all()}
    dept_cache = {dept.department_id: dept.department_name for dept in SageDepartment.objects.all()}

    context = {
        'month_options': month_options,
        'selected_month': selected_month,
    }

    if selected_month:
        year, month = map(int, selected_month.split('-'))

        # Get pay periods for selected month
        pay_periods = PayPeriod.objects.filter(
            period_end__year=year,
            period_end__month=month,
            process_type='actual_pay_period'
        ).order_by('period_end')

        pay_period_list = list(pay_periods)
        pay_period_ids = [pp.period_id for pp in pay_period_list]

        # Get all snapshots for these periods
        snapshots = EmployeePayPeriodSnapshot.objects.filter(
            pay_period__in=pay_periods
        ).select_related('pay_period').order_by('employee_code')

        # Aggregate by employee
        employee_data = defaultdict(lambda: {
            'employee_code': '',
            'employee_name': '',
            'employment_status': '',
            'periods': [],
            'gl_6345_salaries': Decimal('0'),
            'gl_6370_superannuation': Decimal('0'),
            'gl_6300': Decimal('0'),
            'gl_6355_sick_leave': Decimal('0'),
            'gl_6305': Decimal('0'),
            'gl_6335': Decimal('0'),
            'gl_6380': Decimal('0'),
            'total_cost': Decimal('0'),
            'total_hours': Decimal('0'),
            'cost_allocation': {},
            'primary_location': '',
            'primary_department': '',
            'allocation_summary': '',
        })

        for snapshot in snapshots:
            emp = employee_data[snapshot.employee_code]
            emp['employee_code'] = snapshot.employee_code
            emp['employee_name'] = snapshot.employee_name
            emp['employment_status'] = snapshot.employment_status or ''
            emp['periods'].append(snapshot.pay_period.period_id)

            # Sum GL fields
            emp['gl_6345_salaries'] += snapshot.gl_6345_salaries or Decimal('0')
            emp['gl_6370_superannuation'] += snapshot.gl_6370_superannuation or Decimal('0')
            emp['gl_6300'] += snapshot.gl_6300 or Decimal('0')
            emp['gl_6355_sick_leave'] += snapshot.gl_6355_sick_leave or Decimal('0')
            emp['gl_6305'] += snapshot.gl_6305 or Decimal('0')
            emp['gl_6335'] += snapshot.gl_6335 or Decimal('0')
            emp['gl_6380'] += snapshot.gl_6380 or Decimal('0')
            emp['total_cost'] += snapshot.total_cost or Decimal('0')
            emp['total_hours'] += snapshot.total_hours or Decimal('0')

            # Keep latest allocation
            if snapshot.cost_allocation:
                emp['cost_allocation'] = snapshot.cost_allocation

        # Extract primary location/department for each employee
        for emp_code, emp in employee_data.items():
            if emp['cost_allocation']:
                max_pct = Decimal('0')
                summary_parts = []

                for location, departments in emp['cost_allocation'].items():
                    for dept, pct in departments.items():
                        pct_decimal = Decimal(str(pct))
                        loc_name = location_cache.get(location, location)
                        dept_name = dept_cache.get(dept, dept)
                        summary_parts.append(f"{location}-{dept}: {pct}%")

                        if pct_decimal > max_pct:
                            max_pct = pct_decimal
                            emp['primary_location'] = location
                            emp['primary_department'] = dept

                emp['allocation_summary'] = "; ".join(sorted(summary_parts))

        # Convert to list and sort by employee code
        employee_list = sorted(employee_data.values(), key=lambda x: x['employee_code'])

        # Calculate summary totals
        summary = {
            'total_employees': len(employee_list),
            'pay_periods_count': len(pay_period_list),
            'pay_periods': pay_period_ids,
            'total_6345': sum(e['gl_6345_salaries'] for e in employee_list),
            'total_6370': sum(e['gl_6370_superannuation'] for e in employee_list),
            'total_6300': sum(e['gl_6300'] for e in employee_list),
            'total_6355': sum(e['gl_6355_sick_leave'] for e in employee_list),
            'total_6305': sum(e['gl_6305'] for e in employee_list),
            'total_6335': sum(e['gl_6335'] for e in employee_list),
            'total_6380': sum(e['gl_6380'] for e in employee_list),
            'total_cost': sum(e['total_cost'] for e in employee_list),
            'total_hours': sum(e['total_hours'] for e in employee_list),
        }

        from datetime import datetime
        context['selected_month_label'] = datetime(year, month, 1).strftime('%B %Y')
        context['employee_data'] = employee_list
        context['summary'] = summary
        context['pay_periods'] = pay_period_list

    return render(request, 'reconciliation/monthly_snapshot_dashboard.html', context)


@require_http_methods(["GET"])
def download_monthly_snapshot(request):
    """
    Download monthly snapshot data as CSV.
    Supports both summary (one row per employee) and detailed (one row per employee-period) formats.
    """
    from reconciliation.models import SageLocation, SageDepartment

    selected_month = request.GET.get('month')
    download_format = request.GET.get('format', 'summary')  # 'summary' or 'detailed'

    if not selected_month:
        return JsonResponse({'error': 'Month parameter is required'}, status=400)

    year, month = map(int, selected_month.split('-'))

    # Get pay periods for selected month
    pay_periods = PayPeriod.objects.filter(
        period_end__year=year,
        period_end__month=month,
        process_type='actual_pay_period'
    ).order_by('period_end')

    # Get all snapshots for these periods
    snapshots = EmployeePayPeriodSnapshot.objects.filter(
        pay_period__in=pay_periods
    ).select_related('pay_period').order_by('employee_code', 'pay_period__period_end')

    # Cache location/department names
    location_cache = {loc.location_id: loc.location_name for loc in SageLocation.objects.all()}
    dept_cache = {dept.department_id: dept.department_name for dept in SageDepartment.objects.all()}

    # Prepare CSV response
    response = HttpResponse(content_type='text/csv')
    filename = f"Monthly_Snapshot_{selected_month}_{download_format}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)

    if download_format == 'detailed':
        # Detailed format: one row per employee-period
        writer.writerow([
            'Employee Code', 'Employee Name', 'Employment Status',
            'Pay Period ID', 'Period Start', 'Period End',
            'Primary Location', 'Primary Department', 'Allocation Summary',
            'GL 6345 Salaries', 'GL 6370 Superannuation', 'GL 6300 Annual Leave',
            'GL 6355 Sick Leave', 'GL 6305 Bonuses', 'GL 6335 Payroll Tax',
            'GL 6380 Workcover', 'Total Cost', 'Total Hours'
        ])

        for snapshot in snapshots:
            # Extract primary location/department
            primary_loc = ''
            primary_dept = ''
            allocation_summary = ''

            if snapshot.cost_allocation:
                max_pct = Decimal('0')
                summary_parts = []

                for location, departments in snapshot.cost_allocation.items():
                    for dept, pct in departments.items():
                        pct_decimal = Decimal(str(pct))
                        summary_parts.append(f"{location}-{dept}: {pct}%")

                        if pct_decimal > max_pct:
                            max_pct = pct_decimal
                            primary_loc = location
                            primary_dept = dept

                allocation_summary = "; ".join(sorted(summary_parts))

            writer.writerow([
                snapshot.employee_code,
                snapshot.employee_name,
                snapshot.employment_status or '',
                snapshot.pay_period.period_id,
                snapshot.pay_period.period_start.strftime('%Y-%m-%d') if snapshot.pay_period.period_start else '',
                snapshot.pay_period.period_end.strftime('%Y-%m-%d') if snapshot.pay_period.period_end else '',
                primary_loc,
                primary_dept,
                allocation_summary,
                float(snapshot.gl_6345_salaries or 0),
                float(snapshot.gl_6370_superannuation or 0),
                float(snapshot.gl_6300 or 0),
                float(snapshot.gl_6355_sick_leave or 0),
                float(snapshot.gl_6305 or 0),
                float(snapshot.gl_6335 or 0),
                float(snapshot.gl_6380 or 0),
                float(snapshot.total_cost or 0),
                float(snapshot.total_hours or 0),
            ])

    else:
        # Summary format: one row per employee (aggregated)
        writer.writerow([
            'Employee Code', 'Employee Name', 'Employment Status',
            'Period Count', 'Period IDs',
            'Primary Location', 'Primary Department', 'Allocation Summary',
            'GL 6345 Salaries', 'GL 6370 Superannuation', 'GL 6300 Annual Leave',
            'GL 6355 Sick Leave', 'GL 6305 Bonuses', 'GL 6335 Payroll Tax',
            'GL 6380 Workcover', 'Total Cost', 'Total Hours'
        ])

        # Aggregate by employee
        employee_data = defaultdict(lambda: {
            'employee_code': '',
            'employee_name': '',
            'employment_status': '',
            'periods': [],
            'gl_6345_salaries': Decimal('0'),
            'gl_6370_superannuation': Decimal('0'),
            'gl_6300': Decimal('0'),
            'gl_6355_sick_leave': Decimal('0'),
            'gl_6305': Decimal('0'),
            'gl_6335': Decimal('0'),
            'gl_6380': Decimal('0'),
            'total_cost': Decimal('0'),
            'total_hours': Decimal('0'),
            'cost_allocation': {},
        })

        for snapshot in snapshots:
            emp = employee_data[snapshot.employee_code]
            emp['employee_code'] = snapshot.employee_code
            emp['employee_name'] = snapshot.employee_name
            emp['employment_status'] = snapshot.employment_status or ''
            emp['periods'].append(snapshot.pay_period.period_id)

            emp['gl_6345_salaries'] += snapshot.gl_6345_salaries or Decimal('0')
            emp['gl_6370_superannuation'] += snapshot.gl_6370_superannuation or Decimal('0')
            emp['gl_6300'] += snapshot.gl_6300 or Decimal('0')
            emp['gl_6355_sick_leave'] += snapshot.gl_6355_sick_leave or Decimal('0')
            emp['gl_6305'] += snapshot.gl_6305 or Decimal('0')
            emp['gl_6335'] += snapshot.gl_6335 or Decimal('0')
            emp['gl_6380'] += snapshot.gl_6380 or Decimal('0')
            emp['total_cost'] += snapshot.total_cost or Decimal('0')
            emp['total_hours'] += snapshot.total_hours or Decimal('0')

            if snapshot.cost_allocation:
                emp['cost_allocation'] = snapshot.cost_allocation

        # Write rows
        for emp_code in sorted(employee_data.keys()):
            emp = employee_data[emp_code]

            # Extract primary location/department
            primary_loc = ''
            primary_dept = ''
            allocation_summary = ''

            if emp['cost_allocation']:
                max_pct = Decimal('0')
                summary_parts = []

                for location, departments in emp['cost_allocation'].items():
                    for dept, pct in departments.items():
                        pct_decimal = Decimal(str(pct))
                        summary_parts.append(f"{location}-{dept}: {pct}%")

                        if pct_decimal > max_pct:
                            max_pct = pct_decimal
                            primary_loc = location
                            primary_dept = dept

                allocation_summary = "; ".join(sorted(summary_parts))

            writer.writerow([
                emp['employee_code'],
                emp['employee_name'],
                emp['employment_status'],
                len(emp['periods']),
                ', '.join(emp['periods']),
                primary_loc,
                primary_dept,
                allocation_summary,
                float(emp['gl_6345_salaries']),
                float(emp['gl_6370_superannuation']),
                float(emp['gl_6300']),
                float(emp['gl_6355_sick_leave']),
                float(emp['gl_6305']),
                float(emp['gl_6335']),
                float(emp['gl_6380']),
                float(emp['total_cost']),
                float(emp['total_hours']),
            ])

        # Write totals row
        totals = {
            'gl_6345_salaries': sum(e['gl_6345_salaries'] for e in employee_data.values()),
            'gl_6370_superannuation': sum(e['gl_6370_superannuation'] for e in employee_data.values()),
            'gl_6300': sum(e['gl_6300'] for e in employee_data.values()),
            'gl_6355_sick_leave': sum(e['gl_6355_sick_leave'] for e in employee_data.values()),
            'gl_6305': sum(e['gl_6305'] for e in employee_data.values()),
            'gl_6335': sum(e['gl_6335'] for e in employee_data.values()),
            'gl_6380': sum(e['gl_6380'] for e in employee_data.values()),
            'total_cost': sum(e['total_cost'] for e in employee_data.values()),
            'total_hours': sum(e['total_hours'] for e in employee_data.values()),
        }

        writer.writerow([
            'TOTAL', '', '',
            '', '',
            '', '', '',
            float(totals['gl_6345_salaries']),
            float(totals['gl_6370_superannuation']),
            float(totals['gl_6300']),
            float(totals['gl_6355_sick_leave']),
            float(totals['gl_6305']),
            float(totals['gl_6335']),
            float(totals['gl_6380']),
            float(totals['total_cost']),
            float(totals['total_hours']),
        ])

    return response
