import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import Upload, ValidationResult
from reconciliation.data_validator import DataValidator

upload = Upload.objects.get(upload_id='7afb0fa8c0c04e8a9df8267c23c956f3')
validation_results = DataValidator.validate_upload(upload)

# Save validation results
ValidationResult.objects.update_or_create(
    upload=upload,
    defaults={
        'passed': validation_results['passed'],
        'validation_data': validation_results
    }
)

print("Validation results saved!")
print(f"Passed: {validation_results['passed']}")
