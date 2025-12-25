"""
Admin-specific views for importing data
"""
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from reconciliation.models import Employee
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation


@staff_member_required
def import_employees(request):
    """
    Import employees from CSV file
    Matches format of master_employee_file.csv
    Updates existing employees or creates new ones based on Code
    """
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']

        # Validate file type
        if not csv_file.name.endswith('.csv'):
            messages.error(request, 'File must be a CSV file')
            return render(request, 'admin/import_employees.html')

        try:
            # Read CSV file
            decoded_file = csv_file.read().decode('utf-8').splitlines()
            reader = csv.DictReader(decoded_file)

            created_count = 0
            updated_count = 0
            error_count = 0
            errors = []

            with transaction.atomic():
                for row_num, row in enumerate(reader, start=2):  # Start at 2 for header
                    try:
                        # Extract data from CSV row
                        code = row.get('Code', '').strip()

                        if not code:
                            errors.append(f"Row {row_num}: Missing employee code")
                            error_count += 1
                            continue

                        # Parse dates
                        date_hired = parse_date(row.get('Date Hired', ''))
                        date_of_birth = parse_date(row.get('Date of Birth', ''))
                        termination_date = parse_date(row.get('Termination Date', ''))

                        # Parse decimal values
                        normal_hours_paid = parse_decimal(row.get('Normal Hours Paid', ''))
                        yearly_salary = parse_currency(row.get('Yearly Salary', ''))
                        auto_pay_amount = parse_currency(row.get('Auto Pay Amount', ''))
                        award_rate = parse_currency(row.get('Award Rate', ''))
                        normal_rate = parse_currency(row.get('Normal Rate', ''))

                        # Create or update employee
                        employee, created = Employee.objects.update_or_create(
                            code=code,
                            defaults={
                                'surname': row.get('Surname', '').strip(),
                                'first_name': row.get('First Name', '').strip(),
                                'location': row.get('Location', '').strip(),
                                'employment_type': row.get('Employment Type', '').strip(),
                                'date_hired': date_hired,
                                'pay_point': row.get('Pay Point', '').strip(),
                                'auto_pay': row.get('Auto Pay', '').strip(),
                                'normal_hours_paid': normal_hours_paid,
                                'yearly_salary': yearly_salary,
                                'auto_pay_amount': auto_pay_amount,
                                'award_rate': award_rate,
                                'date_of_birth': date_of_birth,
                                'pay_class_description': row.get('Pay Class Description', '').strip(),
                                'normal_rate': normal_rate,
                                'termination_date': termination_date,
                                'job_classification': row.get('Job Classification', '').strip(),
                                'default_cost_account': row.get('Default Cost Account', '').strip(),
                                'default_cost_account_description': row.get('Default Cost Account Description', '').strip(),
                                'notes': row.get('Notes', '').strip(),
                            }
                        )

                        if created:
                            created_count += 1
                        else:
                            updated_count += 1

                    except Exception as e:
                        errors.append(f"Row {row_num}: {str(e)}")
                        error_count += 1

            # Display results
            if created_count > 0:
                messages.success(request, f'Successfully created {created_count} new employee(s)')
            if updated_count > 0:
                messages.success(request, f'Successfully updated {updated_count} existing employee(s)')
            if error_count > 0:
                messages.warning(request, f'Failed to process {error_count} row(s)')
                for error in errors[:10]:  # Show first 10 errors
                    messages.error(request, error)
                if len(errors) > 10:
                    messages.error(request, f'... and {len(errors) - 10} more errors')

            return redirect('admin:reconciliation_employee_changelist')

        except Exception as e:
            messages.error(request, f'Error processing CSV file: {str(e)}')
            return render(request, 'admin/import_employees.html')

    return render(request, 'admin/import_employees.html')


def parse_date(date_str):
    """Parse date from DD/MM/YYYY format"""
    if not date_str or date_str.strip() == '':
        return None
    try:
        return datetime.strptime(date_str.strip(), '%d/%m/%Y').date()
    except ValueError:
        return None


def parse_decimal(value_str):
    """Parse decimal value"""
    if not value_str or value_str.strip() == '':
        return None
    try:
        # Remove any commas
        clean_value = value_str.replace(',', '')
        return Decimal(clean_value)
    except (InvalidOperation, ValueError):
        return None


def parse_currency(value_str):
    """Parse currency value (removes $ and commas)"""
    if not value_str or value_str.strip() == '':
        return None
    try:
        # Remove $ and commas
        clean_value = value_str.replace('$', '').replace(',', '').strip()
        if clean_value == '':
            return None
        return Decimal(clean_value)
    except (InvalidOperation, ValueError):
        return None
