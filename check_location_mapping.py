"""
Check location mapping statistics
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import LocationMapping
from django.db.models import Count

# Count by department
dept_counts = LocationMapping.objects.values('department_code', 'department_name').annotate(
    count=Count('id')
).order_by('department_code')

print("Location Mappings by Department:")
print(f"{'Dept Code':<12} {'Department Name':<25} {'Count':>10}")
print('=' * 50)

for dept in dept_counts:
    print(f"{dept['department_code']:<12} {dept['department_name']:<25} {dept['count']:>10}")

print('=' * 50)
print(f"{'TOTAL':<38} {LocationMapping.objects.count():>10}")
print()

# Show unique cost centres
cost_centres = LocationMapping.objects.values_list('cost_account_code', flat=True).distinct().order_by('cost_account_code')
print(f"\nUnique Cost Centres ({len(cost_centres)}):")
for cc in cost_centres:
    count = LocationMapping.objects.filter(cost_account_code=cc).count()
    print(f"  {cc}: {count} mappings")
