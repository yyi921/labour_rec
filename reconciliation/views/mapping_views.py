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

from reconciliation.models import PayPeriod, LocationMapping, TandaTimesheet, Upload
from reconciliation.cost_allocation import CostAllocationEngine


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
    Cost Allocation View - Placeholder for detailed allocation view
    Will be implemented based on user requirements
    """
    pay_period = get_object_or_404(PayPeriod, period_id=pay_period_id)

    # TODO: Implement detailed cost allocation view
    # This will show allocation details, comparisons, etc.

    context = {
        'pay_period': pay_period,
        'message': 'Cost Allocation View - To be implemented based on your requirements'
    }

    return render(request, 'reconciliation/cost_allocation_view.html', context)
