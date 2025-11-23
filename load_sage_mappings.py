"""
Load Sage Location and Department mappings from CSV files

Run with: python load_sage_mappings.py
"""
import os
import django
import csv

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import SageLocation, SageDepartment, PayCompCodeMapping


def load_sage_locations():
    """Load Sage Location data from CSV"""
    csv_path = 'data/Sage Location.csv'

    print(f"Loading Sage Locations from {csv_path}...")

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        count = 0

        for row in reader:
            location_id = row['Location ID'].strip()
            if not location_id:
                continue

            SageLocation.objects.update_or_create(
                location_id=location_id,
                defaults={
                    'location_name': row['Location name'].strip(),
                    'parent_id': row.get('Parent ID', '').strip(),
                    'parent_name': row.get('Parent - Name', '').strip(),
                    'manager': row.get('Manager', '').strip(),
                    'parent_entity': row.get('Parent entity', '').strip(),
                    'entity_base_currency': row.get('Entity base currency', 'AUD').strip(),
                }
            )
            count += 1

    print(f"Loaded {count} Sage Locations")
    return count


def load_sage_departments():
    """Load Sage Department data from CSV"""
    csv_path = 'data/Sage Department.csv'

    print(f"Loading Sage Departments from {csv_path}...")

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        count = 0

        for row in reader:
            department_id = row['Department ID'].strip()
            if not department_id:
                continue

            SageDepartment.objects.update_or_create(
                department_id=department_id,
                defaults={
                    'department_name': row['Department name'].strip(),
                    'parent_id': row.get('Parent ID', '').strip(),
                    'parent_name': row.get('Parent - Name', '').strip(),
                    'manager': row.get('Manager', '').strip(),
                }
            )
            count += 1

    print(f"Loaded {count} Sage Departments")
    return count


def load_pay_comp_code_mapping():
    """Load Pay Comp Code to GL Account mapping from CSV"""
    csv_path = 'data/PayCompCode Mapping.csv'

    print(f"Loading Pay Comp Code Mappings from {csv_path}...")

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        count = 0

        for row in reader:
            pay_comp_code = row['Pay Comp/Add Ded Code'].strip()
            if not pay_comp_code:
                continue

            PayCompCodeMapping.objects.update_or_create(
                pay_comp_code=pay_comp_code,
                defaults={
                    'gl_account': row['GL Account'].strip(),
                    'gl_name': row['GL Name'].strip(),
                }
            )
            count += 1

    print(f"Loaded {count} Pay Comp Code Mappings")
    return count


if __name__ == '__main__':
    print("=" * 60)
    print("Loading Sage Master Data")
    print("=" * 60)

    # Clear existing data
    print("\nClearing existing data...")
    SageLocation.objects.all().delete()
    SageDepartment.objects.all().delete()
    PayCompCodeMapping.objects.all().delete()

    # Load new data
    locations = load_sage_locations()
    departments = load_sage_departments()
    pay_comp_codes = load_pay_comp_code_mapping()

    print("\n" + "=" * 60)
    print(f"COMPLETE: Loaded {locations} locations, {departments} departments, and {pay_comp_codes} pay comp code mappings")
    print("=" * 60)
