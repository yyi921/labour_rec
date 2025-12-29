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
    For accrual uploads, shows accrual-specific results
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

    # Check if this is an accrual upload
    is_accrual = upload.source_system == 'Accrual_Tanda'

    context = {
        'upload': upload,
        'pay_period': upload.pay_period,
        'validation_passed': validation.passed,
        'validations': validation_data.get('validations', []),
        'created_at': validation.created_at,
        'is_accrual': is_accrual,
    }

    # Add accrual-specific data
    if is_accrual:
        context.update({
            'accrual_summary': validation_data.get('summary', {}),
            'accrual_details': validation_data.get('details', {}),
            'accrual_period': validation_data.get('period', {}),
        })

    return render(request, 'reconciliation/validation_result.html', context)


def validation_summary_view(request, pay_period_id):
    """
    Display validation results for all uploads in a pay period
    """
    pay_period = get_object_or_404(PayPeriod, period_id=pay_period_id)

    # Get all active uploads for this pay period
    uploads = Upload.objects.filter(
        pay_period=pay_period,
        is_active=True
    ).order_by('source_system', '-uploaded_at')

    if not uploads.exists():
        return render(request, 'reconciliation/validation_summary.html', {
            'error': f'No uploads found for pay period {pay_period_id}',
            'pay_period': pay_period
        })

    # Get uploads and their validation results
    uploads_data = []

    for upload in uploads:
        try:
            validation = ValidationResult.objects.get(upload=upload)
            validation_data = validation.validation_data
            validations = validation_data.get('validations', [])
        except ValidationResult.DoesNotExist:
            validation = None
            validation_data = {}
            validations = []

        # Check if this is an accrual upload and extract accrual data
        is_accrual = upload.source_system == 'Accrual_Tanda'
        accrual_summary = None
        accrual_details = None
        accrual_period = None

        if is_accrual and validation_data:
            accrual_summary = validation_data.get('summary', {})
            accrual_details = validation_data.get('details', {})
            accrual_period = validation_data.get('period', {})

        uploads_data.append({
            'upload': upload,
            'validation': validation,
            'validation_passed': validation.passed if validation else None,
            'validations': validations,
            'is_accrual': is_accrual,
            'accrual_summary': accrual_summary,
            'accrual_details': accrual_details,
            'accrual_period': accrual_period
        })

    # Calculate overall status
    all_passed = all(data['validation_passed'] for data in uploads_data if data['validation_passed'] is not None)

    context = {
        'uploads_data': uploads_data,
        'pay_period': pay_period,
        'all_passed': all_passed,
        'total_uploads': len(uploads_data)
    }

    return render(request, 'reconciliation/validation_summary.html', context)
