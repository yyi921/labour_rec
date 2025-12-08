import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import Upload
from reconciliation.data_validator import DataValidator

# Test validation on the leave balance upload
upload = Upload.objects.get(upload_id='7afb0fa8c0c04e8a9df8267c23c956f3')
print(f"Testing validation for: {upload}")
print(f"Pay period: {upload.pay_period.period_end}")

validation_results = DataValidator.validate_upload(upload)

print(f"\nValidation Results:")
print(f"Passed: {validation_results['passed']}")

for v in validation_results['validations']:
    print(f"\n{v['test_name']}:")
    print(f"  Description: {v['description']}")
    print(f"  Passed: {v['passed']}")

    if v.get('errors'):
        print(f"  Errors:")
        for err in v['errors']:
            for key, val in err.items():
                print(f"    {key}: {val}")
