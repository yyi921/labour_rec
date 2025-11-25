"""
Data Validation Views
Shows validation results after file upload
"""
from django.shortcuts import render, get_object_or_404
from reconciliation.models import Upload, ValidationResult, PayPeriod


def validation_result_view(request, upload_id):
    """
    Display validation results for an upload
    Shows detailed validation test results with pass/fail status
    """
    upload = get_object_or_404(Upload, upload_id=upload_id)

    try:
        validation = ValidationResult.objects.get(upload=upload)
    except ValidationResult.DoesNotExist:
        return render(request, 'reconciliation/validation_result.html', {
            'upload': upload,
            'error': 'No validation results found for this upload'
        })

    validation_data = validation.validation_data

    context = {
        'upload': upload,
        'pay_period': upload.pay_period,
        'validation_passed': validation.passed,
        'validations': validation_data.get('validations', []),
        'created_at': validation.created_at,
    }

    return render(request, 'reconciliation/validation_result.html', context)
