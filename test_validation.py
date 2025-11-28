"""
Test script for data validation functionality
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from reconciliation.models import Upload, ValidationResult
from reconciliation.data_validator import DataValidator


def test_validation(upload_id):
    """Test validation for a specific upload"""
    try:
        upload = Upload.objects.get(upload_id=upload_id)
        print(f"\n{'='*60}")
        print(f"Testing Validation for Upload: {upload.file_name}")
        print(f"Source System: {upload.source_system}")
        print(f"Pay Period: {upload.pay_period.period_id}")
        print(f"{'='*60}\n")

        # Run validation
        print("Running validation tests...")
        results = DataValidator.validate_upload(upload)

        # Save results
        validation_result, created = ValidationResult.objects.update_or_create(
            upload=upload,
            defaults={
                'passed': results['passed'],
                'validation_data': results
            }
        )

        # Display results
        print(f"\nOverall Status: {'PASSED' if results['passed'] else 'FAILED'}")
        print(f"\nValidation Tests:\n")

        for test in results['validations']:
            status = "[PASS]" if test['passed'] else "[FAIL]"
            print(f"{status} - {test['test_name']}")
            print(f"   {test['description']}")

            if not test['passed']:
                print(f"   Errors found:")
                for error in test['errors']:
                    if 'message' in error:
                        print(f"   - {error['message']}")
                    if 'invalid_location' in error:
                        print(f"   - Invalid Location: {error['invalid_location']}")
                        print(f"     Total occurrences: {error['total_count']}")
                    if 'invalid_department' in error:
                        print(f"   - Invalid Department: {error['invalid_department']}")
                        print(f"     Total occurrences: {error['total_count']}")
                    if 'missing_accounts' in error:
                        print(f"   - Missing accounts: {error['total_count']}")
                    if 'missing_codes' in error:
                        print(f"   - Missing codes: {error['total_count']}")
            print()

        print(f"\nValidation result saved to database")
        print(f"View results at: /validation/{upload.upload_id}/")

    except Upload.DoesNotExist:
        print(f"Error: Upload with ID {upload_id} not found")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


def list_recent_uploads():
    """List recent uploads"""
    uploads = Upload.objects.filter(is_active=True).order_by('-uploaded_at')[:5]

    print("\nRecent Uploads:")
    print(f"{'='*80}")
    for upload in uploads:
        print(f"Upload ID: {upload.upload_id}")
        print(f"  File: {upload.file_name}")
        print(f"  Type: {upload.source_system}")
        print(f"  Period: {upload.pay_period.period_id}")
        print(f"  Status: {upload.status}")
        print()


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1:
        upload_id = sys.argv[1]
        test_validation(upload_id)
    else:
        print("Usage: python test_validation.py <upload_id>")
        print("\nOr list recent uploads:\n")
        list_recent_uploads()
