from reconciliation.models import Upload, PayPeriod

pp = PayPeriod.objects.filter(period_id='2025-11-16').first()
print(f'Pay Period: {pp}')

if pp:
    uploads = Upload.objects.filter(pay_period=pp, is_active=True)
    print(f'\nActive uploads for this period ({uploads.count()} total):')
    for u in uploads:
        print(f'  - {u.source_system}: {u.original_filename}')

    # Check for any uploads with "leave" in the filename
    print('\nAll uploads (active or not) with "leave" in filename:')
    leave_uploads = Upload.objects.filter(
        pay_period=pp,
        original_filename__icontains='leave'
    )
    for u in leave_uploads:
        print(f'  - {u.source_system} (active={u.is_active}): {u.original_filename}')
else:
    print('Pay period not found!')
