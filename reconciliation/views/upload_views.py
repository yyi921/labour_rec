"""
Upload API views with smart detection and duplicate handling
"""
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework import status
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.contrib.auth.models import User
from django.utils import timezone
import os
import uuid

from reconciliation.models import Upload, PayPeriod, ValidationResult, EmployeePayPeriodSnapshot
from reconciliation.file_detector import FileDetector
from reconciliation.parsers import TandaParser, IQBParser, JournalParser, IQBLeaveBalanceParser
from reconciliation.data_validator import DataValidator
from datetime import datetime


def get_or_create_default_user():
    """Get or create a default system user for uploads"""
    user, created = User.objects.get_or_create(
        username='system_upload',
        defaults={
            'email': 'system@labour-rec.com',
            'first_name': 'System',
            'last_name': 'Upload'
        }
    )
    return user


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def smart_upload(request):
    """
    Smart file upload with auto-detection

    POST /api/uploads/smart/

    Form data:
        file: File to upload (CSV or Excel)
        pay_period_id: (Optional) Override pay period ID (YYYY-MM-DD format)

    Returns:
        - 200: File uploaded and processed successfully
        - 409: Duplicate file detected (returns override options)
        - 400: Invalid file or detection failed
        - 500: Processing error
    """

    # Check if file was provided
    if 'file' not in request.FILES:
        return Response({
            'status': 'error',
            'message': 'No file provided. Please upload a file.'
        }, status=status.HTTP_400_BAD_REQUEST)

    uploaded_file = request.FILES['file']
    override_pay_period_id = request.data.get('pay_period_id')  # Optional override

    # Save file temporarily
    temp_filename = f"temp_{uuid.uuid4()}_{uploaded_file.name}"
    temp_path = default_storage.save(f'temp/{temp_filename}', ContentFile(uploaded_file.read()))
    full_temp_path = default_storage.path(temp_path)

    try:
        # Step 1: Detect file type
        file_type, confidence, df = FileDetector.detect_file_type(full_temp_path)

        if file_type == 'Unknown' or confidence < 0.7:
            # Clean up temp file
            default_storage.delete(temp_path)

            return Response({
                'status': 'error',
                'message': 'Could not detect file type. Please ensure this is a valid Tanda, Micropay IQB, or Micropay Journal file.',
                'detected_type': file_type,
                'confidence': f"{confidence * 100:.1f}%"
            }, status=status.HTTP_400_BAD_REQUEST)

        # Step 2: Extract period (or use override if provided)
        if override_pay_period_id:
            # Use provided pay period ID
            try:
                override_date = datetime.strptime(override_pay_period_id, '%Y-%m-%d').date()
                period_info = {
                    'period_id': override_pay_period_id,
                    'period_start': override_date,  # Will be updated if pay period exists
                    'period_end': override_date
                }
            except ValueError:
                default_storage.delete(temp_path)
                return Response({
                    'status': 'error',
                    'message': 'Invalid pay_period_id format. Please use YYYY-MM-DD.'
                }, status=status.HTTP_400_BAD_REQUEST)
        else:
            # Auto-detect period from file
            period_info = FileDetector.extract_period(file_type, df, full_temp_path)

            if not period_info:
                default_storage.delete(temp_path)

                return Response({
                    'status': 'error',
                    'message': 'Could not extract pay period from file. Please check the file format.',
                    'file_type': file_type
                }, status=status.HTTP_400_BAD_REQUEST)

        # Step 3: Get or create pay period
        pay_period, period_created = PayPeriod.objects.get_or_create(
            period_id=period_info['period_id'],
            defaults={
                'period_start': period_info['period_start'],
                'period_end': period_info['period_end'],
                'period_type': 'fortnightly'
            }
        )
        
        # Step 4: Check for duplicate upload
        existing_upload = Upload.objects.filter(
            pay_period=pay_period,
            source_system=file_type,
            is_active=True
        ).first()
        
        if existing_upload:
            # Duplicate detected - return conflict response
            default_storage.delete(temp_path)
            
            return Response({
                'status': 'duplicate_detected',
                'message': f'{file_type} for period {period_info["period_id"]} already exists.',
                'file_type': file_type,
                'period': {
                    'period_id': period_info['period_id'],
                    'period_start': period_info['period_start'],
                    'period_end': period_info['period_end']
                },
                'existing_upload': {
                    'upload_id': str(existing_upload.upload_id),
                    'file_name': existing_upload.file_name,
                    'uploaded_at': existing_upload.uploaded_at.isoformat(),
                    'uploaded_by': existing_upload.uploaded_by.username,
                    'version': existing_upload.version,
                    'record_count': existing_upload.record_count
                },
                'prompt': 'Do you want to override the existing data?',
                'actions': {
                    'override': f'/api/uploads/{existing_upload.upload_id}/override/',
                    'cancel': '/api/uploads/cancel/'
                }
            }, status=status.HTTP_409_CONFLICT)
        
        # Step 5: Move file to permanent location
        permanent_filename = f"{file_type}_{period_info['period_id']}_{uuid.uuid4().hex[:8]}{os.path.splitext(uploaded_file.name)[1]}"
        permanent_path = default_storage.save(f'uploads/{permanent_filename}', ContentFile(open(full_temp_path, 'rb').read()))
        
        # Clean up temp file
        default_storage.delete(temp_path)
        
        # Step 6: Create upload record
        # Use authenticated user if available, otherwise use default system user
        user = request.user if request.user.is_authenticated else get_or_create_default_user()

        upload = Upload.objects.create(
            pay_period=pay_period,
            source_system=file_type,
            file_name=uploaded_file.name,
            file_path=permanent_path,
            uploaded_by=user,
            version=1,
            is_active=True,
            status='processing'
        )
        
        # Step 7: Parse the file
        try:
            full_permanent_path = default_storage.path(permanent_path)
            
            if file_type == 'Tanda_Timesheet':
                record_count = TandaParser.parse(upload, df)
                pay_period.has_tanda = True

            elif file_type == 'Micropay_IQB':
                record_count = IQBParser.parse(upload, df)
                pay_period.has_iqb = True

            elif file_type == 'Micropay_Journal':
                record_count = JournalParser.parse(upload, df)
                pay_period.has_journal = True

            elif file_type == 'Micropay_IQB_Leave':
                # Use pay period end date as the as_of_date
                as_of_date = datetime.strptime(pay_period.period_id, '%Y-%m-%d').date()
                record_count = IQBLeaveBalanceParser.parse(upload, df, as_of_date)
                # Note: We don't set a flag on pay_period for leave balance as it's optional
            
            # Update upload record
            upload.record_count = record_count
            upload.status = 'completed'
            upload.save()

            # Update pay period status
            if pay_period.has_tanda and pay_period.has_iqb and pay_period.has_journal:
                pay_period.status = 'uploaded'
            pay_period.save()

            # Step 8: Run data validation
            validation_results = DataValidator.validate_upload(upload)

            # Save validation results
            ValidationResult.objects.update_or_create(
                upload=upload,
                defaults={
                    'passed': validation_results['passed'],
                    'validation_data': validation_results
                }
            )

            return Response({
                'status': 'success',
                'message': f'{file_type} uploaded and processed successfully',
                'upload': {
                    'upload_id': str(upload.upload_id),
                    'file_type': file_type,
                    'file_name': uploaded_file.name,
                    'confidence': f"{confidence * 100:.1f}%",
                    'records_imported': record_count,
                    'version': upload.version
                },
                'period': {
                    'period_id': period_info['period_id'],
                    'period_start': str(period_info['period_start']),
                    'period_end': str(period_info['period_end']),
                    'status': pay_period.status,
                    'has_tanda': pay_period.has_tanda,
                    'has_iqb': pay_period.has_iqb,
                    'has_journal': pay_period.has_journal
                },
                'validation': {
                    'passed': validation_results['passed'],
                    'validation_url': f'/validation/{upload.upload_id}/'
                }
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            upload.status = 'failed'
            upload.error_message = str(e)
            upload.save()
            
            return Response({
                'status': 'error',
                'message': f'Error processing file: {str(e)}',
                'upload_id': str(upload.upload_id)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    except Exception as e:
        # Clean up temp file
        if default_storage.exists(temp_path):
            default_storage.delete(temp_path)
        
        return Response({
            'status': 'error',
            'message': f'Unexpected error: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def override_upload(request, upload_id):
    """
    Override an existing upload with a new version

    POST /api/uploads/{upload_id}/override/

    Form data:
        file: New file to upload
        reason: (optional) Reason for override
        pay_period_id: (optional) Override pay period ID (YYYY-MM-DD format)
    """

    try:
        # Get existing upload
        old_upload = Upload.objects.get(upload_id=upload_id, is_active=True)
    except Upload.DoesNotExist:
        return Response({
            'status': 'error',
            'message': 'Upload not found or already superseded'
        }, status=status.HTTP_404_NOT_FOUND)

    # Check if file was provided
    if 'file' not in request.FILES:
        return Response({
            'status': 'error',
            'message': 'No file provided'
        }, status=status.HTTP_400_BAD_REQUEST)

    uploaded_file = request.FILES['file']
    reason = request.data.get('reason', 'User requested override')
    override_pay_period_id = request.data.get('pay_period_id')  # Optional override

    # Save file temporarily
    temp_filename = f"temp_{uuid.uuid4()}_{uploaded_file.name}"
    temp_path = default_storage.save(f'temp/{temp_filename}', ContentFile(uploaded_file.read()))
    full_temp_path = default_storage.path(temp_path)

    try:
        # Detect and validate file type
        file_type, confidence, df = FileDetector.detect_file_type(full_temp_path)

        if file_type != old_upload.source_system:
            default_storage.delete(temp_path)
            return Response({
                'status': 'error',
                'message': f'File type mismatch. Expected {old_upload.source_system}, got {file_type}'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Extract or use overridden period
        if override_pay_period_id:
            # Use provided pay period ID (for leave calculation with LP/TP)
            try:
                override_date = datetime.strptime(override_pay_period_id, '%Y-%m-%d').date()
                period_info = {
                    'period_id': override_pay_period_id,
                    'period_start': override_date,
                    'period_end': override_date
                }
                # Skip period validation when overriding
            except ValueError:
                default_storage.delete(temp_path)
                return Response({
                    'status': 'error',
                    'message': 'Invalid pay_period_id format. Please use YYYY-MM-DD.'
                }, status=status.HTTP_400_BAD_REQUEST)
        else:
            # Extract and validate period normally
            period_info = FileDetector.extract_period(file_type, df, full_temp_path)
            if period_info['period_id'] != old_upload.pay_period.period_id:
                default_storage.delete(temp_path)
                return Response({
                    'status': 'error',
                    'message': f'Period mismatch. Expected {old_upload.pay_period.period_id}, got {period_info["period_id"]}'
                }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get or create the pay period (might be different if overriding)
        if override_pay_period_id:
            target_pay_period, _ = PayPeriod.objects.get_or_create(
                period_id=period_info['period_id'],
                defaults={
                    'period_start': period_info['period_start'],
                    'period_end': period_info['period_end'],
                    'period_type': 'fortnightly'
                }
            )
        else:
            target_pay_period = old_upload.pay_period

        # Move to permanent location
        permanent_filename = f"{file_type}_{period_info['period_id']}_v{old_upload.version + 1}_{uuid.uuid4().hex[:8]}{os.path.splitext(uploaded_file.name)[1]}"
        permanent_path = default_storage.save(f'uploads/{permanent_filename}', ContentFile(open(full_temp_path, 'rb').read()))

        # Clean up temp
        default_storage.delete(temp_path)

        # Create new upload (version++)
        # Use authenticated user if available, otherwise use default system user
        user = request.user if request.user.is_authenticated else get_or_create_default_user()

        new_upload = Upload.objects.create(
            pay_period=target_pay_period,
            source_system=old_upload.source_system,
            file_name=uploaded_file.name,
            file_path=permanent_path,
            uploaded_by=user,
            version=old_upload.version + 1,
            is_active=True,
            status='processing'
        )
        
        # Mark old upload as superseded
        old_upload.is_active = False
        old_upload.status = 'superseded'
        old_upload.replaced_by = new_upload
        old_upload.save()
        
        # Delete old records (cascade will handle this)
        if file_type == 'Tanda_Timesheet':
            old_upload.tanda_records.all().delete()
            record_count = TandaParser.parse(new_upload, df)

        elif file_type == 'Micropay_IQB':
            old_upload.iqb_records.all().delete()
            record_count = IQBParser.parse(new_upload, df)

        elif file_type == 'Micropay_Journal':
            old_upload.journal_records.all().delete()
            record_count = JournalParser.parse(new_upload, df)

        elif file_type == 'Micropay_IQB_Leave':
            old_upload.leave_balance_records.all().delete()
            as_of_date = datetime.strptime(target_pay_period.period_id, '%Y-%m-%d').date()
            record_count = IQBLeaveBalanceParser.parse(new_upload, df, as_of_date)
        
        # Update new upload
        new_upload.record_count = record_count
        new_upload.status = 'completed'
        new_upload.save()

        # Run data validation
        validation_results = DataValidator.validate_upload(new_upload)

        # Save validation results
        ValidationResult.objects.update_or_create(
            upload=new_upload,
            defaults={
                'passed': validation_results['passed'],
                'validation_data': validation_results
            }
        )

        return Response({
            'status': 'success',
            'message': 'Upload overridden successfully',
            'old_upload': {
                'upload_id': str(old_upload.upload_id),
                'version': old_upload.version,
                'status': old_upload.status
            },
            'new_upload': {
                'upload_id': str(new_upload.upload_id),
                'version': new_upload.version,
                'records_imported': record_count,
                'status': new_upload.status
            },
            'reason': reason,
            'validation': {
                'passed': validation_results['passed'],
                'validation_url': f'/validation/{new_upload.upload_id}/'
            }
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        if default_storage.exists(temp_path):
            default_storage.delete(temp_path)
        
        return Response({
            'status': 'error',
            'message': f'Error overriding upload: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def list_uploads(request):
    """
    List all uploads
    
    GET /api/uploads/
    
    Query params:
        period_id: Filter by period (optional)
        is_active: Filter by active status (optional)
    """
    uploads = Upload.objects.all().order_by('-uploaded_at')
    
    # Filter by period if provided
    period_id = request.query_params.get('period_id')
    if period_id:
        uploads = uploads.filter(pay_period__period_id=period_id)
    
    # Filter by active status if provided
    is_active = request.query_params.get('is_active')
    if is_active is not None:
        uploads = uploads.filter(is_active=is_active.lower() == 'true')
    
    # Serialize
    data = []
    for upload in uploads:
        data.append({
            'upload_id': str(upload.upload_id),
            'source_system': upload.source_system,
            'file_name': upload.file_name,
            'period_id': upload.pay_period.period_id,
            'uploaded_by': upload.uploaded_by.username,
            'uploaded_at': upload.uploaded_at.isoformat(),
            'version': upload.version,
            'is_active': upload.is_active,
            'status': upload.status,
            'record_count': upload.record_count
        })
    
    return Response({
        'status': 'success',
        'count': len(data),
        'uploads': data
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
def upload_detail(request, upload_id):
    """
    Get details of a specific upload
    
    GET /api/uploads/{upload_id}/
    """
    try:
        upload = Upload.objects.get(upload_id=upload_id)
    except Upload.DoesNotExist:
        return Response({
            'status': 'error',
            'message': 'Upload not found'
        }, status=status.HTTP_404_NOT_FOUND)
    
    return Response({
        'status': 'success',
        'upload': {
            'upload_id': str(upload.upload_id),
            'source_system': upload.source_system,
            'file_name': upload.file_name,
            'file_path': upload.file_path,
            'period': {
                'period_id': upload.pay_period.period_id,
                'period_start': str(upload.pay_period.period_start),
                'period_end': str(upload.pay_period.period_end),
                'status': upload.pay_period.status
            },
            'uploaded_by': upload.uploaded_by.username,
            'uploaded_at': upload.uploaded_at.isoformat(),
            'version': upload.version,
            'is_active': upload.is_active,
            'status': upload.status,
            'record_count': upload.record_count,
            'error_message': upload.error_message,
            'replaced_by': str(upload.replaced_by.upload_id) if upload.replaced_by else None
        }
    }, status=status.HTTP_200_OK)


def multi_upload(request):
    """
    Multi-file upload page
    GET /uploads/multi/
    """
    from django.shortcuts import render

    return render(request, 'reconciliation/multi_upload.html')


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def accrual_upload(request):
    """
    Upload Tanda timesheet for accrual wage calculation

    POST /api/uploads/accrual/

    Form data:
        file: Tanda timesheet file
        start_period: Start date (YYYY-MM-DD)
        end_period: End date (YYYY-MM-DD)
        pay_period_id: Pay period ID for posting journals (YYYY-MM-DD)

    Returns:
        - 200: File processed successfully
        - 400: Invalid file or parameters
        - 500: Processing error
    """
    # Check if file was provided
    if 'file' not in request.FILES:
        return Response({
            'status': 'error',
            'message': 'No file provided. Please upload a Tanda timesheet file.'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Get period parameters
    start_period = request.data.get('start_period')
    end_period = request.data.get('end_period')
    pay_period_id = request.data.get('pay_period_id')

    if not start_period or not end_period or not pay_period_id:
        return Response({
            'status': 'error',
            'message': 'Missing required parameters: start_period, end_period, pay_period_id'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Validate date formats
    try:
        start_date = datetime.strptime(start_period, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_period, '%Y-%m-%d').date()
        pay_period_date = datetime.strptime(pay_period_id, '%Y-%m-%d').date()
    except ValueError as e:
        return Response({
            'status': 'error',
            'message': f'Invalid date format. Please use YYYY-MM-DD: {str(e)}'
        }, status=status.HTTP_400_BAD_REQUEST)

    if end_date < start_date:
        return Response({
            'status': 'error',
            'message': 'End period must be after or equal to start period'
        }, status=status.HTTP_400_BAD_REQUEST)

    uploaded_file = request.FILES['file']

    # Save file temporarily
    temp_filename = f"temp_{uuid.uuid4()}_{uploaded_file.name}"
    temp_path = default_storage.save(f'temp/{temp_filename}', ContentFile(uploaded_file.read()))
    full_temp_path = default_storage.path(temp_path)

    try:
        # Step 1: Detect file type (must be Tanda_Timesheet)
        file_type, confidence, df = FileDetector.detect_file_type(full_temp_path)

        if file_type != 'Tanda_Timesheet':
            default_storage.delete(temp_path)
            return Response({
                'status': 'error',
                'message': f'Invalid file type. Expected Tanda_Timesheet, got {file_type}',
                'detected_type': file_type,
                'confidence': f"{confidence * 100:.1f}%"
            }, status=status.HTTP_400_BAD_REQUEST)

        # Step 2: Get or create pay period
        pay_period, period_created = PayPeriod.objects.get_or_create(
            period_id=pay_period_id,
            defaults={
                'period_start': start_date,
                'period_end': end_date,
                'period_type': 'accrual'
            }
        )

        # Step 3: Move file to permanent location
        permanent_filename = f"Accrual_Tanda_{pay_period_id}_{uuid.uuid4().hex[:8]}{os.path.splitext(uploaded_file.name)[1]}"
        permanent_path = default_storage.save(f'uploads/{permanent_filename}', ContentFile(open(full_temp_path, 'rb').read()))

        # Clean up temp file
        default_storage.delete(temp_path)

        # Step 4: Create upload record
        user = request.user if request.user.is_authenticated else get_or_create_default_user()

        upload = Upload.objects.create(
            pay_period=pay_period,
            source_system='Accrual_Tanda',
            file_name=uploaded_file.name,
            file_path=permanent_path,
            uploaded_by=user,
            version=1,
            is_active=True,
            status='processing'
        )

        # Step 5: Parse the Tanda file
        try:
            record_count = TandaParser.parse(upload, df)

            upload.record_count = record_count
            upload.status = 'completed'
            upload.save()

            # Step 6: Process accruals
            from reconciliation.accrual_processor import AccrualWageProcessor

            accrual_results = AccrualWageProcessor.process_accruals(
                upload=upload,
                start_date=start_date,
                end_date=end_date,
                pay_period=pay_period
            )

            # Update pay period status
            pay_period.status = 'accrual_processed'
            pay_period.save()

            # Create reversal pay period for next month
            from datetime import timedelta
            reversal_date = end_date + timedelta(days=1)
            reversal_period_id = reversal_date.strftime('%Y-%m-%d')

            reversal_period, reversal_created = PayPeriod.objects.get_or_create(
                period_id=reversal_period_id,
                defaults={
                    'period_start': reversal_date,
                    'period_end': reversal_date,
                    'period_type': 'accrual_reversal'
                }
            )

            # Copy all snapshots with negative amounts for reversal
            if reversal_created:
                original_snapshots = EmployeePayPeriodSnapshot.objects.filter(
                    pay_period=pay_period
                )

                for snapshot in original_snapshots:
                    EmployeePayPeriodSnapshot.objects.create(
                        pay_period=reversal_period,
                        employee_code=snapshot.employee_code,
                        employee_name=snapshot.employee_name,
                        employment_status=snapshot.employment_status,
                        termination_date=snapshot.termination_date,

                        # Accrual period info (same as original)
                        accrual_period_start=snapshot.accrual_period_start,
                        accrual_period_end=snapshot.accrual_period_end,
                        accrual_days_in_period=snapshot.accrual_days_in_period,

                        # Negative amounts for reversal
                        accrual_base_wages=-snapshot.accrual_base_wages,
                        accrual_superannuation=-snapshot.accrual_superannuation,
                        accrual_annual_leave=-snapshot.accrual_annual_leave,
                        accrual_payroll_tax=-snapshot.accrual_payroll_tax,
                        accrual_workcover=-snapshot.accrual_workcover,
                        accrual_total=-snapshot.accrual_total,

                        # Metadata
                        accrual_source=f"reversal_{snapshot.accrual_source}",
                        accrual_calculated_at=timezone.now(),
                        accrual_employee_type=snapshot.accrual_employee_type,

                        # Negative GL Account totals
                        gl_6345_salaries=-snapshot.gl_6345_salaries,
                        gl_6370_superannuation=-snapshot.gl_6370_superannuation,
                        gl_6300=-snapshot.gl_6300,
                        gl_6335=-snapshot.gl_6335,
                        gl_6380=-snapshot.gl_6380,
                        gl_2055_accrued_expenses=-snapshot.gl_2055_accrued_expenses,

                        # Negative total cost
                        total_cost=-snapshot.total_cost,

                        # Same cost allocation
                        cost_allocation=snapshot.cost_allocation,
                        allocation_source=f"reversal_{snapshot.allocation_source}",
                        allocation_finalized_at=timezone.now()
                    )

                reversal_period.status = 'accrual_reversed'
                reversal_period.save()

            # Build validation result
            validation_passed = (
                len(accrual_results['validation_errors']) == 0 and
                len(accrual_results['gl_code_errors']) == 0
            )

            validation_data = {
                'passed': validation_passed,
                'summary': {
                    'total_processed': accrual_results['processed_count'],
                    'total_skipped': accrual_results['skipped_count'],
                    'total_accrued': accrual_results['total_accrued'],
                    'employees_not_found_count': len(accrual_results['employees_not_found']),
                    'employees_terminated_count': len(accrual_results['employees_terminated']),
                    'employees_auto_pay_only_count': len(accrual_results['employees_auto_pay_only']),
                    'validation_errors_count': len(accrual_results['validation_errors']),
                    'gl_code_errors_count': len(accrual_results['gl_code_errors'])
                },
                'details': accrual_results,
                'period': {
                    'start_date': str(start_date),
                    'end_date': str(end_date),
                    'pay_period_id': pay_period_id,
                    'days': (end_date - start_date).days + 1
                }
            }

            # Save validation results
            ValidationResult.objects.update_or_create(
                upload=upload,
                defaults={
                    'passed': validation_passed,
                    'validation_data': validation_data
                }
            )

            return Response({
                'status': 'success',
                'message': f'Accrual processing completed. Processed {accrual_results["processed_count"]} employees. Reversal period {reversal_period_id} created.',
                'upload_id': str(upload.upload_id),
                'file_type': 'Accrual_Tanda',
                'file_name': uploaded_file.name,
                'records_imported': record_count,
                'accrual_results': accrual_results,
                'validation_result': validation_data,
                'validation_url': f'/validation/{upload.upload_id}/',
                'reversal_period_id': reversal_period_id,
                'reversal_period_created': reversal_created
            }, status=status.HTTP_200_OK)

        except Exception as e:
            upload.status = 'failed'
            upload.error_message = str(e)
            upload.save()

            return Response({
                'status': 'error',
                'message': f'Error processing accrual file: {str(e)}',
                'upload_id': str(upload.upload_id)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    except Exception as e:
        # Clean up temp file
        if default_storage.exists(temp_path):
            default_storage.delete(temp_path)

        return Response({
            'status': 'error',
            'message': f'Unexpected error: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)