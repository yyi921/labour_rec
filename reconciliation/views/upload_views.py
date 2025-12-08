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
import os
import uuid

from reconciliation.models import Upload, PayPeriod, ValidationResult
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
        
        # Step 2: Extract period
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
        
        # Extract and validate period
        period_info = FileDetector.extract_period(file_type, df, full_temp_path)
        if period_info['period_id'] != old_upload.pay_period.period_id:
            default_storage.delete(temp_path)
            return Response({
                'status': 'error',
                'message': f'Period mismatch. Expected {old_upload.pay_period.period_id}, got {period_info["period_id"]}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Move to permanent location
        permanent_filename = f"{file_type}_{period_info['period_id']}_v{old_upload.version + 1}_{uuid.uuid4().hex[:8]}{os.path.splitext(uploaded_file.name)[1]}"
        permanent_path = default_storage.save(f'uploads/{permanent_filename}', ContentFile(open(full_temp_path, 'rb').read()))
        
        # Clean up temp
        default_storage.delete(temp_path)

        # Create new upload (version++)
        # Use authenticated user if available, otherwise use default system user
        user = request.user if request.user.is_authenticated else get_or_create_default_user()

        new_upload = Upload.objects.create(
            pay_period=old_upload.pay_period,
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
            as_of_date = datetime.strptime(pay_period.period_id, '%Y-%m-%d').date()
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