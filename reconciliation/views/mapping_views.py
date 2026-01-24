"""
Location Mapping Verification Views
"""
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
import json
import csv
import os
from django.conf import settings

from reconciliation.models import (
    PayPeriod, LocationMapping, TandaTimesheet, Upload, CostAllocationRule,
    IQBDetail, SageLocation, SageDepartment, PayCompCodeMapping, FinalizedAllocation,
    EmployeePayPeriodSnapshot, JournalReconciliation, ReconciliationRun
)
from reconciliation.cost_allocation import CostAllocationEngine
from django.db.models import Sum, Count, Q, Max
from decimal import Decimal
import pandas as pd


def _load_transaction_types_for_costs():
    """
    Load transaction types from database that should be included in cost calculations
    Same logic as the reconciliation engine
    """
    try:
        from reconciliation.models import IQBTransactionType

        # Get active transaction types with include_in_costs=True
        costs_types = list(
            IQBTransactionType.objects.filter(
                is_active=True,
                include_in_costs=True
            ).values_list('transaction_type', flat=True)
        )
        return costs_types
    except Exception as e:
        # Fallback to default list if database can't be queried
        return [
            'Annual Leave', 'Auto Pay', 'Hours By Rate', 'Long Service Leave',
            'Non Standard Add Before', 'Other Leave', 'Sick Leave',
            'Standard Add Before', 'Super', 'Term ETP - Taxable (Code: O)',
            'Term Post 93 AL Gross', 'Term Post 93 LL Gross', 'Term Post 93 LSL Gross',
            'User Defined Leave',
        ]


def _load_employee_locations():
    """Load employee locations from master_employee_file.csv
    Returns dict of {employee_code: location}"""
    csv_path = os.path.join(settings.BASE_DIR, 'data', 'master_employee_file.csv')

    if not os.path.exists(csv_path):
        return {}

    employee_locations = {}
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get('Code', '').strip()
            location = row.get('Location', '').strip()
            if code and location:
                employee_locations[code] = location

    return employee_locations


def _auto_create_tanda_mappings(tanda_upload):
    """
    Automatically create Tanda location mappings based on master_employee_file.csv
    Maps Tanda location names to cost account codes using employee default accounts
    """
    from reconciliation.models import LocationMapping, TandaTimesheet, SageLocation, SageDepartment

    # Load master employee file to get default cost accounts by location
    csv_path = os.path.join(settings.BASE_DIR, 'data', 'master_employee_file.csv')
    if not os.path.exists(csv_path):
        return

    # Build location -> default cost account mapping from master file
    location_default_accounts = {}
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            location = row.get('Location', '').strip()
            default_account = row.get('Default Cost Account', '').strip()

            if location and default_account and location not in location_default_accounts:
                # Use the first employee's default account for this location
                location_default_accounts[location] = default_account

    # Get all unique Tanda location names from this upload
    tanda_locations = TandaTimesheet.objects.filter(
        upload=tanda_upload
    ).values_list('location_name', flat=True).distinct()

    # Get all existing mappings
    existing_mappings = set(LocationMapping.objects.filter(
        is_active=True
    ).values_list('tanda_location', flat=True))

    # Create missing mappings
    created_count = 0
    for tanda_location in tanda_locations:
        if not tanda_location or tanda_location in existing_mappings:
            continue

        # Find the default cost account for this location
        cost_account = location_default_accounts.get(tanda_location)

        if cost_account and '-' in cost_account:
            # Parse location and department from cost account
            parts = cost_account.split('-')
            location_id = parts[0]
            dept_id = parts[1][:2] if len(parts[1]) >= 2 else ''

            # Get location and department names
            sage_location = SageLocation.objects.filter(location_id=location_id).first()
            sage_dept = SageDepartment.objects.filter(department_id=dept_id).first()

            location_name = sage_location.location_name if sage_location else ''
            dept_name = sage_dept.department_name if sage_dept else ''

            # Create the mapping
            LocationMapping.objects.create(
                tanda_location=tanda_location,
                cost_account_code=cost_account,
                department_code=dept_id,
                department_name=dept_name,
                is_active=True
            )
            created_count += 1

    return created_count


def _expand_spl_allocations(allocation):
    """
    Expand SPL (split) accounts in allocation to their target accounts

    Args:
        allocation: dict of {cost_account: {'percentage': float, 'amount': float}}

    Returns:
        dict of {cost_account: {'percentage': float, 'amount': float}} with SPL accounts expanded
    """
    from reconciliation.models import CostCenterSplit
    from decimal import Decimal

    if not allocation:
        return {}

    expanded = {}

    # Get all SPL split rules
    split_rules = {}
    for split in CostCenterSplit.objects.all():
        if split.source_account not in split_rules:
            split_rules[split.source_account] = []
        split_rules[split.source_account].append({
            'target': split.target_account,
            'percentage': float(split.percentage)
        })

    # Process each allocation
    for cost_account, details in allocation.items():
        percentage = details.get('percentage', 0)
        amount = details.get('amount', 0)

        # Check if this is an SPL account
        if cost_account.startswith('SPL') and cost_account in split_rules:
            # Expand this SPL account to its targets
            for rule in split_rules[cost_account]:
                target_account = rule['target']
                split_pct = rule['percentage']

                # Calculate the percentage that goes to this target
                target_percentage = percentage * split_pct
                target_amount = amount * split_pct

                # Add to or update the target account
                if target_account in expanded:
                    expanded[target_account]['percentage'] += target_percentage
                    expanded[target_account]['amount'] += target_amount
                else:
                    expanded[target_account] = {
                        'percentage': target_percentage,
                        'amount': target_amount
                    }
        else:
            # Not an SPL account, keep as-is
            if cost_account in expanded:
                expanded[cost_account]['percentage'] += percentage
                expanded[cost_account]['amount'] += amount
            else:
                expanded[cost_account] = {
                    'percentage': percentage,
                    'amount': amount
                }

    return expanded


def verify_tanda_mapping(request, pay_period_id):
    """
    Verify Tanda location mappings and allow user to fix unmapped locations
    Only shows locations that have blank GLCode and no LocationMapping
    """
    pay_period = get_object_or_404(PayPeriod, period_id=pay_period_id)

    # Get Tanda upload
    tanda_upload = Upload.objects.filter(
        pay_period=pay_period,
        source_system='Tanda_Timesheet',
        is_active=True
    ).first()

    if not tanda_upload:
        return render(request, 'reconciliation/verify_mapping.html', {
            'pay_period': pay_period,
            'error': 'No Tanda timesheet data found for this period'
        })

    # Get all unique location-team combinations that have BLANK gl_code
    # (only these need mapping, since records with gl_code are already mapped)
    unmapped_data = TandaTimesheet.objects.filter(
        upload=tanda_upload
    ).filter(
        Q(gl_code__isnull=True) | Q(gl_code='')
    ).values('location_name', 'team_name').annotate(
        employee_count=Count('employee_id', distinct=True)
    ).order_by('location_name', 'team_name')

    # Get existing mappings
    existing_mappings = {
        m.tanda_location: m.cost_account_code
        for m in LocationMapping.objects.filter(is_active=True)
    }

    # Build unmapped locations list (only those without gl_code AND without mapping)
    unmapped_locations = []
    for item in unmapped_data:
        tanda_location = f"{item['location_name']} - {item['team_name']}"
        if tanda_location not in existing_mappings:
            unmapped_locations.append({
                'tanda_location': tanda_location,
                'employee_count': item['employee_count']
            })

    # Calculate total records with gl_code
    total_records = TandaTimesheet.objects.filter(upload=tanda_upload).count()
    records_with_glcode = TandaTimesheet.objects.filter(
        upload=tanda_upload
    ).exclude(
        Q(gl_code__isnull=True) | Q(gl_code='')
    ).count()

    mapped_count = records_with_glcode + len(existing_mappings)
    total_locations = TandaTimesheet.objects.filter(
        upload=tanda_upload
    ).values('location_name').distinct().count()

    return render(request, 'reconciliation/verify_mapping.html', {
        'pay_period': pay_period,
        'unmapped_locations': unmapped_locations,
        'unmapped_count': len(unmapped_locations),
        'mapped_count': total_locations - len(unmapped_locations),
        'total_locations': total_locations,
        'records_with_glcode': records_with_glcode,
        'mapped_pct': round((total_locations - len(unmapped_locations)) / total_locations * 100, 1) if total_locations > 0 else 0,
    })


@csrf_exempt
@require_http_methods(['POST'])
def save_location_mapping(request):
    """
    AJAX endpoint to save a new Tanda location mapping
    """
    try:
        data = json.loads(request.body)
        tanda_location = data.get('tanda_location')
        cost_account_code = data.get('cost_account_code')
        department_code = data.get('department_code')
        department_name = data.get('department_name')

        if not all([tanda_location, cost_account_code, department_code, department_name]):
            return JsonResponse({'error': 'Missing required fields'}, status=400)

        # Create or update mapping
        mapping, created = LocationMapping.objects.update_or_create(
            tanda_location=tanda_location,
            defaults={
                'cost_account_code': cost_account_code,
                'department_code': department_code,
                'department_name': department_name,
                'is_active': True
            }
        )

        return JsonResponse({
            'success': True,
            'created': created,
            'mapping': {
                'tanda_location': mapping.tanda_location,
                'cost_account_code': mapping.cost_account_code,
                'department_code': mapping.department_code,
                'department_name': mapping.department_name,
            }
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(['POST'])
def run_cost_allocation(request, pay_period_id):
    """
    Run cost allocation for both IQB and Tanda sources
    """
    try:
        pay_period = PayPeriod.objects.get(period_id=pay_period_id)
        engine = CostAllocationEngine(pay_period)

        # Run IQB allocation
        iqb_result = engine.build_allocations(source='iqb')

        # Run Tanda allocation
        tanda_result = engine.build_allocations(source='tanda')

        # Update pay period status
        pay_period.has_cost_allocation = True
        pay_period.save()

        return JsonResponse({
            'success': True,
            'iqb_result': iqb_result,
            'tanda_result': tanda_result
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def cost_allocation_view(request, pay_period_id):
    """
    Cost Allocation View - Complex view allowing users to:
    - Toggle between $ Value by GL and % Allocation by Cost Center
    - View IQB, Tanda, and Override allocations for each employee
    - Filter by Sage Location and Department
    - Override allocations with manual input
    """
    pay_period = get_object_or_404(PayPeriod, period_id=pay_period_id)

    # Get filter parameters
    location_filter = request.GET.get('location', '')
    department_filter = request.GET.get('department', '')
    tecc_filter = request.GET.get('tecc', '')  # TECC (Location 700) filter
    view_mode = request.GET.get('view', 'percentage')  # 'percentage' or 'dollar'

    # If switching to dollar view, return dollar view
    if view_mode == 'dollar':
        return _render_dollar_view(request, pay_period, location_filter, department_filter)

    # Default behavior: if no filters applied, show empty list (for performance)
    # User must select location/department to load data
    if not location_filter and not department_filter and not tecc_filter:
        # Get filter options
        locations = SageLocation.objects.all().order_by('location_id')
        departments = SageDepartment.objects.all().order_by('department_id')

        context = {
            'pay_period': pay_period,
            'employees': [],
            'gl_totals': {'items': [], 'grand_total': 0},
            'locations': locations,
            'departments': departments,
            'selected_location': location_filter,
            'selected_department': department_filter,
            'tecc_filter': tecc_filter,
            'view_mode': view_mode,
            'show_filter_message': True,
        }
        return render(request, 'reconciliation/cost_allocation_view.html', context)

    # Get all employees with allocation rules
    employees_data = []

    # Get IQB upload for cost calculations
    iqb_upload = Upload.objects.filter(
        pay_period=pay_period,
        source_system='Micropay_IQB',
        is_active=True
    ).first()

    if not iqb_upload:
        return render(request, 'reconciliation/cost_allocation_view.html', {
            'pay_period': pay_period,
            'error': 'No IQB data available for this pay period'
        })

    # Get Tanda upload for calculating Tanda allocations on-the-fly
    tanda_upload = Upload.objects.filter(
        pay_period=pay_period,
        source_system='Tanda_Timesheet',
        is_active=True
    ).first()

    # Auto-create Tanda location mappings if needed
    if tanda_upload:
        _auto_create_tanda_mappings(tanda_upload)

    # Get all allocation rules (indexed by employee_code for quick lookup)
    all_rules = {
        rule.employee_code: rule
        for rule in CostAllocationRule.objects.filter(pay_period=pay_period).select_related('pay_period')
    }

    # Get override rules separately
    override_rules = {
        rule.employee_code: rule
        for rule in CostAllocationRule.objects.filter(pay_period=pay_period, source='override')
    }

    # Load employee locations from master file
    employee_locations = _load_employee_locations()

    # Get list of transaction types to include (load from CSV like the reconciliation engine does)
    include_transaction_types = _load_transaction_types_for_costs()

    # Get ALL employees from IQB (like the dashboard does, not just those with allocation rules)
    all_employees = IQBDetail.objects.filter(
        upload=iqb_upload,
        transaction_type__in=include_transaction_types
    ).values('employee_code').annotate(
        employee_name=Max('full_name')
    ).order_by('employee_code')

    # Build employee data
    for emp in all_employees:
        emp_code = emp['employee_code']
        emp_name = emp['employee_name']

        # Get the allocation rule for this employee (if exists)
        rule = all_rules.get(emp_code)

        # Apply location/department filter if specified
        if location_filter or department_filter:
            # Check if employee has any cost account codes matching the filter
            if not _employee_matches_filter_by_cost_account(
                iqb_upload, emp_code, include_transaction_types, location_filter, department_filter
            ):
                continue

        # TECC filter: check if employee has location 700 in any source
        if tecc_filter:
            has_tecc = _employee_has_location_700(
                iqb_upload, emp_code, include_transaction_types,
                tanda_upload, override_rules.get(emp_code)
            )
            if not has_tecc:
                continue

        # Get total cost by pay_comp_code for this employee
        pay_comp_breakdown = IQBDetail.objects.filter(
            upload=iqb_upload,
            employee_code=emp_code,
            transaction_type__in=include_transaction_types
        ).values('pay_comp_code').annotate(
            total=Sum('amount')
        )

        # Calculate total cost
        total_cost = sum(item['total'] or 0 for item in pay_comp_breakdown)

        # Map to GL accounts
        gl_costs = _map_to_gl_accounts(pay_comp_breakdown)

        # Calculate IQB allocation on-the-fly from IQB data
        iqb_allocation = _calculate_iqb_allocation(iqb_upload, emp_code, include_transaction_types, total_cost)

        # Calculate Tanda allocation on-the-fly if Tanda upload exists
        tanda_allocation = None
        has_tanda = False
        if tanda_upload:
            tanda_allocation = _calculate_tanda_allocation(tanda_upload, emp_code, total_cost)
            has_tanda = tanda_allocation is not None and len(tanda_allocation) > 0

        # Get override (if exists)
        override_rule = override_rules.get(emp_code)

        # Determine current source from the rule (default to 'iqb' if no rule)
        current_source = rule.source if rule else 'iqb'

        # Get employee location from master file
        emp_location = employee_locations.get(emp_code, '')

        # Determine default source based on location (for Task 3)
        default_source = 'tanda' if emp_location in ['Culinary', 'Stewarding'] else 'iqb'

        # Get the current allocation based on the selected source
        # Use freshly calculated allocations instead of stale rule.allocations
        if current_source == 'iqb':
            current_allocation = iqb_allocation
        elif current_source == 'tanda':
            current_allocation = tanda_allocation if tanda_allocation else iqb_allocation
        elif current_source == 'override':
            current_allocation = override_rule.allocations if override_rule else iqb_allocation
        else:
            current_allocation = iqb_allocation

        # Calculate expanded allocation for override input pre-population
        # Expand any SPL accounts to show the actual target allocations
        expanded_allocation = _expand_spl_allocations(current_allocation) if current_allocation else {}

        employees_data.append({
            'employee_code': emp_code,
            'employee_name': emp_name,
            'employee_location': emp_location,
            'total_cost': float(total_cost),
            'gl_costs': gl_costs,
            'iqb_allocation': iqb_allocation,
            'tanda_allocation': tanda_allocation,
            'has_tanda': has_tanda,
            'override_allocation': override_rule.allocations if override_rule else None,
            'current_source': current_source,
            'current_allocation': current_allocation,
            'default_source': default_source,
            'expanded_allocation': expanded_allocation,
        })

    # Get GL totals from Journal Reconciliation (same as dashboard)
    gl_totals = _get_journal_gl_totals(pay_period)

    # Get filter options
    locations = SageLocation.objects.all().order_by('location_id')
    departments = SageDepartment.objects.all().order_by('department_id')

    context = {
        'pay_period': pay_period,
        'employees': employees_data,
        'gl_totals': gl_totals,
        'locations': locations,
        'departments': departments,
        'selected_location': location_filter,
        'selected_department': department_filter,
        'tecc_filter': tecc_filter,
        'view_mode': view_mode,
    }

    return render(request, 'reconciliation/cost_allocation_view.html', context)


def _map_to_gl_accounts(pay_comp_breakdown):
    """
    Map IQB pay_comp_code to GL accounts using PayCompCodeMapping
    Returns dict of {gl_account: amount}
    """
    # Load mapping from database
    pay_comp_mappings = {
        mapping.pay_comp_code: mapping.gl_account
        for mapping in PayCompCodeMapping.objects.all()
    }

    # Also check for normalized codes (strip leading zeros)
    normalized_mappings = {}
    for code, gl in pay_comp_mappings.items():
        if code.isdigit():
            normalized_mappings[code.lstrip('0') or '0'] = gl

    gl_costs = {}
    for item in pay_comp_breakdown:
        pay_comp_code = item['pay_comp_code']
        amount = item['total'] or 0

        # Try exact match first
        gl_account = pay_comp_mappings.get(pay_comp_code)

        # If not found and code is numeric, try normalized
        if not gl_account and pay_comp_code.isdigit():
            normalized_code = pay_comp_code.lstrip('0') or '0'
            gl_account = normalized_mappings.get(normalized_code)

        if gl_account:
            if gl_account in gl_costs:
                gl_costs[gl_account] += amount
            else:
                gl_costs[gl_account] = amount

    return gl_costs


def _calculate_iqb_allocation(iqb_upload, emp_code, include_transaction_types, total_cost):
    """
    Calculate allocation based on IQB cost account codes
    Returns dict of {cost_account: {percentage: float, amount: float}}
    """
    # Get cost accounts and their amounts for this employee
    cost_account_breakdown = IQBDetail.objects.filter(
        upload=iqb_upload,
        employee_code=emp_code,
        transaction_type__in=include_transaction_types
    ).values('cost_account_code').annotate(
        total=Sum('amount')
    )

    allocation = {}
    # Convert total_cost to float to avoid Decimal/float mix
    total_cost_float = float(total_cost) if total_cost else 0

    for item in cost_account_breakdown:
        cost_account = item['cost_account_code']
        amount = float(item['total'] or 0)

        if not cost_account or total_cost_float == 0:
            continue

        percentage = (amount / total_cost_float) * 100

        allocation[cost_account] = {
            'percentage': percentage,
            'amount': amount
        }

    return allocation


def _calculate_tanda_allocation(tanda_upload, emp_code, total_cost):
    """
    Calculate allocation based on Tanda timesheets using gl_code field
    Falls back to location mapping for backward compatibility
    Returns dict of {cost_account: {percentage: float, amount: float}}
    """
    # Get all Tanda records for this employee
    tanda_records = TandaTimesheet.objects.filter(
        upload=tanda_upload,
        employee_id=emp_code
    ).values('gl_code', 'location_name').annotate(
        total_hours=Sum('shift_hours')
    )

    if not tanda_records:
        return None

    # Get location mappings (for backward compatibility)
    location_mappings = {
        mapping.tanda_location: mapping.cost_account_code
        for mapping in LocationMapping.objects.filter(is_active=True)
    }

    # Calculate total hours
    total_hours = sum(float(item['total_hours'] or 0) for item in tanda_records)

    if total_hours == 0:
        return None

    # Convert total_cost to float to avoid Decimal/float mix
    total_cost_float = float(total_cost) if total_cost else 0

    allocation = {}
    for item in tanda_records:
        gl_code = item['gl_code']
        location = item['location_name']
        hours = float(item['total_hours'] or 0)

        # Use gl_code if available, otherwise fall back to location mapping
        if gl_code:
            cost_account = gl_code
        else:
            cost_account = location_mappings.get(location)
            if not cost_account:
                continue  # Skip only if no gl_code AND no location mapping

        percentage = (hours / total_hours) * 100
        amount = (percentage / 100) * total_cost_float

        if cost_account in allocation:
            allocation[cost_account]['percentage'] += percentage
            allocation[cost_account]['amount'] += amount
        else:
            allocation[cost_account] = {
                'percentage': percentage,
                'amount': amount
            }

    return allocation


def _employee_matches_filter_by_cost_account(iqb_upload, emp_code, include_transaction_types, location_filter, department_filter):
    """
    Check if employee has any cost account codes matching the location/department filter
    """
    # Get all cost accounts for this employee
    cost_accounts = IQBDetail.objects.filter(
        upload=iqb_upload,
        employee_code=emp_code,
        transaction_type__in=include_transaction_types
    ).values_list('cost_account_code', flat=True).distinct()

    for cost_account in cost_accounts:
        if not cost_account or '-' not in cost_account:
            continue

        parts = cost_account.split('-')
        location_code = parts[0]
        dept_code = parts[1][:2] if len(parts[1]) >= 2 else ''

        # Check if matches filter
        location_match = not location_filter or location_code == location_filter
        department_match = not department_filter or dept_code == department_filter

        if location_match and department_match:
            return True

    return False


def _employee_has_location_700(iqb_upload, emp_code, include_transaction_types, tanda_upload, override_rule):
    """
    Check if employee has location 700 in any source (IQB, Tanda, or Override)
    Used for TECC filtering
    """
    # Check IQB cost accounts for location 700
    if iqb_upload:
        iqb_has_700 = IQBDetail.objects.filter(
            upload=iqb_upload,
            employee_code=emp_code,
            transaction_type__in=include_transaction_types,
            cost_account_code__startswith='700-'
        ).exists()
        if iqb_has_700:
            return True

    # Check Tanda allocation for location 700
    if tanda_upload:
        from reconciliation.models import TandaTimesheet, LocationMapping
        tanda_entries = TandaTimesheet.objects.filter(
            upload=tanda_upload,
            employee_code=emp_code
        ).values_list('location', 'team_name').distinct()

        for location_name, team_name in tanda_entries:
            tanda_location = f"{location_name} - {team_name}"
            mapping = LocationMapping.objects.filter(tanda_location=tanda_location).first()
            if mapping and mapping.cost_account_code and mapping.cost_account_code.startswith('700-'):
                return True

    # Check Override allocation for location 700
    if override_rule and override_rule.allocations:
        for cost_account in override_rule.allocations.keys():
            if cost_account.startswith('700-') or cost_account == '700':
                return True

    return False


def _get_journal_gl_totals(pay_period):
    """
    Get GL totals from Journal Reconciliation (same as dashboard)
    This matches the Journal Entry Breakdown on the dashboard
    """
    # Get the latest completed reconciliation run
    recon_run = ReconciliationRun.objects.filter(
        pay_period=pay_period,
        status='completed'
    ).order_by('-completed_at').first()

    if not recon_run:
        return {
            'items': [],
            'grand_total': Decimal('0')
        }

    # Get journal items that are included in total cost (same as dashboard)
    journal_items = JournalReconciliation.objects.filter(
        recon_run=recon_run,
        include_in_total_cost=True
    ).order_by('gl_account')

    # Build result
    items = []
    grand_total = Decimal('0')

    for item in journal_items:
        amount = item.journal_net
        grand_total += amount
        items.append({
            'gl_account': item.gl_account,
            'gl_name': item.description,
            'total': amount
        })

    return {
        'items': items,
        'grand_total': grand_total
    }


def _calculate_gl_totals(iqb_upload):
    """
    Calculate total amount by GL account for verification
    """
    # Load transaction types from CSV (same as reconciliation engine)
    include_transaction_types = _load_transaction_types_for_costs()

    # Get all pay_comp_code totals
    pay_comp_totals = IQBDetail.objects.filter(
        upload=iqb_upload,
        transaction_type__in=include_transaction_types
    ).values('pay_comp_code').annotate(
        total=Sum('amount')
    )

    # Map to GL accounts
    gl_totals_dict = _map_to_gl_accounts(pay_comp_totals)

    # Get GL names
    gl_name_mapping = {
        mapping.gl_account: mapping.gl_name
        for mapping in PayCompCodeMapping.objects.all()
    }

    # Build result
    items = []
    grand_total = 0
    for gl_account in sorted(gl_totals_dict.keys()):
        amount = gl_totals_dict[gl_account]
        grand_total += amount
        items.append({
            'gl_account': gl_account,
            'gl_name': gl_name_mapping.get(gl_account, 'Other'),
            'total': amount
        })

    return {
        'items': items,
        'grand_total': grand_total
    }


def _render_dollar_view(request, pay_period, location_filter, department_filter):
    """
    Render the $ Value by GL view using saved finalized allocations
    Shows employees as rows, GL accounts as columns
    """
    # Default behavior: if no filters applied, show empty list (for performance)
    if not location_filter and not department_filter:
        locations = SageLocation.objects.all().order_by('location_id')
        departments = SageDepartment.objects.all().order_by('department_id')

        context = {
            'pay_period': pay_period,
            'employees': [],
            'gl_accounts': [],
            'locations': locations,
            'departments': departments,
            'selected_location': location_filter,
            'selected_department': department_filter,
            'view_mode': 'dollar',
            'show_filter_message': True,
        }
        return render(request, 'reconciliation/cost_allocation_dollar_view.html', context)

    # Get IQB upload
    iqb_upload = Upload.objects.filter(
        pay_period=pay_period,
        source_system='Micropay_IQB',
        is_active=True
    ).first()

    if not iqb_upload:
        return render(request, 'reconciliation/cost_allocation_dollar_view.html', {
            'pay_period': pay_period,
            'error': 'No IQB data available'
        })

    # Get Tanda upload
    tanda_upload = Upload.objects.filter(
        pay_period=pay_period,
        source_system='Tanda_Timesheet',
        is_active=True
    ).first()

    # Load employee locations from master file
    employee_locations = _load_employee_locations()

    # Get all allocation rules
    all_rules = CostAllocationRule.objects.filter(pay_period=pay_period)

    # Load transaction types from CSV (same as reconciliation engine)
    include_transaction_types = _load_transaction_types_for_costs()

    # Build employee data with GL breakdown
    employees_data = []
    gl_totals = {}  # Track totals for each GL account

    for rule in all_rules:
        emp_code = rule.employee_code

        # Apply location/department filter if specified
        if location_filter or department_filter:
            if not _employee_matches_filter_by_cost_account(
                iqb_upload, emp_code, include_transaction_types, location_filter, department_filter
            ):
                continue

        # Get employee's GL breakdown from IQB
        pay_comp_breakdown = IQBDetail.objects.filter(
            upload=iqb_upload,
            employee_code=emp_code,
            transaction_type__in=include_transaction_types
        ).values('pay_comp_code').annotate(
            total=Sum('amount')
        )

        # Map to GL accounts
        gl_costs = _map_to_gl_accounts(pay_comp_breakdown)

        # Calculate total cost
        total_cost = sum(gl_costs.values())

        # Get the appropriate allocation based on source
        if rule.source == 'iqb':
            allocation = _calculate_iqb_allocation(iqb_upload, emp_code, include_transaction_types, total_cost)
        elif rule.source == 'tanda' and tanda_upload:
            allocation = _calculate_tanda_allocation(tanda_upload, emp_code, total_cost)
        elif rule.source == 'override':
            allocation = rule.allocations
        else:
            allocation = _calculate_iqb_allocation(iqb_upload, emp_code, include_transaction_types, total_cost)

        if not allocation:
            continue

        # Calculate allocated GL amounts based on cost account allocation
        # Only include cost accounts that match the filter
        allocated_gl = {}
        total_percentage_shown = 0  # Track what % of employee's cost is shown in this view

        for cost_account, alloc_details in allocation.items():
            percentage = alloc_details.get('percentage', 0)

            # Check if this cost account matches the location/department filter
            if location_filter or department_filter:
                if not cost_account or '-' not in cost_account:
                    continue
                parts = cost_account.split('-')
                location_code = parts[0]
                dept_code = parts[1][:2] if len(parts[1]) >= 2 else ''

                # Skip this cost account if it doesn't match filter
                if location_filter and location_code != location_filter:
                    continue
                if department_filter and dept_code != department_filter:
                    continue

            # This cost account matches the filter, include its allocation
            total_percentage_shown += percentage

            # Allocate the percentage of each GL cost
            for gl_account, gl_amount in gl_costs.items():
                allocated_amount = float(gl_amount) * (percentage / 100)

                if gl_account in allocated_gl:
                    allocated_gl[gl_account] += allocated_amount
                else:
                    allocated_gl[gl_account] = allocated_amount

        # Add to GL totals
        for gl_account, amount in allocated_gl.items():
            if gl_account in gl_totals:
                gl_totals[gl_account] += amount
            else:
                gl_totals[gl_account] = amount

        # Get employee location from master file
        emp_location = employee_locations.get(emp_code, '')

        employees_data.append({
            'employee_code': emp_code,
            'employee_name': rule.employee_name,
            'employee_location': emp_location,
            'gl_amounts': allocated_gl,
            'total': sum(allocated_gl.values()),
            'source': rule.source,
        })

    # Get unique GL accounts sorted
    all_gl_accounts = sorted(set(gl_totals.keys()))

    # Get GL names
    gl_name_mapping = {
        mapping.gl_account: mapping.gl_name
        for mapping in PayCompCodeMapping.objects.all()
    }

    # Build GL columns info
    gl_columns = [
        {
            'account': gl_account,
            'name': gl_name_mapping.get(gl_account, 'Other')
        }
        for gl_account in all_gl_accounts
    ]

    # Get filter options
    locations = SageLocation.objects.all().order_by('location_id')
    departments = SageDepartment.objects.all().order_by('department_id')

    # Calculate grand total
    grand_total = sum(gl_totals.values())

    context = {
        'pay_period': pay_period,
        'view_mode': 'dollar',
        'employees': employees_data,
        'gl_columns': gl_columns,
        'gl_totals': gl_totals,
        'grand_total': grand_total,
        'locations': locations,
        'departments': departments,
        'selected_location': location_filter,
        'selected_department': department_filter,
    }

    return render(request, 'reconciliation/cost_allocation_dollar_view.html', context)


@csrf_exempt
@require_http_methods(['POST'])
def save_cost_allocations(request, pay_period_id):
    """
    Save cost allocations to EmployeePayPeriodSnapshot
    Groups allocations by employee + location + department
    """
    try:
        pay_period = PayPeriod.objects.get(period_id=pay_period_id)
        data = json.loads(request.body)
        changes = data.get('changes', [])

        if not changes:
            return JsonResponse({'error': 'No changes to save'}, status=400)

        # Get IQB upload for GL breakdown
        iqb_upload = Upload.objects.filter(
            pay_period=pay_period,
            source_system='Micropay_IQB',
            is_active=True
        ).first()

        if not iqb_upload:
            return JsonResponse({'error': 'No IQB data available'}, status=400)

        # Get location and department lookups
        location_lookup = {loc.location_id: loc.location_name for loc in SageLocation.objects.all()}
        department_lookup = {dept.department_id: dept.department_name for dept in SageDepartment.objects.all()}

        # Load transaction types from CSV (same as reconciliation engine)
        include_transaction_types = _load_transaction_types_for_costs()

        saved_count = 0

        # Process each employee in a transaction to prevent database locks
        with transaction.atomic():
            for change in changes:
                emp_code = change.get('employee_code')
                source = change.get('source')
                override_allocation = change.get('override', {})

                # Get employee name
                emp_name = CostAllocationRule.objects.filter(
                    pay_period=pay_period,
                    employee_code=emp_code
                ).first()
                if not emp_name:
                    continue
                emp_name = emp_name.employee_name

                # Get employee's GL breakdown
                pay_comp_breakdown = IQBDetail.objects.filter(
                    upload=iqb_upload,
                    employee_code=emp_code,
                    transaction_type__in=include_transaction_types
                ).values('pay_comp_code').annotate(
                    total=Sum('amount')
                )

                gl_costs = _map_to_gl_accounts(pay_comp_breakdown)
                total_cost = sum(gl_costs.values())

                # Get the allocation based on source
                if source == 'override':
                    allocation = override_allocation
                    # If override is empty, fall back to IQB but still save source as 'override'
                    # This allows the user to select Override first, then enter values later
                    if not allocation:
                        allocation = _calculate_iqb_allocation(iqb_upload, emp_code, include_transaction_types, total_cost)
                elif source == 'iqb':
                    allocation = _calculate_iqb_allocation(iqb_upload, emp_code, include_transaction_types, total_cost)
                elif source == 'tanda':
                    tanda_upload = Upload.objects.filter(
                        pay_period=pay_period,
                        source_system='Tanda_Timesheet',
                        is_active=True
                    ).first()
                    if tanda_upload:
                        allocation = _calculate_tanda_allocation(tanda_upload, emp_code, total_cost)
                    else:
                        allocation = _calculate_iqb_allocation(iqb_upload, emp_code, include_transaction_types, total_cost)
                else:
                    continue

                if not allocation:
                    continue

                # Expand SPL allocations
                expanded_allocation = _expand_spl_allocations(allocation)

                # Build cost_allocation JSON structure: { '449': { '50': 33.33, '30': 16.67 } }
                cost_allocation_json = {}

                for cost_account, details in expanded_allocation.items():
                    if not cost_account or '-' not in cost_account:
                        continue

                    # Parse location and department from cost account
                    parts = cost_account.split('-')
                    location_id = parts[0]
                    dept_id = parts[1][:2] if len(parts[1]) >= 2 else ''

                    if location_id not in cost_allocation_json:
                        cost_allocation_json[location_id] = {}

                    if dept_id not in cost_allocation_json[location_id]:
                        cost_allocation_json[location_id][dept_id] = 0

                    cost_allocation_json[location_id][dept_id] += float(details.get('percentage', 0))

                # Map GL accounts to model fields
                gl_field_mapping = {
                    # Payroll Liability Accounts (2xxx)
                    '2310': 'gl_2310_annual_leave',
                    '2317': 'gl_2317_long_service_leave',  # Actually TIL Provision, but field name kept
                    '2318': 'gl_2318_toil_liability',
                    '2320': 'gl_2320_sick_leave',  # Actually WorkCover, but field name kept
                    '2321': 'gl_2321_paid_parental',
                    '2325': 'gl_2325_leasing',
                    '2330': 'gl_2330_long_service_leave',
                    '2350': 'gl_2350_net_wages',
                    '2351': 'gl_2351_other_deductions',
                    '2360': 'gl_2360_payg_withholding',
                    '2391': 'gl_2391_super_sal_sacrifice',
                    # Labour Expense Accounts (6xxx)
                    '6302': 'gl_6302',
                    '6305': 'gl_6305',
                    '6309': 'gl_6309',
                    '6310': 'gl_6310',
                    '6312': 'gl_6312',
                    '6315': 'gl_6315',
                    '6325': 'gl_6325',
                    '6330': 'gl_6330',
                    '6331': 'gl_6331',
                    '6332': 'gl_6332',
                    '6335': 'gl_6335',
                    '6338': 'gl_6338',
                    '6340': 'gl_6340',
                    '6345': 'gl_6345_salaries',
                    '6350': 'gl_6350',
                    '6355': 'gl_6355_sick_leave',
                    '6370': 'gl_6370_superannuation',
                    '6372': 'gl_6372_toil',
                    '6375': 'gl_6375',
                    '6380': 'gl_6380',
                }

                # Build GL values
                gl_values = {}
                for gl_account, gl_amount in gl_costs.items():
                    if gl_account in gl_field_mapping:
                        gl_values[gl_field_mapping[gl_account]] = Decimal(str(gl_amount))

                # Delete existing snapshot for this employee/pay period
                EmployeePayPeriodSnapshot.objects.filter(
                    pay_period=pay_period,
                    employee_code=emp_code
                ).delete()

                # Create single snapshot for this employee
                EmployeePayPeriodSnapshot.objects.create(
                    pay_period=pay_period,
                    employee_code=emp_code,
                    employee_name=emp_name,
                    cost_allocation=cost_allocation_json,
                    allocation_source=source,
                    total_cost=Decimal(str(total_cost)),
                    **gl_values
                )

                # Update or create CostAllocationRule to persist the source selection
                CostAllocationRule.objects.update_or_create(
                    pay_period=pay_period,
                    employee_code=emp_code,
                    defaults={
                        'employee_name': emp_name,
                        'source': source,
                        'allocations': expanded_allocation
                    }
                )

                saved_count += 1

        return JsonResponse({
            'success': True,
            'message': f'Successfully saved {saved_count} allocation snapshots',
            'saved_count': saved_count
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(['POST'])
def save_all_allocations(request, pay_period_id):
    """
    Save cost allocations for ALL employees in the pay period
    Uses the source selection from CostAllocationRule
    """
    try:
        pay_period = PayPeriod.objects.get(period_id=pay_period_id)

        # Get IQB upload for GL breakdown
        iqb_upload = Upload.objects.filter(
            pay_period=pay_period,
            source_system='Micropay_IQB',
            is_active=True
        ).first()

        if not iqb_upload:
            return JsonResponse({'error': 'No IQB data available'}, status=400)

        # Get all employees with allocation rules for this pay period
        all_rules = CostAllocationRule.objects.filter(pay_period=pay_period)

        if not all_rules.exists():
            return JsonResponse({'error': 'No cost allocation rules found for this pay period'}, status=400)

        # Load transaction types from CSV (same as reconciliation engine)
        include_transaction_types = _load_transaction_types_for_costs()

        saved_count = 0

        # Process each employee using their source from CostAllocationRule in a transaction
        with transaction.atomic():
            for rule in all_rules:
                emp_code = rule.employee_code
                emp_name = rule.employee_name
                source = rule.source  # Get the source from the rule

                # Get employee's GL breakdown
                pay_comp_breakdown = IQBDetail.objects.filter(
                    upload=iqb_upload,
                    employee_code=emp_code,
                    transaction_type__in=include_transaction_types
                ).values('pay_comp_code').annotate(
                    total=Sum('amount')
                )

                gl_costs = _map_to_gl_accounts(pay_comp_breakdown)
                total_cost = sum(gl_costs.values())

                # Get the allocation based on source
                if source == 'override':
                    allocation = rule.allocations  # Use stored override allocation
                    # If override is empty, fall back to IQB but still save source as 'override'
                    if not allocation:
                        allocation = _calculate_iqb_allocation(iqb_upload, emp_code, include_transaction_types, total_cost)
                elif source == 'iqb':
                    allocation = _calculate_iqb_allocation(iqb_upload, emp_code, include_transaction_types, total_cost)
                elif source == 'tanda':
                    tanda_upload = Upload.objects.filter(
                        pay_period=pay_period,
                        source_system='Tanda_Timesheet',
                        is_active=True
                    ).first()
                    if tanda_upload:
                        allocation = _calculate_tanda_allocation(tanda_upload, emp_code, total_cost)
                    else:
                        allocation = _calculate_iqb_allocation(iqb_upload, emp_code, include_transaction_types, total_cost)
                else:
                    continue

                if not allocation:
                    continue

                # Expand SPL allocations
                expanded_allocation = _expand_spl_allocations(allocation)

                # Build cost_allocation JSON structure
                cost_allocation_json = {}

                for cost_account, details in expanded_allocation.items():
                    if not cost_account or '-' not in cost_account:
                        continue

                    # Parse location and department from cost account
                    parts = cost_account.split('-')
                    location_id = parts[0]
                    dept_id = parts[1][:2] if len(parts[1]) >= 2 else ''

                    if location_id not in cost_allocation_json:
                        cost_allocation_json[location_id] = {}

                    if dept_id not in cost_allocation_json[location_id]:
                        cost_allocation_json[location_id][dept_id] = 0

                    cost_allocation_json[location_id][dept_id] += float(details.get('percentage', 0))

                # Map GL accounts to model fields
                gl_field_mapping = {
                    # Payroll Liability Accounts (2xxx)
                    '2310': 'gl_2310_annual_leave',
                    '2317': 'gl_2317_long_service_leave',  # Actually TIL Provision, but field name kept
                    '2318': 'gl_2318_toil_liability',
                    '2320': 'gl_2320_sick_leave',  # Actually WorkCover, but field name kept
                    '2321': 'gl_2321_paid_parental',
                    '2325': 'gl_2325_leasing',
                    '2330': 'gl_2330_long_service_leave',
                    '2350': 'gl_2350_net_wages',
                    '2351': 'gl_2351_other_deductions',
                    '2360': 'gl_2360_payg_withholding',
                    '2391': 'gl_2391_super_sal_sacrifice',
                    # Labour Expense Accounts (6xxx)
                    '6302': 'gl_6302',
                    '6305': 'gl_6305',
                    '6309': 'gl_6309',
                    '6310': 'gl_6310',
                    '6312': 'gl_6312',
                    '6315': 'gl_6315',
                    '6325': 'gl_6325',
                    '6330': 'gl_6330',
                    '6331': 'gl_6331',
                    '6332': 'gl_6332',
                    '6335': 'gl_6335',
                    '6338': 'gl_6338',
                    '6340': 'gl_6340',
                    '6345': 'gl_6345_salaries',
                    '6350': 'gl_6350',
                    '6355': 'gl_6355_sick_leave',
                    '6370': 'gl_6370_superannuation',
                    '6372': 'gl_6372_toil',
                    '6375': 'gl_6375',
                    '6380': 'gl_6380',
                }

                # Build GL values
                gl_values = {}
                for gl_account, gl_amount in gl_costs.items():
                    if gl_account in gl_field_mapping:
                        gl_values[gl_field_mapping[gl_account]] = Decimal(str(gl_amount))

                # Delete existing snapshot for this employee/pay period
                EmployeePayPeriodSnapshot.objects.filter(
                    pay_period=pay_period,
                    employee_code=emp_code
                ).delete()

                # Create single snapshot for this employee
                EmployeePayPeriodSnapshot.objects.create(
                    pay_period=pay_period,
                    employee_code=emp_code,
                    employee_name=emp_name,
                    cost_allocation=cost_allocation_json,
                    allocation_source=source,
                    total_cost=Decimal(str(total_cost)),
                    **gl_values
                )

                saved_count += 1

        return JsonResponse({
            'success': True,
            'message': f'Successfully saved {saved_count} allocation snapshots',
            'saved_count': saved_count
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(['POST'])
def apply_bulk_source(request, pay_period_id):
    """
    Apply a bulk source selection to ALL employees in the pay period
    This updates the CostAllocationRule.source field for all employees
    """
    try:
        pay_period = PayPeriod.objects.get(period_id=pay_period_id)
        data = json.loads(request.body)
        source = data.get('source')

        if not source or source not in ['iqb', 'tanda', 'override']:
            return JsonResponse({'error': 'Invalid source specified'}, status=400)

        # Get all cost allocation rules for this pay period
        all_rules = CostAllocationRule.objects.filter(pay_period=pay_period)

        if not all_rules.exists():
            return JsonResponse({'error': 'No cost allocation rules found for this pay period'}, status=400)

        # Update all rules with the new source
        updated_count = 0

        with transaction.atomic():
            for rule in all_rules:
                # Skip Tanda if employee doesn't have Tanda data
                if source == 'tanda':
                    # Check if employee has Tanda data
                    tanda_upload = Upload.objects.filter(
                        pay_period=pay_period,
                        source_system='Tanda_Timesheet',
                        is_active=True
                    ).first()

                    if tanda_upload:
                        has_tanda = TandaTimesheet.objects.filter(
                            upload=tanda_upload,
                            employee_id=rule.employee_code
                        ).exists()

                        if not has_tanda:
                            # Skip this employee, no Tanda data
                            continue

                # Update the source
                rule.source = source
                rule.save()
                updated_count += 1

        return JsonResponse({
            'success': True,
            'message': f'Applied {source} to {updated_count} employees',
            'updated_count': updated_count
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)
