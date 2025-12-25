"""
Analytics Tools Library
Provides database query functions for Claude API Tool Use
"""
from django.db.models import Count, Sum, Avg, Q, F, FloatField, Value, Case, When
from django.db.models.functions import Cast, Coalesce
from reconciliation.models import (
    Employee, PayPeriod, EmployeeReconciliation, EmployeePayPeriodSnapshot,
    TandaTimesheet, IQBDetail, JournalEntry
)
from decimal import Decimal
from datetime import datetime, timedelta


def get_employee_statistics(filters=None, group_by=None):
    """
    Get employee statistics with optional filtering and grouping

    Args:
        filters (dict): Filters to apply (location, employment_type, auto_pay, etc.)
        group_by (str): Field to group by (location, employment_type, etc.)

    Returns:
        list: Statistics with counts and percentages
    """
    queryset = Employee.objects.all()

    # Apply filters
    if filters:
        if 'location' in filters and filters['location']:
            queryset = queryset.filter(location__icontains=filters['location'])
        if 'employment_type' in filters and filters['employment_type']:
            queryset = queryset.filter(employment_type__icontains=filters['employment_type'])
        if 'auto_pay' in filters and filters['auto_pay']:
            queryset = queryset.filter(auto_pay=filters['auto_pay'])
        if 'is_active' in filters:
            if filters['is_active']:
                queryset = queryset.filter(termination_date__isnull=True)
            else:
                queryset = queryset.filter(termination_date__isnull=False)

    # Group and aggregate
    if group_by:
        results = queryset.values(group_by).annotate(
            total=Count('code'),
            salaried=Count('code', filter=Q(auto_pay='Yes')),
            hourly=Count('code', filter=Q(auto_pay='No')),
            active=Count('code', filter=Q(termination_date__isnull=True)),
            terminated=Count('code', filter=Q(termination_date__isnull=False))
        ).order_by(f'-{group_by}')

        # Calculate percentages
        for result in results:
            if result['total'] > 0:
                result['salaried_pct'] = round(result['salaried'] / result['total'] * 100, 2)
                result['hourly_pct'] = round(result['hourly'] / result['total'] * 100, 2)
                result['active_pct'] = round(result['active'] / result['total'] * 100, 2)

        return list(results)
    else:
        # Overall statistics
        total = queryset.count()
        salaried = queryset.filter(auto_pay='Yes').count()
        hourly = queryset.filter(auto_pay='No').count()
        active = queryset.filter(termination_date__isnull=True).count()
        terminated = queryset.filter(termination_date__isnull=False).count()

        return {
            'total': total,
            'salaried': salaried,
            'hourly': hourly,
            'active': active,
            'terminated': terminated,
            'salaried_pct': round(salaried / total * 100, 2) if total > 0 else 0,
            'hourly_pct': round(hourly / total * 100, 2) if total > 0 else 0,
            'active_pct': round(active / total * 100, 2) if total > 0 else 0
        }


def get_payroll_summary(pay_period_id):
    """
    Get payroll summary for a specific pay period

    Args:
        pay_period_id (str): Pay period ID (YYYY-MM-DD)

    Returns:
        dict: Payroll summary with totals and breakdowns
    """
    try:
        pay_period = PayPeriod.objects.get(period_id=pay_period_id)
    except PayPeriod.DoesNotExist:
        return {'error': f'Pay period {pay_period_id} not found'}

    snapshots = EmployeePayPeriodSnapshot.objects.filter(pay_period=pay_period)

    if not snapshots.exists():
        return {'error': f'No data found for pay period {pay_period_id}'}

    summary = snapshots.aggregate(
        total_cost=Coalesce(Sum('total_cost'), Value(0)),
        total_hours=Coalesce(Sum('total_hours'), Value(0)),
        employee_count=Count('employee_code', distinct=True)
    )

    # Get breakdown by employment type/location if available
    breakdown = snapshots.values('employment_status').annotate(
        cost=Sum('total_cost'),
        count=Count('employee_code')
    ).order_by('-cost')

    return {
        'pay_period': pay_period_id,
        'total_cost': float(summary['total_cost'] or 0),
        'total_hours': float(summary['total_hours'] or 0),
        'employee_count': summary['employee_count'],
        'breakdown': list(breakdown)
    }


def compare_pay_periods(period_1, period_2, breakdown_by='location'):
    """
    Compare two pay periods and return variance data

    Args:
        period_1 (str): First pay period ID (YYYY-MM-DD)
        period_2 (str): Second pay period ID (YYYY-MM-DD)
        breakdown_by (str): How to break down variance (location, employment_status, etc.)

    Returns:
        dict: Comparison data with variances and breakdown
    """
    # Get data for both periods
    try:
        pp1 = PayPeriod.objects.get(period_id=period_1)
        pp2 = PayPeriod.objects.get(period_id=period_2)
    except PayPeriod.DoesNotExist as e:
        return {'error': str(e)}

    data1 = EmployeePayPeriodSnapshot.objects.filter(pay_period=pp1)
    data2 = EmployeePayPeriodSnapshot.objects.filter(pay_period=pp2)

    if not data1.exists() or not data2.exists():
        return {'error': 'One or both pay periods have no data'}

    # Overall totals
    total1 = data1.aggregate(cost=Coalesce(Sum('total_cost'), Value(0)))['cost']
    total2 = data2.aggregate(cost=Coalesce(Sum('total_cost'), Value(0)))['cost']

    variance = float(total2) - float(total1)
    variance_pct = (variance / float(total1) * 100) if float(total1) > 0 else 0

    # Breakdown by dimension
    breakdown = []

    if breakdown_by == 'location':
        # Get cost allocation breakdown
        for snapshot in data2:
            if snapshot.cost_allocation:
                for loc, cost in snapshot.cost_allocation.items():
                    breakdown.append({
                        'category': loc,
                        'period_1': 0,  # Would need to aggregate from period_1
                        'period_2': cost,
                        'variance': cost
                    })

    return {
        'period_1': period_1,
        'period_2': period_2,
        'period_1_total': float(total1),
        'period_2_total': float(total2),
        'variance': variance,
        'variance_pct': round(variance_pct, 2),
        'employee_count_1': data1.count(),
        'employee_count_2': data2.count(),
        'breakdown': breakdown[:10]  # Limit to top 10
    }


def get_cost_breakdown(pay_period_id, dimension):
    """
    Get cost breakdown by various dimensions

    Args:
        pay_period_id (str): Pay period ID
        dimension (str): Dimension to break down by (location, employment_type, etc.)

    Returns:
        list: Cost breakdown data
    """
    try:
        pay_period = PayPeriod.objects.get(period_id=pay_period_id)
    except PayPeriod.DoesNotExist:
        return {'error': f'Pay period {pay_period_id} not found'}

    snapshots = EmployeePayPeriodSnapshot.objects.filter(pay_period=pay_period)

    if not snapshots.exists():
        return {'error': 'No data found'}

    # Aggregate by dimension
    breakdown = snapshots.values(dimension).annotate(
        total_cost=Sum('total_cost'),
        total_hours=Sum('total_hours'),
        employee_count=Count('employee_code')
    ).order_by('-total_cost')

    return list(breakdown)


def get_month_over_month(start_month=None, end_month=None, metric='total_cost'):
    """
    Compare costs/metrics month over month

    Args:
        start_month (str): Start month (YYYY-MM)
        end_month (str): End month (YYYY-MM)
        metric (str): Metric to track (total_cost, total_hours, employee_count)

    Returns:
        list: Month-by-month data with changes
    """
    # Get all pay periods
    periods = PayPeriod.objects.all().order_by('period_end')

    if start_month:
        periods = periods.filter(period_end__gte=f'{start_month}-01')
    if end_month:
        # Get last day of month
        end_date = datetime.strptime(f'{end_month}-01', '%Y-%m-%d')
        end_date = end_date.replace(day=28) + timedelta(days=4)
        end_date = end_date - timedelta(days=end_date.day)
        periods = periods.filter(period_end__lte=end_date)

    results = []
    prev_value = None

    for period in periods:
        snapshots = EmployeePayPeriodSnapshot.objects.filter(pay_period=period)

        if metric == 'total_cost':
            value = snapshots.aggregate(val=Coalesce(Sum('total_cost'), Value(0)))['val']
        elif metric == 'total_hours':
            value = snapshots.aggregate(val=Coalesce(Sum('total_hours'), Value(0)))['val']
        elif metric == 'employee_count':
            value = snapshots.count()
        else:
            value = 0

        change = None
        change_pct = None

        if prev_value is not None and prev_value > 0:
            change = float(value) - float(prev_value)
            change_pct = (change / float(prev_value)) * 100

        results.append({
            'period': period.period_id,
            'value': float(value),
            'change': change,
            'change_pct': round(change_pct, 2) if change_pct is not None else None
        })

        prev_value = value

    return results


def get_month_over_budget(month, budget_amount=None):
    """
    Compare actual costs to budget for a specific month

    Args:
        month (str): Month to analyze (YYYY-MM)
        budget_amount (float): Budget amount (if known)

    Returns:
        dict: Actual vs budget comparison
    """
    # Find pay periods in this month
    periods = PayPeriod.objects.filter(
        period_end__year=int(month.split('-')[0]),
        period_end__month=int(month.split('-')[1])
    )

    if not periods.exists():
        return {'error': f'No pay periods found for month {month}'}

    # Get total costs for the month
    total_actual = 0
    breakdown = []

    for period in periods:
        snapshots = EmployeePayPeriodSnapshot.objects.filter(pay_period=period)
        period_cost = snapshots.aggregate(cost=Coalesce(Sum('total_cost'), Value(0)))['cost']
        total_actual += float(period_cost)

        breakdown.append({
            'period': period.period_id,
            'actual': float(period_cost)
        })

    result = {
        'month': month,
        'actual': total_actual,
        'periods': breakdown
    }

    if budget_amount is not None:
        variance = total_actual - budget_amount
        variance_pct = (variance / budget_amount * 100) if budget_amount > 0 else 0

        result.update({
            'budget': budget_amount,
            'variance': variance,
            'variance_pct': round(variance_pct, 2),
            'over_under': 'over' if variance > 0 else 'under'
        })

    return result


def get_headcount_by_location():
    """
    Get current headcount broken down by location

    Returns:
        list: Headcount by location
    """
    return list(
        Employee.objects.filter(termination_date__isnull=True)
        .values('location')
        .annotate(
            total=Count('code'),
            salaried=Count('code', filter=Q(auto_pay='Yes')),
            hourly=Count('code', filter=Q(auto_pay='No'))
        )
        .order_by('-total')
    )


def get_reconciliation_status(pay_period_id):
    """
    Get reconciliation status for a pay period

    Args:
        pay_period_id (str): Pay period ID

    Returns:
        dict: Reconciliation status and variances
    """
    try:
        pay_period = PayPeriod.objects.get(period_id=pay_period_id)
    except PayPeriod.DoesNotExist:
        return {'error': f'Pay period {pay_period_id} not found'}

    recons = EmployeeReconciliation.objects.filter(pay_period=pay_period)

    if not recons.exists():
        return {'error': 'No reconciliation data found'}

    summary = recons.aggregate(
        total_employees=Count('employee_id'),
        hours_match=Count('employee_id', filter=Q(hours_match=True)),
        cost_match=Count('employee_id', filter=Q(cost_match=True)),
        has_issues=Count('employee_id', filter=Q(has_issues=True)),
        total_hours_variance=Sum('hours_variance'),
        total_cost_variance=Sum('cost_variance')
    )

    return {
        'pay_period': pay_period_id,
        'total_employees': summary['total_employees'],
        'hours_match_count': summary['hours_match'],
        'cost_match_count': summary['cost_match'],
        'issues_count': summary['has_issues'],
        'hours_match_pct': round(summary['hours_match'] / summary['total_employees'] * 100, 2) if summary['total_employees'] > 0 else 0,
        'cost_match_pct': round(summary['cost_match'] / summary['total_employees'] * 100, 2) if summary['total_employees'] > 0 else 0,
        'total_hours_variance': float(summary['total_hours_variance'] or 0),
        'total_cost_variance': float(summary['total_cost_variance'] or 0)
    }


# Tool definitions for Claude API
ANALYTICS_TOOLS = [
    {
        "name": "get_employee_statistics",
        "description": "Get employee statistics with optional filtering and grouping. Use this to answer questions about employee counts, percentages, demographics, etc. Can filter by location, employment type, or active status. Can group by any employee field.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filters": {
                    "type": "object",
                    "description": "Filters to apply",
                    "properties": {
                        "location": {"type": "string", "description": "Filter by location (case-insensitive partial match)"},
                        "employment_type": {"type": "string", "description": "Filter by employment type (case-insensitive partial match)"},
                        "auto_pay": {"type": "string", "description": "Filter by auto pay (Yes/No)"},
                        "is_active": {"type": "boolean", "description": "Filter by active status (true=active, false=terminated)"}
                    }
                },
                "group_by": {
                    "type": "string",
                    "description": "Field to group by (location, employment_type, etc.)",
                    "enum": ["location", "employment_type", "pay_point"]
                }
            }
        }
    },
    {
        "name": "get_payroll_summary",
        "description": "Get payroll summary for a specific pay period including total costs, hours, and employee count.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pay_period_id": {"type": "string", "description": "Pay period ID in YYYY-MM-DD format"}
            },
            "required": ["pay_period_id"]
        }
    },
    {
        "name": "compare_pay_periods",
        "description": "Compare two pay periods and calculate variances. Use this for period-over-period analysis and bridge charts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period_1": {"type": "string", "description": "First pay period ID (YYYY-MM-DD)"},
                "period_2": {"type": "string", "description": "Second pay period ID (YYYY-MM-DD)"},
                "breakdown_by": {"type": "string", "description": "How to break down variance", "enum": ["location", "employment_status"]}
            },
            "required": ["period_1", "period_2"]
        }
    },
    {
        "name": "get_cost_breakdown",
        "description": "Get cost breakdown by various dimensions (location, employment type, etc.) for a specific pay period.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pay_period_id": {"type": "string", "description": "Pay period ID (YYYY-MM-DD)"},
                "dimension": {"type": "string", "description": "Dimension to break down by", "enum": ["location", "employment_status"]}
            },
            "required": ["pay_period_id", "dimension"]
        }
    },
    {
        "name": "get_month_over_month",
        "description": "Get month-over-month cost/metric trends. Returns time series data with period-over-period changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_month": {"type": "string", "description": "Start month (YYYY-MM), optional"},
                "end_month": {"type": "string", "description": "End month (YYYY-MM), optional"},
                "metric": {"type": "string", "description": "Metric to track", "enum": ["total_cost", "total_hours", "employee_count"]}
            }
        }
    },
    {
        "name": "get_month_over_budget",
        "description": "Compare actual costs to budget for a specific month. Shows actual vs budget variance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "Month to analyze (YYYY-MM)"},
                "budget_amount": {"type": "number", "description": "Budget amount for the month (optional)"}
            },
            "required": ["month"]
        }
    },
    {
        "name": "get_headcount_by_location",
        "description": "Get current active headcount broken down by location with salaried/hourly split.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_reconciliation_status",
        "description": "Get reconciliation status for a pay period including match rates and variances.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pay_period_id": {"type": "string", "description": "Pay period ID (YYYY-MM-DD)"}
            },
            "required": ["pay_period_id"]
        }
    }
]


# Tool function mapping
TOOL_FUNCTIONS = {
    "get_employee_statistics": get_employee_statistics,
    "get_payroll_summary": get_payroll_summary,
    "compare_pay_periods": compare_pay_periods,
    "get_cost_breakdown": get_cost_breakdown,
    "get_month_over_month": get_month_over_month,
    "get_month_over_budget": get_month_over_budget,
    "get_headcount_by_location": get_headcount_by_location,
    "get_reconciliation_status": get_reconciliation_status
}
