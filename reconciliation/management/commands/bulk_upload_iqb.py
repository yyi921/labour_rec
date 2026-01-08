"""
Django management command to bulk upload IQB Detail V2 CSV files from a folder.

Usage:
    python manage.py bulk_upload_iqb <folder_path>

Example:
    python manage.py bulk_upload_iqb "C:/Users/yuany/OneDrive/Desktop/labour_reconciliation/media/test_data"
"""

from django.core.management.base import BaseCommand, CommandError
from reconciliation.models import IQBDetailV2, SageLocation, SageDepartment, IQBTransactionType
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import csv
import os
import glob


class Command(BaseCommand):
    help = 'Bulk upload IQB Detail V2 CSV files from a folder'

    def add_arguments(self, parser):
        parser.add_argument(
            'folder_path',
            type=str,
            help='Path to the folder containing CSV files'
        )
        parser.add_argument(
            '--pattern',
            type=str,
            default='*.csv',
            help='File pattern to match (default: *.csv)'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Batch size for bulk insertion (default: 1000)'
        )

    def handle(self, *args, **options):
        folder_path = options['folder_path']
        pattern = options['pattern']
        batch_size = options['batch_size']

        # Validate folder exists
        if not os.path.exists(folder_path):
            raise CommandError(f'Folder does not exist: {folder_path}')

        if not os.path.isdir(folder_path):
            raise CommandError(f'Path is not a directory: {folder_path}')

        # Find all CSV files
        search_pattern = os.path.join(folder_path, pattern)
        csv_files = glob.glob(search_pattern)

        if not csv_files:
            self.stdout.write(self.style.WARNING(f'No CSV files found matching pattern: {search_pattern}'))
            return

        self.stdout.write(self.style.SUCCESS(f'Found {len(csv_files)} CSV file(s) to process'))

        # Preload mapping data for performance
        self.stdout.write('Loading mapping data...')
        iqb_transaction_types = {
            tt.transaction_type: tt.include_in_costs
            for tt in IQBTransactionType.objects.filter(is_active=True)
        }
        sage_locations = {
            loc.location_id: loc.location_name
            for loc in SageLocation.objects.all()
        }
        sage_departments = {
            dept.department_id: dept.department_name
            for dept in SageDepartment.objects.all()
        }
        self.stdout.write(self.style.SUCCESS(f'Loaded {len(iqb_transaction_types)} transaction types, {len(sage_locations)} locations, {len(sage_departments)} departments'))

        # Process each file
        total_imported = 0
        total_errors = 0

        for csv_file_path in csv_files:
            file_name = os.path.basename(csv_file_path)
            self.stdout.write(f'\nProcessing: {file_name}')

            try:
                count, errors = self.process_file(
                    csv_file_path,
                    file_name,
                    batch_size,
                    iqb_transaction_types,
                    sage_locations,
                    sage_departments
                )
                total_imported += count
                total_errors += len(errors)

                if errors:
                    self.stdout.write(self.style.WARNING(f'  Imported {count} records with {len(errors)} errors'))
                    for error in errors[:5]:  # Show first 5 errors
                        self.stdout.write(self.style.ERROR(f'    {error}'))
                    if len(errors) > 5:
                        self.stdout.write(self.style.ERROR(f'    ... and {len(errors) - 5} more errors'))
                else:
                    self.stdout.write(self.style.SUCCESS(f'  Successfully imported {count} records'))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  Failed to process file: {str(e)}'))
                total_errors += 1

        # Summary
        self.stdout.write('\n' + '='*70)
        self.stdout.write(self.style.SUCCESS(f'Bulk upload complete!'))
        self.stdout.write(f'  Total files processed: {len(csv_files)}')
        self.stdout.write(f'  Total records imported: {total_imported}')
        if total_errors > 0:
            self.stdout.write(self.style.WARNING(f'  Total errors: {total_errors}'))

    def process_file(self, csv_file_path, file_name, batch_size, iqb_transaction_types, sage_locations, sage_departments):
        """Process a single CSV file"""
        count = 0
        errors = []
        records_to_create = []
        period_date = None

        with open(csv_file_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)

            for row_num, row in enumerate(reader, start=2):
                try:
                    # Skip empty rows
                    if not row.get('Employee Code', '').strip():
                        continue

                    # Get period end date from CSV (first row sets it for all)
                    if period_date is None:
                        csv_period_end = self.parse_date(row.get('Period End Date', ''))
                        if csv_period_end:
                            period_date = csv_period_end
                        else:
                            errors.append(f"Row {row_num}: Missing or invalid 'Period End Date' in CSV")
                            continue

                    # Calculate period start date
                    period_start = period_date - timedelta(days=13)

                    # Get cost account codes
                    cost_acc_code = row.get('Cost Account Code', '').strip()
                    default_cost_acc = row.get('Default Cost Account Code', '').strip()

                    # Map cost account to location and department
                    location_id, location_name, dept_code, dept_name, mapped_cost_account = self.map_cost_account(
                        cost_acc_code, default_cost_acc, sage_locations, sage_departments
                    )

                    # Map transaction type to include_in_costs
                    trans_type = row.get('Transaction Type', '').strip()
                    include_in_costs = iqb_transaction_types.get(trans_type, False)

                    record = IQBDetailV2(
                        file_name=file_name,
                        period_end_date=period_date,
                        period_start_date=period_start,
                        employee_code=row.get('Employee Code', '').strip(),
                        surname=row.get('Surname', '').strip(),
                        first_name=row.get('First Name', '').strip(),
                        given_names=row.get('Given Names', '').strip(),
                        other_names=row.get('Other Names', '').strip(),
                        full_name=row.get('Full Name', '').strip(),
                        surname_with_initials=row.get('Surname with Initials', '').strip(),
                        initials=row.get('Initials', '').strip(),
                        date_of_birth=self.parse_date(row.get('Date Of Birth', '')),
                        age=self.parse_int(row.get('Age', '')),
                        hired_date=self.parse_date(row.get('Hired Date', '')),
                        years_of_service=self.parse_decimal(row.get('Years Of Service', '')),
                        employment_type=row.get('Employment Type', '').strip(),
                        location=row.get('Location', '').strip(),
                        pay_point=row.get('Pay Point', '').strip(),
                        default_cost_account_code=default_cost_acc,
                        default_cost_account_description=row.get('Default Cost Account Description', '').strip(),
                        pay_period_id=row.get('Pay Period ID', '').strip(),
                        period_end_processed=row.get('Period End Processed', '').strip(),
                        sl_code=row.get('SL Code', '').strip(),
                        sl_description=row.get('SL Description', '').strip(),
                        al_code=row.get('AL Code', '').strip(),
                        al_description=row.get('AL Description', '').strip(),
                        lsl_code=row.get('LSL Code', '').strip(),
                        lsl_description=row.get('LSL Description', '').strip(),
                        pay_comp_add_ded_code=row.get('Pay Comp/Add Ded Code', '').strip(),
                        pay_comp_add_ded_desc=row.get('Pay Comp/Add Ded Desc', '').strip(),
                        shortcut_key=row.get('Shortcut Key', '').strip(),
                        other_leave_id=row.get('Other Leave ID', '').strip(),
                        post_type=row.get('Post Type', '').strip(),
                        cost_account_code=mapped_cost_account,
                        cost_account_description=row.get('Cost Account Description', '').strip(),
                        location_id=location_id,
                        location_name=location_name,
                        department_code=dept_code,
                        department_name=dept_name,
                        leave_start_date=self.parse_date(row.get('Leave Start Date', '')),
                        leave_end_date=self.parse_date(row.get('Leave End Date', '')),
                        recommence_date=self.parse_date(row.get('Recommence Date', '')),
                        pay_period_pay_frequency=row.get('Pay Period Pay Frequency', '').strip(),
                        number_of_periods=self.parse_int(row.get('Number of Periods', '')),
                        pay_advice_number=self.parse_int(row.get('Pay Advice Number', '')),
                        generate_payment=row.get('Generate Payment', '').strip(),
                        contract_hours_per_day=self.parse_decimal(row.get('Contract Hours per Day', '')),
                        contract_hours_per_week=self.parse_decimal(row.get('Contract Hours per Week', '')),
                        hours=self.parse_decimal(row.get('Hours', '')) or 0,
                        days=self.parse_decimal(row.get('Days', '')),
                        unit=self.parse_decimal(row.get('Unit', '')),
                        rate=self.parse_decimal(row.get('Rate', '')),
                        percent=self.parse_decimal(row.get('Percent', '')),
                        amount=self.parse_decimal(row.get('Amount', '')) or 0,
                        loading_rate=self.parse_decimal(row.get('Loading Rate', '')),
                        loading_percent=self.parse_decimal(row.get('Loading Percent', '')),
                        loading_amount=self.parse_decimal(row.get('Loading Amount', '')) or 0,
                        transaction_type=trans_type,
                        hours_worked_type=row.get('Hours Worked Type', '').strip(),
                        include_in_costs=include_in_costs,
                        leave_reason_code=row.get('Leave Reason Code', '').strip(),
                        leave_reason_description=row.get('Leave Reason Description', '').strip(),
                        rate_factor_code=row.get('Rate Factor Code', '').strip(),
                        rate_factor_description=row.get('Rate Factor Description', '').strip(),
                        rate_factor=self.parse_decimal(row.get('Rate Factor', '')),
                        pay_class_code=row.get('Pay Class Code', '').strip(),
                        pay_class_description=row.get('Pay Class Description', '').strip(),
                        addition_deduction_type=row.get('Addition/Deduction Type', '').strip(),
                        super_contribution_code=row.get('Super Contribution Code', '').strip(),
                        super_contribution_description=row.get('Super Contribution Description', '').strip(),
                        super_fund_code=row.get('Super Fund Code', '').strip(),
                        super_fund_description=row.get('Super Fund Description', '').strip(),
                        super_calculated_on=row.get('Super Calculated On', '').strip(),
                        employee_pay_frequency=row.get('Employee Pay Frequency', '').strip(),
                        termination_tax=row.get('Termination Tax', '').strip(),
                        pay_end_date_for_previous_earnings=self.parse_date(row.get('Pay End Date for Previous Earnings', '')),
                        adjustment_pay_period_date=self.parse_date(row.get('Adjustment Pay Period Date', '')),
                        pay_advice_print_date=self.parse_date(row.get('Pay Advice Print Date', '')),
                        qualification_value=self.parse_decimal(row.get('Qualification Value', '')),
                        sgl_actually_paid=self.parse_decimal(row.get('SGL Actually Paid', '')),
                        sgl_hours_worked=self.parse_decimal(row.get('SGL Hours Worked', '')),
                        date_super_process_completed=self.parse_date(row.get('Date Super Process Completed', '')),
                        sgl_age=self.parse_int(row.get('SGL Age', '')),
                        transaction_location=row.get('Transaction Location', '').strip(),
                        payroll_company=row.get('Payroll Company', '').strip(),
                        year_ending=self.parse_int(row.get('Year Ending', ''))
                    )
                    records_to_create.append(record)
                    count += 1

                    # Bulk insert every batch_size records
                    if len(records_to_create) >= batch_size:
                        IQBDetailV2.objects.bulk_create(records_to_create, batch_size=batch_size)
                        records_to_create = []

                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")
                    if len(errors) > 100:  # Limit errors
                        errors.append("... and more errors")
                        break

        # Insert any remaining records
        if records_to_create:
            IQBDetailV2.objects.bulk_create(records_to_create, batch_size=batch_size)

        return count, errors

    def parse_date(self, date_str):
        """Parse date from CSV"""
        if not date_str or date_str.strip() == '':
            return None
        try:
            return datetime.strptime(date_str.strip(), '%d/%m/%Y').date()
        except:
            try:
                return datetime.strptime(date_str.strip(), '%Y-%m-%d').date()
            except:
                return None

    def parse_decimal(self, value):
        """Parse decimal from CSV"""
        if not value or value.strip() == '':
            return None
        try:
            cleaned = value.replace('$', '').replace(',', '').strip()
            return Decimal(cleaned)
        except (ValueError, InvalidOperation):
            return None

    def parse_int(self, value):
        """Parse integer from CSV"""
        if not value or value.strip() == '':
            return None
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None

    def map_cost_account(self, cost_account_code, default_cost_account_code, sage_locations, sage_departments):
        """Map cost account code to location and department"""
        # If cost account is 100-1000, replace with default cost account
        if cost_account_code == '100-1000':
            cost_account_code = default_cost_account_code

        # Special case: If starts with SPL-, use full code for both location and department
        if cost_account_code and cost_account_code.startswith('SPL-'):
            return cost_account_code, cost_account_code, cost_account_code, cost_account_code, cost_account_code

        # Parse location and department from cost account code
        if cost_account_code and '-' in cost_account_code:
            parts = cost_account_code.split('-')
            location_id = parts[0].strip()
            dept_full = parts[1].strip() if len(parts) > 1 else ''

            # Department code is only the first 2 digits (e.g., "71" from "7100")
            dept_code = dept_full[:2] if len(dept_full) >= 2 else dept_full

            # Map to location name
            location_name = sage_locations.get(location_id, 'Invalid')

            # Map to department name
            department_name = sage_departments.get(dept_code, 'Invalid')

            return location_id, location_name, dept_code, department_name, cost_account_code
        else:
            return '', 'Invalid', '', 'Invalid', cost_account_code
