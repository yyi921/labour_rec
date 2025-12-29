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
