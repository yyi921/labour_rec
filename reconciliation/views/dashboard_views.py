"""
Reconciliation Dashboard Views
"""
from django.shortcuts import render, get_object_or_404
from django.db.models import Sum, Count, Avg, Q
from decimal import Decimal

from reconciliation.models import (
    PayPeriod, ReconciliationRun, EmployeeReconciliation,
    JournalReconciliation
)


def reconciliation_dashboard(request, pay_period_id):
    """
    Main reconciliation dashboard showing all summary tables
    """
    pay_period = get_object_or_404(PayPeriod, period_id=pay_period_id)

    # Get the latest reconciliation run for this pay period
    recon_run = ReconciliationRun.objects.filter(
        pay_period=pay_period
    ).order_by('-started_at').first()

    if not recon_run:
        return render(request, 'reconciliation/dashboard.html', {
            'pay_period': pay_period,
            'error': 'No reconciliation run found for this pay period'
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
