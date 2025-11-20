"""
Upload handler with versioning support
Ensures only one active file per type per pay period
"""
from django.db import transaction
from reconciliation.models import Upload, PayPeriod


class UploadHandler:
    """Handle file uploads with automatic versioning"""

    @staticmethod
    @transaction.atomic
    def create_upload(pay_period, source_system, file_name, file_path, uploaded_by):
        """
        Create a new upload, superseding any existing active upload for the same period and type

        Args:
            pay_period: PayPeriod instance
            source_system: 'Tanda_Timesheet', 'Micropay_IQB', or 'Micropay_Journal'
            file_name: Name of the uploaded file
            file_path: Path to the uploaded file
            uploaded_by: User who uploaded the file

        Returns:
            Upload instance (newly created)
        """
        # Check for existing active upload of same type for this period
        existing_upload = Upload.objects.filter(
            pay_period=pay_period,
            source_system=source_system,
            is_active=True
        ).first()

        if existing_upload:
            # Supersede the existing upload
            print(f"Found existing {source_system} upload (v{existing_upload.version})")
            print(f"Superseding with new version...")

            # Mark old upload as superseded
            existing_upload.is_active = False
            existing_upload.status = 'superseded'

            # Delete old records to avoid duplicates
            _delete_old_records(existing_upload, source_system)

            # Set version for new upload
            new_version = existing_upload.version + 1
        else:
            new_version = 1
            print(f"Creating new {source_system} upload (v{new_version})")

        # Create new upload
        new_upload = Upload.objects.create(
            pay_period=pay_period,
            source_system=source_system,
            file_name=file_name,
            file_path=file_path,
            uploaded_by=uploaded_by,
            version=new_version,
            is_active=True,
            status='processing'
        )

        # Link old upload to new one if it exists
        if existing_upload:
            existing_upload.replaced_by = new_upload
            existing_upload.save()

        return new_upload


def _delete_old_records(upload, source_system):
    """Delete old records associated with superseded upload"""
    if source_system == 'Tanda_Timesheet':
        count = upload.tanda_records.count()
        upload.tanda_records.all().delete()
        print(f"  Deleted {count} old Tanda records")

    elif source_system == 'Micropay_IQB':
        count = upload.iqb_records.count()
        upload.iqb_records.all().delete()
        print(f"  Deleted {count} old IQB records")

    elif source_system == 'Micropay_Journal':
        count = upload.journal_records.count()
        upload.journal_records.all().delete()
        print(f"  Deleted {count} old Journal records")
