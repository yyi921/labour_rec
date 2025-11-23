"""
Location Mapping Verification Views
"""
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
import json
import csv
import os
from django.conf import settings

from reconciliation.models import (
    PayPeriod, LocationMapping, TandaTimesheet, Upload, CostAllocationRule,
    IQBDetail, SageLocation, SageDepartment, PayCompCodeMapping, FinalizedAllocation
)
from reconciliation.cost_allocation import CostAllocationEngine
from django.db.models import Sum, Count, Q
from decimal import Decimal


def verify_tanda_mapping(request, pay_period_id):
    """
    Verify Tanda location mappings and allow user to fix unmapped locations
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
            'error': 'No Tanda timesheet data found for this pay period'
        })

    # Get all unique location/team combinations from Tanda
    tanda_locations = TandaTimesheet.objects.filter(
        upload=tanda_upload
    ).values('location_name', 'team_name').distinct()

    # Check mapping status for each
    mapping_status = []
    unmapped_locations = []

    for loc in tanda_locations:
        location_name = loc['location_name']
        team_name = loc['team_name']
        tanda_location = f"{location_name} - {team_name}"

        # Check if mapping exists
        try:
            mapping = LocationMapping.objects.get(
                tanda_location=tanda_location,
                is_active=True
            )
            mapping_status.append({
                'tanda_location': tanda_location,
                'location_name': location_name,
                'team_name': team_name,
                'cost_account_code': mapping.cost_account_code,
                'department_name': mapping.department_name,
                'is_mapped': True
            })
        except LocationMapping.DoesNotExist:
            # Find employee count for this location
            employee_count = TandaTimesheet.objects.filter(
                upload=tanda_upload,
                location_name=location_name,
                team_name=team_name
            ).values('employee_id').distinct().count()

            unmapped_locations.append({
                'tanda_location': tanda_location,
                'location_name': location_name,
                'team_name': team_name,
                'cost_account_code': '',
                'department_name': '',
                'is_mapped': False,
                'employee_count': employee_count
            })

    total_locations = len(mapping_status) + len(unmapped_locations)
    mapped_count = len(mapping_status)
    mapped_pct = (mapped_count / total_locations * 100) if total_locations > 0 else 0

    context = {
        'pay_period': pay_period,
        'total_locations': total_locations,
        'mapped_count': mapped_count,
        'mapped_pct': round(mapped_pct, 1),
        'unmapped_count': len(unmapped_locations),
        'unmapped_locations': unmapped_locations,
        'mapping_status': mapping_status[:20],  # Show first 20 for reference
    }

    return render(request, 'reconciliation/verify_mapping.html', context)


@csrf_exempt
@require_http_methods(["POST"])
def save_location_mappings(request, pay_period_id):
    """
    Save new location mappings and update CSV file
    """
    try:
        data = json.loads(request.body)
        mappings = data.get('mappings', [])

        if not mappings:
            return JsonResponse({'error': 'No mappings provided'}, status=400)

        # Validate mappings
        for mapping in mappings:
            if not mapping.get('tanda_location') or not mapping.get('cost_account_code'):
                return JsonResponse({'error': 'Invalid mapping data'}, status=400)

        # Add to database
        created_count = 0
        for mapping in mappings:
            location_name, team_name = mapping['tanda_location'].split(' - ', 1)

            # Extract department info from cost account
            cost_account = mapping['cost_account_code']
            if '-' in cost_account:
                dept_code = cost_account.split('-')[0][-2:]  # Last 2 digits
            else:
                dept_code = '00'

            dept_names = {
                '10': 'Administration', '20': 'Marketing', '30': 'Beverage',
                '40': 'Entertainment', '50': 'Food', '60': 'Gaming',
                '70': 'Accommodation', '80': 'Security', '90': 'Other', '00': 'Other'
            }
            dept_name = dept_names.get(dept_code, 'Other')

            # Create or update LocationMapping
            obj, created = LocationMapping.objects.update_or_create(
                tanda_location=mapping['tanda_location'],
                defaults={
                    'cost_account_code': cost_account,
                    'department_code': dept_code,
                    'department_name': dept_name,
                    'is_active': True
                }
            )
            if created:
                created_count += 1

        # Update CSV file
        csv_path = os.path.join(settings.BASE_DIR, 'data', 'location_and_team_report.csv')

        # Read existing CSV
        existing_data = []
        headers = []
        if os.path.exists(csv_path):
            with open(csv_path, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames
                existing_data = list(reader)

        # Add new mappings to CSV
        for mapping in mappings:
            location_name, team_name = mapping['tanda_location'].split(' - ', 1)

            # Check if already exists
            exists = any(
                row.get('Location Name') == location_name and
                row.get('Team Name') == team_name
                for row in existing_data
            )

            if not exists:
                existing_data.append({
                    'Location Name': location_name,
                    'Team Name': team_name,
                    'Cost Centre': mapping['cost_account_code'],
                    'Location Code': '',
                    'Location Address': '',
                    'Public Holiday region': '',
                    'Mobile login radius': '',
                    'Timezone': 'Australia/Brisbane'
                })

        # Write back to CSV
        if headers:
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(existing_data)

        # Re-run cost allocation
        pay_period = PayPeriod.objects.get(period_id=pay_period_id)
        engine = CostAllocationEngine(pay_period)
        result = engine.build_allocations(source='tanda')

        return JsonResponse({
            'success': True,
            'created_count': created_count,
            'updated_count': len(mappings) - created_count,
            'allocation_result': {
                'rules_created': result['rules_created'],
                'valid_rules': result['valid_rules'],
                'invalid_rules': result['invalid_rules'],
                'unmapped_count': len(result.get('mapping_errors', []))
            }
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
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
    view_mode = request.GET.get('view', 'percentage')  # 'percentage' or 'dollar'

    # If switching to dollar view, return dollar view
    if view_mode == 'dollar':
        return _render_dollar_view(request, pay_period, location_filter, department_filter)

    # Get all employees with allocation rules
    employees_data = []

    # Get all allocation rules (each employee has ONE rule with their current source)
    all_rules = CostAllocationRule.objects.filter(
        pay_period=pay_period
    ).select_related('pay_period')

    # Get override rules separately
    override_rules = {
        rule.employee_code: rule
        for rule in CostAllocationRule.objects.filter(pay_period=pay_period, source='override')
    }

    # Get Tanda upload for calculating Tanda allocations on-the-fly
    tanda_upload = Upload.objects.filter(
        pay_period=pay_period,
        source_system='Tanda_Timesheet',
        is_active=True
    ).first()

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

    # Build employee data
    for rule in all_rules:
        emp_code = rule.employee_code

        # Get list of transaction types to include
        include_transaction_types = [
            'Annual Leave', 'Auto Pay', 'Hours By Rate', 'Long Service Leave',
            'Non Standard Add Before', 'Other Leave', 'Sick Leave',
            'Standard Add Before', 'Super', 'Term ETP - Taxable (Code: O)',
            'Term Post 93 AL Gross', 'Term Post 93 LL Gross', 'User Defined Leave',
        ]

        # Apply location/department filter if specified
        if location_filter or department_filter:
            # Check if employee has any cost account codes matching the filter
            if not _employee_matches_filter_by_cost_account(
                iqb_upload, emp_code, include_transaction_types, location_filter, department_filter
            ):
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

        # Determine current source from the rule
        current_source = rule.source
        current_allocation = rule.allocations

        employees_data.append({
            'employee_code': emp_code,
            'employee_name': rule.employee_name,
            'total_cost': float(total_cost),
            'gl_costs': gl_costs,
            'iqb_allocation': iqb_allocation,
            'tanda_allocation': tanda_allocation,
            'has_tanda': has_tanda,
            'override_allocation': override_rule.allocations if override_rule else None,
            'current_source': current_source,
            'current_allocation': current_allocation,
        })

    # Calculate GL totals for verification
    gl_totals = _calculate_gl_totals(iqb_upload)

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

    gl_costs = {}
    for item in pay_comp_breakdown:
        pay_comp_code = item['pay_comp_code']
        amount = item['total'] or 0

        # Map pay_comp_code to GL account
        gl_account = pay_comp_mappings.get(pay_comp_code, '6345')  # Default to 6345
        gl_costs[gl_account] = gl_costs.get(gl_account, 0) + float(amount)

    return gl_costs


def _employee_matches_filter_by_cost_account(iqb_upload, emp_code, include_transaction_types, location_filter, department_filter):
    """
    Check if employee has any IQB cost account codes matching the location/department filter
    Cost account format: "421-5000" where:
    - 421 = Sage Location ID
    - 50 = Sage Department ID (first 2 digits of 5000)
    """
    # Get all cost account codes for this employee from IQB
    cost_accounts = IQBDetail.objects.filter(
        upload=iqb_upload,
        employee_code=emp_code,
        transaction_type__in=include_transaction_types
    ).values_list('cost_account_code', flat=True).distinct()

    for cost_account in cost_accounts:
        if not cost_account or '-' not in cost_account:
            continue

        parts = cost_account.split('-')
        if len(parts) != 2:
            continue

        location_code = parts[0]  # "421"
        dept_code = parts[1][:2] if len(parts[1]) >= 2 else ''  # "50" from "5000"

        # Check location filter
        if location_filter and location_code != location_filter:
            continue

        # Check department filter
        if department_filter and dept_code != department_filter:
            continue

        # If we get here, employee matches the filter
        return True

    return False


def _calculate_iqb_allocation(iqb_upload, emp_code, include_transaction_types, total_cost):
    """
    Calculate IQB allocation for an employee based on cost account codes
    Returns dict in same format as stored allocations
    Logic: Amount assigned to that cost account code / total amount for employee
    """
    # Get all IQB details for this employee
    iqb_details = IQBDetail.objects.filter(
        upload=iqb_upload,
        employee_code=emp_code,
        transaction_type__in=include_transaction_types
    ).values('cost_account_code').annotate(
        total_amount=Sum('amount')
    )

    if not iqb_details:
        return {}

    # Calculate total
    grand_total = float(sum(item['total_amount'] or 0 for item in iqb_details))
    if grand_total == 0:
        return {}

    # Build allocation dict
    allocations = {}

    for item in iqb_details:
        cost_account = item['cost_account_code']
        amount = float(item['total_amount'] or 0)

        if not cost_account:
            continue

        percentage = (amount / grand_total) * 100 if grand_total > 0 else 0

        allocations[cost_account] = {
            'percentage': round(percentage, 2),
            'amount': amount,
            'source': 'iqb'
        }

    return allocations


def _calculate_tanda_allocation(tanda_upload, emp_code, total_cost):
    """
    Calculate Tanda allocation for an employee based on timesheet hours/costs
    Returns dict in same format as stored allocations
    """
    from reconciliation.models import TandaTimesheet, LocationMapping

    # Get employee's Tanda data
    tanda_data = TandaTimesheet.objects.filter(
        upload=tanda_upload,
        employee_id=emp_code
    ).values('location_name', 'team_name').annotate(
        total_hours=Sum('shift_hours'),
        total_cost=Sum('shift_cost')
    )

    if not tanda_data:
        return None

    # Calculate total (convert to float to avoid Decimal issues)
    grand_total_cost = float(sum(item['total_cost'] or 0 for item in tanda_data))
    if grand_total_cost == 0:
        return None

    # Build allocation dict
    allocations = {}
    unmapped_found = False

    for item in tanda_data:
        location_name = item['location_name']
        team_name = item['team_name']
        cost = float(item['total_cost'] or 0)

        # Combine location and team to match LocationMapping format
        tanda_location = f"{location_name} - {team_name}"

        # Look up cost account
        try:
            mapping = LocationMapping.objects.get(tanda_location=tanda_location)
            cost_account = mapping.cost_account_code

            percentage = (cost / grand_total_cost) * 100 if grand_total_cost > 0 else 0
            amount = float(total_cost) * (percentage / 100)

            if cost_account in allocations:
                allocations[cost_account]['percentage'] += percentage
                allocations[cost_account]['amount'] += amount
            else:
                allocations[cost_account] = {
                    'percentage': round(percentage, 2),
                    'amount': float(amount),
                    'hours': float(item['total_hours'] or 0),
                    'source': 'tanda'
                }
        except LocationMapping.DoesNotExist:
            unmapped_found = True
            continue

    if unmapped_found or not allocations:
        return None

    # Round percentages
    for cost_account in allocations:
        allocations[cost_account]['percentage'] = round(allocations[cost_account]['percentage'], 2)

    return allocations


def _calculate_gl_totals(iqb_upload):
    """
    Calculate total by GL account across all employees
    Should match IQB Grand Total from dashboard
    Uses pay_comp_code from IQB and maps to GL accounts
    Only includes transactions where transaction_type has "Include in Costs" = "Yes"
    """
    # Get list of transaction types to include (from iqb_transaction_types.csv)
    include_transaction_types = [
        'Annual Leave',
        'Auto Pay',
        'Hours By Rate',
        'Long Service Leave',
        'Non Standard Add Before',
        'Other Leave',
        'Sick Leave',
        'Standard Add Before',
        'Super',
        'Term ETP - Taxable (Code: O)',
        'Term Post 93 AL Gross',
        'Term Post 93 LL Gross',
        'User Defined Leave',
    ]

    # Get totals by pay_comp_code for included transaction types
    pay_comp_breakdown = IQBDetail.objects.filter(
        upload=iqb_upload,
        transaction_type__in=include_transaction_types
    ).values('pay_comp_code').annotate(
        total=Sum('amount')
    )

    # Map to GL accounts
    gl_costs = _map_to_gl_accounts(pay_comp_breakdown)

    # Get GL names from mapping
    gl_name_mapping = {
        mapping.gl_account: mapping.gl_name
        for mapping in PayCompCodeMapping.objects.all()
    }

    gl_totals = []
    grand_total = 0

    for gl_account, amount in sorted(gl_costs.items()):
        # Get the first GL name for this account (there may be duplicates)
        gl_name = gl_name_mapping.get(gl_account, 'Other')

        gl_totals.append({
            'gl_account': gl_account,
            'gl_name': gl_name,
            'total': amount
        })
        grand_total += amount

    return {
        'items': gl_totals,
        'grand_total': grand_total
    }


def _calculate_and_save_finalized_allocations(pay_period):
    """
    Calculate finalized allocations based on current source selections
    and save to FinalizedAllocation model for journal generation
    """
    # Clear existing finalized allocations
    FinalizedAllocation.objects.filter(pay_period=pay_period).delete()

    # Get IQB upload
    iqb_upload = Upload.objects.filter(
        pay_period=pay_period,
        source_system='Micropay_IQB',
        is_active=True
    ).first()

    if not iqb_upload:
        return

    # Get Tanda upload
    tanda_upload = Upload.objects.filter(
        pay_period=pay_period,
        source_system='Tanda_Timesheet',
        is_active=True
    ).first()

    # Get all allocation rules
    all_rules = CostAllocationRule.objects.filter(pay_period=pay_period)

    # Transaction types to include
    include_transaction_types = [
        'Annual Leave', 'Auto Pay', 'Hours By Rate', 'Long Service Leave',
        'Non Standard Add Before', 'Other Leave', 'Sick Leave',
        'Standard Add Before', 'Super', 'Term ETP - Taxable (Code: O)',
        'Term Post 93 AL Gross', 'Term Post 93 LL Gross', 'User Defined Leave',
    ]

    # Track allocations by cost_account + GL
    allocations_dict = {}  # Key: (cost_account, gl_account), Value: {amount, employee_count}

    # Process each employee
    for rule in all_rules:
        emp_code = rule.employee_code

        # Get employee's GL breakdown
        pay_comp_breakdown = IQBDetail.objects.filter(
            upload=iqb_upload,
            employee_code=emp_code,
            transaction_type__in=include_transaction_types
        ).values('pay_comp_code').annotate(
            total=Sum('amount')
        )

        # Map to GL accounts
        gl_costs = _map_to_gl_accounts(pay_comp_breakdown)

        # Get employee's total cost
        total_cost = sum(item['total'] or 0 for item in pay_comp_breakdown)

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

        # For each cost account in the allocation
        for cost_account, alloc_details in allocation.items():
            percentage = alloc_details.get('percentage', 0)

            # Distribute each GL cost across cost accounts based on allocation percentage
            for gl_account, gl_amount in gl_costs.items():
                allocated_amount = gl_amount * (percentage / 100)

                key = (cost_account, gl_account)
                if key in allocations_dict:
                    allocations_dict[key]['amount'] += allocated_amount
                    allocations_dict[key]['employee_count'] += 1
                else:
                    allocations_dict[key] = {
                        'amount': allocated_amount,
                        'employee_count': 1
                    }

    # Save to database
    from reconciliation.models import SageLocation, SageDepartment

    # Get location and department lookups
    locations = {loc.location_id: loc.location_name for loc in SageLocation.objects.all()}
    departments = {dept.department_id: dept.department_name for dept in SageDepartment.objects.all()}

    # Get GL names
    gl_name_mapping = {
        mapping.gl_account: mapping.gl_name
        for mapping in PayCompCodeMapping.objects.all()
    }

    for (cost_account, gl_account), data in allocations_dict.items():
        if '-' not in cost_account:
            continue

        parts = cost_account.split('-')
        if len(parts) != 2:
            continue

        location_id = parts[0]
        department_id = parts[1][:2] if len(parts[1]) >= 2 else ''

        FinalizedAllocation.objects.create(
            pay_period=pay_period,
            location_id=location_id,
            location_name=locations.get(location_id, f'Location {location_id}'),
            department_id=department_id,
            department_name=departments.get(department_id, f'Department {department_id}'),
            cost_account_code=cost_account,
            gl_account=gl_account,
            gl_name=gl_name_mapping.get(gl_account, 'Other'),
            amount=Decimal(str(data['amount'])),
            employee_count=data['employee_count']
        )


def _render_dollar_view(request, pay_period, location_filter, department_filter):
    """
    Render the $ Value by GL view using saved finalized allocations
    Shows employees as rows, GL accounts as columns
    """
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

    # Get all allocation rules
    all_rules = CostAllocationRule.objects.filter(pay_period=pay_period)

    # Transaction types to include
    include_transaction_types = [
        'Annual Leave', 'Auto Pay', 'Hours By Rate', 'Long Service Leave',
        'Non Standard Add Before', 'Other Leave', 'Sick Leave',
        'Standard Add Before', 'Super', 'Term ETP - Taxable (Code: O)',
        'Term Post 93 AL Gross', 'Term Post 93 LL Gross', 'User Defined Leave',
    ]

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
                allocated_amount = gl_amount * (percentage / 100)

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

        employees_data.append({
            'employee_code': emp_code,
            'employee_name': rule.employee_name,
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
