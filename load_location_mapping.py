"""
Load location and team mappings from CSV into LocationMapping model
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import LocationMapping
import pandas as pd

# Read the CSV file
csv_path = os.path.join('data', 'location_and_team_report.csv')
df = pd.read_csv(csv_path)

print(f"Loading {len(df)} location/team mappings from {csv_path}")
print()

# Clear existing mappings
deleted_count = LocationMapping.objects.all().delete()[0]
print(f"Deleted {deleted_count} existing location mappings")
print()

# Extract department code and name from cost centre
def extract_department_info(cost_centre):
    """
    Extract department code from cost centre
    Examples: 
    - '470-6800' -> department '70' (Accommodation)
    - '910-9100' -> department '10' (Administration)
    """
    if pd.isna(cost_centre) or not cost_centre:
        return None, None
    
    parts = str(cost_centre).split('-')
    if len(parts) == 2:
        # Get the last digit of the first part (e.g., '470' -> '70', '910' -> '10')
        dept_code = parts[0][-2:]  # Last 2 digits
        
        # Map to department names (you can customize this)
        dept_names = {
            '10': 'Administration',
            '20': 'Marketing',
            '30': 'Beverage',
            '40': 'Entertainment',
            '50': 'Food',
            '60': 'Gaming',
            '70': 'Accommodation',
            '80': 'Security',
            '90': 'Other',
        }
        
        dept_name = dept_names.get(dept_code, 'Other')
        return dept_code, dept_name
    
    return None, None

# Create location mappings
# Strategy: Create a mapping for each unique Location Name + Team Name combination
mappings = []
seen_combinations = set()

for _, row in df.iterrows():
    location_name = str(row.get('Location Name', '')).strip()
    team_name = str(row.get('Team Name', '')).strip()
    cost_centre = str(row.get('Cost Centre', '')).strip()
    
    if not location_name or not team_name or not cost_centre:
        continue
    
    # Create a unique key combining location and team
    # This matches how Tanda combines them in timesheet exports
    tanda_location = f"{location_name} - {team_name}"
    
    # Skip duplicates
    if tanda_location in seen_combinations:
        continue
    
    seen_combinations.add(tanda_location)
    
    # Extract department info
    dept_code, dept_name = extract_department_info(cost_centre)
    
    if dept_code and dept_name:
        mapping = LocationMapping(
            tanda_location=tanda_location,
            cost_account_code=cost_centre,
            department_code=dept_code,
            department_name=dept_name,
            is_active=True
        )
        mappings.append(mapping)

# Bulk create
LocationMapping.objects.bulk_create(mappings, batch_size=500)

print(f"Created {len(mappings)} location mappings")
print()

# Show some examples
print("Sample mappings:")
for mapping in LocationMapping.objects.all()[:10]:
    print(f"  {mapping.tanda_location:<60} -> {mapping.cost_account_code} ({mapping.department_name})")

print()
print(f"Total mappings in database: {LocationMapping.objects.count()}")
