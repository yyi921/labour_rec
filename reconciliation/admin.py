from django.contrib import admin
from .models import (
    Employee, PayPeriod, Upload, TandaTimesheet, IQBDetail, JournalEntry,
    CostCenterSplit, ReconciliationRun, ReconciliationItem,
    ExceptionResolution, LabourCostSummary, SageIntacctExport,
    EmployeeReconciliation, JournalReconciliation, LocationMapping,
    ValidationResult, EmployeePayPeriodSnapshot, IQBLeaveBalance,
    LSLProbability, IQBTransactionType, PayCompCodeMapping, JournalDescriptionMapping,
    IQBDetailV2
)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = [
        'code', 'surname', 'first_name', 'employment_type', 'location',
        'job_classification', 'date_hired', 'termination_date', 'auto_pay'
    ]
    list_filter = ['employment_type', 'location', 'pay_point', 'auto_pay']
    search_fields = ['code', 'first_name', 'surname', 'job_classification']

    change_list_template = 'admin/employee_changelist.html'

    fieldsets = (
        ('Employee Information', {
            'fields': ('code', 'surname', 'first_name', 'date_of_birth')
        }),
        ('Employment Details', {
            'fields': (
                'location', 'employment_type', 'date_hired', 'pay_point',
                'termination_date', 'job_classification'
            )
        }),
        ('Pay Information', {
            'fields': (
                'auto_pay', 'normal_hours_paid', 'yearly_salary', 'auto_pay_amount',
                'award_rate', 'pay_class_description', 'normal_rate'
            )
        }),
        ('Cost Center', {
            'fields': ('default_cost_account', 'default_cost_account_description')
        }),
        ('Additional Information', {
            'fields': ('state', 'notes'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'updated_at']

    # Enable CSV export and import
    actions = ['export_as_csv']

    def export_as_csv(self, request, queryset):
        """Export selected employees to CSV matching master_employee_file.csv format"""
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="employees_export.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Surname', 'First Name', 'Code', 'Location', 'Employment Type',
            'Date Hired', 'Pay Point', 'Auto Pay', 'Normal Hours Paid',
            'Yearly Salary', 'Auto Pay Amount', 'Award Rate', 'Date of Birth',
            'Pay Class Description', 'Normal Rate', 'Termination Date',
            'Job Classification', 'Default Cost Account',
            'Default Cost Account Description', 'State', 'Notes'
        ])

        for employee in queryset:
            writer.writerow([
                employee.surname,
                employee.first_name,
                employee.code,
                employee.location,
                employee.employment_type,
                employee.date_hired.strftime('%d/%m/%Y') if employee.date_hired else '',
                employee.pay_point,
                employee.auto_pay,
                employee.normal_hours_paid if employee.normal_hours_paid else '',
                f"${employee.yearly_salary:,.2f}" if employee.yearly_salary else '',
                f"${employee.auto_pay_amount:,.2f}" if employee.auto_pay_amount else '',
                f"${employee.award_rate:.2f}" if employee.award_rate else '',
                employee.date_of_birth.strftime('%d/%m/%Y') if employee.date_of_birth else '',
                employee.pay_class_description,
                f"${employee.normal_rate:.2f}" if employee.normal_rate else '',
                employee.termination_date.strftime('%d/%m/%Y') if employee.termination_date else '',
                employee.job_classification,
                employee.default_cost_account,
                employee.default_cost_account_description,
                employee.state,
                employee.notes,
            ])

        return response
    export_as_csv.short_description = 'Export selected employees to CSV'

    def changelist_view(self, request, extra_context=None):
        """Add import functionality to changelist"""
        extra_context = extra_context or {}
        extra_context['show_import'] = True
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(PayPeriod)
class PayPeriodAdmin(admin.ModelAdmin):
    list_display = ['period_id', 'period_end', 'status', 'has_tanda', 'has_iqb', 'has_journal']
    list_filter = ['status', 'period_type']
    search_fields = ['period_id']

@admin.register(Upload)
class UploadAdmin(admin.ModelAdmin):
    list_display = ['upload_id', 'pay_period', 'source_system', 'version', 'is_active', 'uploaded_at']
    list_filter = ['source_system', 'is_active', 'status']
    search_fields = ['file_name']

@admin.register(TandaTimesheet)
class TandaTimesheetAdmin(admin.ModelAdmin):
    list_display = ['employee_id', 'employee_name', 'location_name', 'shift_hours', 'shift_cost']
    list_filter = ['employment_type', 'location_name', 'is_leave']
    search_fields = ['employee_id', 'employee_name']

@admin.register(IQBDetail)
class IQBDetailAdmin(admin.ModelAdmin):
    list_display = ['employee_code', 'full_name', 'cost_account_code', 'transaction_type', 'hours', 'amount']
    list_filter = ['transaction_type', 'employment_type']
    search_fields = ['employee_code', 'full_name', 'cost_account_code']


@admin.register(IQBDetailV2)
class IQBDetailV2Admin(admin.ModelAdmin):
    list_display = [
        'employee_code', 'full_name', 'period_end_date', 'month_year',
        'location_id', 'department_code', 'cost_account_code',
        'transaction_type', 'include_in_costs', 'hours', 'amount', 'file_name'
    ]
    list_filter = [
        'period_end_date', 'file_name', 'transaction_type', 'include_in_costs',
        'employment_type', 'location', 'location_id', 'department_code'
    ]
    search_fields = ['employee_code', 'full_name', 'cost_account_code', 'file_name']
    date_hierarchy = 'period_end_date'

    change_list_template = 'admin/iqbdetailv2_changelist.html'

    readonly_fields = ['created_at', 'updated_at', 'month_year']

    fieldsets = (
        ('File & Period Information', {
            'fields': ('file_name', 'period_end_date', 'period_start_date', 'month_year', 'upload')
        }),
        ('Employee Information', {
            'fields': (
                'employee_code', 'surname', 'first_name', 'given_names', 'other_names',
                'full_name', 'surname_with_initials', 'initials',
                'date_of_birth', 'age', 'hired_date', 'years_of_service'
            )
        }),
        ('Employment Details', {
            'fields': (
                'employment_type', 'location', 'pay_point',
                'default_cost_account_code', 'default_cost_account_description'
            )
        }),
        ('Pay Period Details', {
            'fields': ('pay_period_id', 'period_end_processed')
        }),
        ('Leave Codes', {
            'fields': (
                'sl_code', 'sl_description',
                'al_code', 'al_description',
                'lsl_code', 'lsl_description'
            ),
            'classes': ('collapse',)
        }),
        ('Pay Components', {
            'fields': (
                'pay_comp_add_ded_code', 'pay_comp_add_ded_desc',
                'shortcut_key', 'other_leave_id'
            )
        }),
        ('Transaction Details', {
            'fields': (
                'post_type', 'cost_account_code', 'cost_account_description',
                'transaction_type', 'hours_worked_type', 'include_in_costs'
            )
        }),
        ('Mapped Fields (Auto-populated)', {
            'fields': (
                'location_id', 'location_name',
                'department_code', 'department_name'
            ),
            'description': 'These fields are automatically mapped from the cost account code and can be edited if needed.'
        }),
        ('Leave Dates', {
            'fields': ('leave_start_date', 'leave_end_date', 'recommence_date'),
            'classes': ('collapse',)
        }),
        ('Pay Frequency', {
            'fields': (
                'pay_period_pay_frequency', 'number_of_periods',
                'pay_advice_number', 'generate_payment'
            ),
            'classes': ('collapse',)
        }),
        ('Hours and Contract', {
            'fields': (
                'contract_hours_per_day', 'contract_hours_per_week',
                'hours', 'days', 'unit'
            )
        }),
        ('Financial Details', {
            'fields': (
                'rate', 'percent', 'amount',
                'loading_rate', 'loading_percent', 'loading_amount'
            )
        }),
        ('Leave Reason', {
            'fields': ('leave_reason_code', 'leave_reason_description'),
            'classes': ('collapse',)
        }),
        ('Rate Factor', {
            'fields': ('rate_factor_code', 'rate_factor_description', 'rate_factor'),
            'classes': ('collapse',)
        }),
        ('Pay Class', {
            'fields': ('pay_class_code', 'pay_class_description', 'addition_deduction_type'),
            'classes': ('collapse',)
        }),
        ('Superannuation', {
            'fields': (
                'super_contribution_code', 'super_contribution_description',
                'super_fund_code', 'super_fund_description',
                'super_calculated_on', 'employee_pay_frequency'
            ),
            'classes': ('collapse',)
        }),
        ('Tax and Dates', {
            'fields': (
                'termination_tax', 'pay_end_date_for_previous_earnings',
                'adjustment_pay_period_date', 'pay_advice_print_date'
            ),
            'classes': ('collapse',)
        }),
        ('SGL (Superannuation Guarantee)', {
            'fields': (
                'qualification_value', 'sgl_actually_paid', 'sgl_hours_worked',
                'date_super_process_completed', 'sgl_age'
            ),
            'classes': ('collapse',)
        }),
        ('Location Details', {
            'fields': ('transaction_location', 'payroll_company', 'year_ending')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = ['delete_selected_records', 'export_as_csv']

    def delete_selected_records(self, request, queryset):
        """Delete selected IQB Detail V2 records"""
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f'Successfully deleted {count} IQB Detail V2 records')
    delete_selected_records.short_description = 'Delete selected IQB Detail V2 records'

    def export_as_csv(self, request, queryset):
        """Export selected records to CSV"""
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="iqb_details_v2_export.csv"'

        writer = csv.writer(response)
        # Write header
        writer.writerow([
            'Employee Code', 'Surname', 'First Name', 'Given Names', 'Other Names',
            'Full Name', 'Surname with Initials', 'Initials', 'Date Of Birth', 'Age',
            'Hired Date', 'Years Of Service', 'Employment Type', 'Location', 'Pay Point',
            'Default Cost Account Code', 'Default Cost Account Description',
            'Pay Period ID', 'Period End Date',
            'SL Code', 'SL Description', 'AL Code', 'AL Description',
            'LSL Code', 'LSL Description',
            'Pay Comp/Add Ded Code', 'Pay Comp/Add Ded Desc', 'Shortcut Key', 'Other Leave ID',
            'Post Type', 'Cost Account Code', 'Cost Account Description', 'Period End Processed',
            'Leave Start Date', 'Leave End Date', 'Recommence Date',
            'Pay Period Pay Frequency', 'Number of Periods', 'Pay Advice Number', 'Generate Payment',
            'Contract Hours per Day', 'Contract Hours per Week', 'Hours', 'Days', 'Unit',
            'Rate', 'Percent', 'Amount', 'Loading Rate', 'Loading Percent', 'Loading Amount',
            'Transaction Type', 'Hours Worked Type',
            'Leave Reason Code', 'Leave Reason Description',
            'Rate Factor Code', 'Rate Factor Description', 'Rate Factor',
            'Pay Class Code', 'Pay Class Description', 'Addition/Deduction Type',
            'Super Contribution Code', 'Super Contribution Description',
            'Super Fund Code', 'Super Fund Description', 'Super Calculated On',
            'Employee Pay Frequency', 'Termination Tax',
            'Pay End Date for Previous Earnings', 'Adjustment Pay Period Date', 'Pay Advice Print Date',
            'Qualification Value', 'SGL Actually Paid', 'SGL Hours Worked',
            'Date Super Process Completed', 'SGL Age',
            'Transaction Location', 'Payroll Company', 'Year Ending'
        ])

        for record in queryset:
            writer.writerow([
                record.employee_code,
                record.surname,
                record.first_name,
                record.given_names,
                record.other_names,
                record.full_name,
                record.surname_with_initials,
                record.initials,
                record.date_of_birth.strftime('%d/%m/%Y') if record.date_of_birth else '',
                record.age if record.age else '',
                record.hired_date.strftime('%d/%m/%Y') if record.hired_date else '',
                record.years_of_service if record.years_of_service else '',
                record.employment_type,
                record.location,
                record.pay_point,
                record.default_cost_account_code,
                record.default_cost_account_description,
                record.pay_period_id,
                record.period_end_date.strftime('%d/%m/%Y') if record.period_end_date else '',
                record.sl_code,
                record.sl_description,
                record.al_code,
                record.al_description,
                record.lsl_code,
                record.lsl_description,
                record.pay_comp_add_ded_code,
                record.pay_comp_add_ded_desc,
                record.shortcut_key,
                record.other_leave_id,
                record.post_type,
                record.cost_account_code,
                record.cost_account_description,
                record.period_end_processed,
                record.leave_start_date.strftime('%d/%m/%Y') if record.leave_start_date else '',
                record.leave_end_date.strftime('%d/%m/%Y') if record.leave_end_date else '',
                record.recommence_date.strftime('%d/%m/%Y') if record.recommence_date else '',
                record.pay_period_pay_frequency,
                record.number_of_periods if record.number_of_periods else '',
                record.pay_advice_number if record.pay_advice_number else '',
                record.generate_payment,
                record.contract_hours_per_day if record.contract_hours_per_day else '',
                record.contract_hours_per_week if record.contract_hours_per_week else '',
                record.hours,
                record.days if record.days else '',
                record.unit if record.unit else '',
                record.rate if record.rate else '',
                record.percent if record.percent else '',
                record.amount,
                record.loading_rate if record.loading_rate else '',
                record.loading_percent if record.loading_percent else '',
                record.loading_amount,
                record.transaction_type,
                record.hours_worked_type,
                record.leave_reason_code,
                record.leave_reason_description,
                record.rate_factor_code,
                record.rate_factor_description,
                record.rate_factor if record.rate_factor else '',
                record.pay_class_code,
                record.pay_class_description,
                record.addition_deduction_type,
                record.super_contribution_code,
                record.super_contribution_description,
                record.super_fund_code,
                record.super_fund_description,
                record.super_calculated_on,
                record.employee_pay_frequency,
                record.termination_tax,
                record.pay_end_date_for_previous_earnings.strftime('%d/%m/%Y') if record.pay_end_date_for_previous_earnings else '',
                record.adjustment_pay_period_date.strftime('%d/%m/%Y') if record.adjustment_pay_period_date else '',
                record.pay_advice_print_date.strftime('%d/%m/%Y') if record.pay_advice_print_date else '',
                record.qualification_value if record.qualification_value else '',
                record.sgl_actually_paid if record.sgl_actually_paid else '',
                record.sgl_hours_worked if record.sgl_hours_worked else '',
                record.date_super_process_completed.strftime('%d/%m/%Y') if record.date_super_process_completed else '',
                record.sgl_age if record.sgl_age else '',
                record.transaction_location,
                record.payroll_company,
                record.year_ending if record.year_ending else '',
            ])

        return response
    export_as_csv.short_description = 'Export selected records to CSV'

    def changelist_view(self, request, extra_context=None):
        """Add import functionality to changelist"""
        extra_context = extra_context or {}

        if request.method == 'POST':
            # Handle delete by file name
            if 'delete_file' in request.POST:
                file_name = request.POST.get('file_name_to_delete')
                if file_name:
                    if request.POST.get('confirm_delete_file') == 'yes':
                        count = IQBDetailV2.objects.filter(file_name=file_name).count()
                        IQBDetailV2.objects.filter(file_name=file_name).delete()
                        self.message_user(request, f'Successfully deleted {count} records from file: {file_name}')
                    else:
                        extra_context['show_file_delete_confirmation'] = True
                        extra_context['file_to_delete'] = file_name
                        extra_context['file_record_count'] = IQBDetailV2.objects.filter(file_name=file_name).count()

            # Handle delete all
            elif 'delete_all' in request.POST:
                if request.POST.get('confirm_delete') == 'yes':
                    count = IQBDetailV2.objects.count()
                    IQBDetailV2.objects.all().delete()
                    self.message_user(request, f'Successfully deleted {count} IQB Detail V2 records')
                else:
                    extra_context['show_delete_confirmation'] = True
                    extra_context['record_count'] = IQBDetailV2.objects.count()

            # Handle CSV upload
            elif 'csv_file' in request.FILES:
                csv_file = request.FILES['csv_file']

                try:
                    import csv as csv_module
                    from io import StringIO
                    from datetime import datetime, timedelta
                    from decimal import Decimal, InvalidOperation
                    from .models import SageLocation, SageDepartment, IQBTransactionType

                    # Get file name
                    file_name = csv_file.name

                    # Read CSV file
                    decoded_file = csv_file.read().decode('utf-8-sig')
                    io_string = StringIO(decoded_file)
                    reader = csv_module.DictReader(io_string)

                    # Preload mapping data for performance
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

                    # Helper function to parse dates
                    def parse_date(date_str):
                        if not date_str or date_str.strip() == '':
                            return None
                        try:
                            # Handle DD/MM/YYYY format
                            return datetime.strptime(date_str.strip(), '%d/%m/%Y').date()
                        except:
                            try:
                                # Handle other formats
                                return datetime.strptime(date_str.strip(), '%Y-%m-%d').date()
                            except:
                                return None

                    def parse_decimal(value):
                        if not value or value.strip() == '':
                            return None
                        try:
                            # Remove $ and , from the value
                            cleaned = value.replace('$', '').replace(',', '').strip()
                            return Decimal(cleaned)
                        except (ValueError, InvalidOperation):
                            return None

                    def parse_int(value):
                        if not value or value.strip() == '':
                            return None
                        try:
                            return int(float(value))
                        except (ValueError, TypeError):
                            return None

                    def map_cost_account(cost_account_code, default_cost_account_code):
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

                    # Import records using bulk_create for performance
                    records_to_create = []
                    count = 0
                    errors = []
                    batch_size = 1000  # Insert 1000 records at a time

                    for row_num, row in enumerate(reader, start=2):
                        try:
                            # Skip empty rows
                            if not row.get('Employee Code', '').strip():
                                continue

                            # Get period end date from CSV for THIS row
                            period_date = parse_date(row.get('Period End Date', ''))
                            if not period_date:
                                errors.append(f"Row {row_num}: Missing or invalid 'Period End Date'")
                                continue

                            # Calculate period start date
                            period_start = period_date - timedelta(days=13)

                            # Get cost account codes
                            cost_acc_code = row.get('Cost Account Code', '').strip()
                            default_cost_acc = row.get('Default Cost Account Code', '').strip()

                            # Map cost account to location and department
                            location_id, location_name, dept_code, dept_name, mapped_cost_account = map_cost_account(
                                cost_acc_code, default_cost_acc
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
                                date_of_birth=parse_date(row.get('Date Of Birth', '')),
                                age=parse_int(row.get('Age', '')),
                                hired_date=parse_date(row.get('Hired Date', '')),
                                years_of_service=parse_decimal(row.get('Years Of Service', '')),
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
                                # Mapped fields
                                location_id=location_id,
                                location_name=location_name,
                                department_code=dept_code,
                                department_name=dept_name,
                                leave_start_date=parse_date(row.get('Leave Start Date', '')),
                                leave_end_date=parse_date(row.get('Leave End Date', '')),
                                recommence_date=parse_date(row.get('Recommence Date', '')),
                                pay_period_pay_frequency=row.get('Pay Period Pay Frequency', '').strip(),
                                number_of_periods=parse_int(row.get('Number of Periods', '')),
                                pay_advice_number=parse_int(row.get('Pay Advice Number', '')),
                                generate_payment=row.get('Generate Payment', '').strip(),
                                contract_hours_per_day=parse_decimal(row.get('Contract Hours per Day', '')),
                                contract_hours_per_week=parse_decimal(row.get('Contract Hours per Week', '')),
                                hours=parse_decimal(row.get('Hours', '')) or 0,
                                days=parse_decimal(row.get('Days', '')),
                                unit=parse_decimal(row.get('Unit', '')),
                                rate=parse_decimal(row.get('Rate', '')),
                                percent=parse_decimal(row.get('Percent', '')),
                                amount=parse_decimal(row.get('Amount', '')) or 0,
                                loading_rate=parse_decimal(row.get('Loading Rate', '')),
                                loading_percent=parse_decimal(row.get('Loading Percent', '')),
                                loading_amount=parse_decimal(row.get('Loading Amount', '')) or 0,
                                transaction_type=trans_type,
                                hours_worked_type=row.get('Hours Worked Type', '').strip(),
                                include_in_costs=include_in_costs,
                                leave_reason_code=row.get('Leave Reason Code', '').strip(),
                                leave_reason_description=row.get('Leave Reason Description', '').strip(),
                                rate_factor_code=row.get('Rate Factor Code', '').strip(),
                                rate_factor_description=row.get('Rate Factor Description', '').strip(),
                                rate_factor=parse_decimal(row.get('Rate Factor', '')),
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
                                pay_end_date_for_previous_earnings=parse_date(row.get('Pay End Date for Previous Earnings', '')),
                                adjustment_pay_period_date=parse_date(row.get('Adjustment Pay Period Date', '')),
                                pay_advice_print_date=parse_date(row.get('Pay Advice Print Date', '')),
                                qualification_value=parse_decimal(row.get('Qualification Value', '')),
                                sgl_actually_paid=parse_decimal(row.get('SGL Actually Paid', '')),
                                sgl_hours_worked=parse_decimal(row.get('SGL Hours Worked', '')),
                                date_super_process_completed=parse_date(row.get('Date Super Process Completed', '')),
                                sgl_age=parse_int(row.get('SGL Age', '')),
                                transaction_location=row.get('Transaction Location', '').strip(),
                                payroll_company=row.get('Payroll Company', '').strip(),
                                year_ending=parse_int(row.get('Year Ending', ''))
                            )
                            records_to_create.append(record)
                            count += 1

                            # Bulk insert every batch_size records
                            if len(records_to_create) >= batch_size:
                                IQBDetailV2.objects.bulk_create(records_to_create, batch_size=batch_size)
                                records_to_create = []

                        except Exception as e:
                            errors.append(f"Row {row_num}: {str(e)}")
                            if len(errors) > 10:  # Limit error messages
                                errors.append("... and more errors")
                                break

                    # Insert any remaining records
                    if records_to_create:
                        IQBDetailV2.objects.bulk_create(records_to_create, batch_size=batch_size)

                    if errors:
                        error_msg = f'Imported {count} records with errors:\n' + '\n'.join(errors[:10])
                        self.message_user(request, error_msg, level='WARNING')
                    else:
                        self.message_user(request, f'Successfully imported {count} IQB Detail V2 records from {file_name}')

                except Exception as e:
                    self.message_user(request, f'Error importing CSV: {str(e)}', level='ERROR')

        extra_context['show_import'] = True
        extra_context['show_delete_all'] = True

        # Get list of uploaded files for deletion dropdown
        uploaded_files = IQBDetailV2.objects.values_list('file_name', flat=True).distinct().order_by('-file_name')
        extra_context['uploaded_files'] = list(uploaded_files)

        return super().changelist_view(request, extra_context=extra_context)


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ['cost_account', 'transaction', 'debit', 'hours', 'date']
    list_filter = ['ledger_account', 'transaction']
    search_fields = ['cost_account', 'description']

@admin.register(IQBLeaveBalance)
class IQBLeaveBalanceAdmin(admin.ModelAdmin):
    list_display = ['employee_code', 'full_name', 'leave_type', 'balance_hours', 'balance_value', 'leave_loading', 'years_of_service', 'as_of_date']
    list_filter = ['leave_type', 'employment_type', 'as_of_date', 'location']
    search_fields = ['employee_code', 'surname', 'first_name', 'full_name']
    readonly_fields = ['upload', 'as_of_date']

    change_list_template = 'admin/iqb_leave_balance_changelist.html'

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}

        if request.method == 'POST' and 'delete_all' in request.POST:
            # Confirm deletion
            if request.POST.get('confirm_delete') == 'yes':
                count = IQBLeaveBalance.objects.count()
                IQBLeaveBalance.objects.all().delete()
                self.message_user(request, f'Successfully deleted {count} IQB Leave Balance records')
            else:
                # Show confirmation
                extra_context['show_delete_confirmation'] = True
                extra_context['record_count'] = IQBLeaveBalance.objects.count()

        return super().changelist_view(request, extra_context=extra_context)

@admin.register(LSLProbability)
class LSLProbabilityAdmin(admin.ModelAdmin):
    list_display = ['years_from', 'years_to', 'probability', 'is_active', 'updated_at']
    list_filter = ['is_active']
    search_fields = []

    change_list_template = 'admin/lsl_probability_changelist.html'

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}

        if request.method == 'POST' and 'csv_file' in request.FILES:
            csv_file = request.FILES['csv_file']

            try:
                import csv as csv_module
                from io import StringIO
                from decimal import Decimal

                # Read CSV file
                decoded_file = csv_file.read().decode('utf-8')
                io_string = StringIO(decoded_file)
                reader = csv_module.DictReader(io_string)

                # Clear existing probabilities
                LSLProbability.objects.all().delete()

                # Import new probabilities
                count = 0
                for row in reader:
                    LSLProbability.objects.create(
                        years_from=Decimal(row['Years From']),
                        years_to=Decimal(row['Years To']),
                        probability=Decimal(row['Probability']),
                        is_active=True
                    )
                    count += 1

                self.message_user(request, f'Successfully imported {count} LSL probability records')

            except Exception as e:
                self.message_user(request, f'Error importing CSV: {str(e)}', level='ERROR')

        return super().changelist_view(request, extra_context=extra_context)

@admin.register(CostCenterSplit)
class CostCenterSplitAdmin(admin.ModelAdmin):
    list_display = ['source_account', 'target_account', 'percentage', 'is_active']
    list_filter = ['is_active']
    search_fields = ['source_account', 'target_account']

@admin.register(ReconciliationRun)
class ReconciliationRunAdmin(admin.ModelAdmin):
    list_display = ['run_id', 'pay_period', 'status', 'started_at', 'total_checks', 'checks_failed']
    list_filter = ['status']

@admin.register(ReconciliationItem)
class ReconciliationItemAdmin(admin.ModelAdmin):
    list_display = ['item_id', 'recon_type', 'severity', 'status', 'employee_id', 'cost_center']
    list_filter = ['recon_type', 'severity', 'status']
    search_fields = ['employee_id', 'employee_name', 'description']

@admin.register(ExceptionResolution)
class ExceptionResolutionAdmin(admin.ModelAdmin):
    list_display = ['resolution_id', 'modification_type', 'modified_by', 'modified_at', 'triggered_rerun']
    list_filter = ['modification_type', 'approval_status']

@admin.register(LabourCostSummary)
class LabourCostSummaryAdmin(admin.ModelAdmin):
    list_display = ['employee_code', 'cost_account_code', 'normal_pay', 'superannuation', 'total_cost']
    search_fields = ['employee_code', 'employee_name', 'cost_account_code']

@admin.register(SageIntacctExport)
class SageIntacctExportAdmin(admin.ModelAdmin):
    list_display = ['export_id', 'pay_period', 'status', 'record_count', 'total_amount', 'exported_at']
    list_filter = ['status']



@admin.register(EmployeeReconciliation)
class EmployeeReconciliationAdmin(admin.ModelAdmin):
    list_display = [
        'employee_id', 'employee_name', 'employment_type', 'is_salaried', 'pay_period',
        'tanda_total_hours', 'iqb_total_hours', 'hours_variance',
        'tanda_total_cost', 'auto_pay_amount', 'iqb_total_cost', 'iqb_superannuation', 'cost_variance',
        'hours_match', 'cost_match', 'has_issues'
    ]
    list_filter = ['pay_period', 'employment_type', 'is_salaried', 'has_issues', 'hours_match', 'cost_match', 'recon_run']
    search_fields = ['employee_id', 'employee_name']
    readonly_fields = [
        'pay_period', 'recon_run', 'employee_id', 'employee_name', 'employment_type',
        'is_salaried', 'auto_pay_amount', 'tanda_earliest_shift',
        'tanda_latest_shift', 'tanda_locations', 'cost_centers', 'tanda_leave_breakdown'
    ]

    fieldsets = (
        ('Employee', {
            'fields': ('pay_period', 'recon_run', 'employee_id', 'employee_name', 'employment_type', 'is_salaried', 'auto_pay_amount')
        }),
        ('Tanda Data (Worked)', {
            'fields': (
                'tanda_total_hours', 'tanda_total_cost', 'tanda_shift_count',
                'tanda_normal_hours', 'tanda_leave_hours', 'tanda_leave_breakdown',
                'tanda_earliest_shift', 'tanda_latest_shift', 'tanda_locations'
            )
        }),
        ('IQB Data (Paid)', {
            'fields': (
                'iqb_total_hours', 'iqb_gross_pay', 'iqb_superannuation', 'iqb_total_cost',
                'iqb_normal_pay', 'iqb_normal_hours',
                'iqb_overtime_pay', 'iqb_overtime_hours',
                'iqb_annual_leave_pay', 'iqb_annual_leave_hours',
                'iqb_sick_leave_pay', 'iqb_sick_leave_hours',
                'iqb_other_leave_pay', 'iqb_other_leave_hours',
                'cost_centers'
            )
        }),
        ('Reconciliation', {
            'fields': (
                'hours_variance', 'hours_variance_pct', 'hours_match',
                'cost_variance', 'cost_variance_pct', 'cost_match',
                'has_issues', 'issue_description'
            )
        }),
    )


@admin.register(JournalReconciliation)
class JournalReconciliationAdmin(admin.ModelAdmin):
    list_display = ['description', 'gl_account', 'journal_debit', 'journal_credit', 'journal_net', 'include_in_total_cost', 'is_mapped']
    list_filter = ['recon_run', 'include_in_total_cost', 'is_mapped']
    search_fields = ['description', 'gl_account']


@admin.register(LocationMapping)
class LocationMappingAdmin(admin.ModelAdmin):
    list_display = ['tanda_location', 'cost_account_code', 'department_code', 'department_name', 'is_active']
    list_filter = ['department_code', 'department_name', 'is_active']
    search_fields = ['tanda_location', 'cost_account_code']
    list_editable = ['is_active']


@admin.register(IQBTransactionType)
class IQBTransactionTypeAdmin(admin.ModelAdmin):
    list_display = ['transaction_type', 'include_in_hours', 'include_in_costs', 'is_active', 'notes']
    list_filter = ['include_in_hours', 'include_in_costs', 'is_active']
    search_fields = ['transaction_type', 'notes']
    list_editable = ['include_in_hours', 'include_in_costs', 'is_active']

    change_list_template = 'admin/iqbtransactiontype_changelist.html'

    fieldsets = (
        ('Transaction Type', {
            'fields': ('transaction_type', 'notes')
        }),
        ('Configuration', {
            'fields': ('include_in_hours', 'include_in_costs', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'updated_at']

    actions = ['export_as_csv']

    def export_as_csv(self, request, queryset):
        """Export selected transaction types to CSV"""
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="iqb_transaction_types.csv"'

        writer = csv.writer(response)
        writer.writerow(['Transaction Type', 'Include in Hours', 'Include in Costs', 'Notes'])

        for item in queryset:
            writer.writerow([
                item.transaction_type,
                'Yes' if item.include_in_hours else 'No',
                'Yes' if item.include_in_costs else 'No',
                item.notes
            ])

        return response
    export_as_csv.short_description = 'Export selected transaction types to CSV'

    def changelist_view(self, request, extra_context=None):
        """Add import functionality to changelist"""
        extra_context = extra_context or {}

        if request.method == 'POST' and 'csv_file' in request.FILES:
            csv_file = request.FILES['csv_file']

            try:
                import csv as csv_module
                from io import StringIO

                # Read CSV file
                decoded_file = csv_file.read().decode('utf-8-sig')  # utf-8-sig to handle BOM
                io_string = StringIO(decoded_file)
                reader = csv_module.DictReader(io_string)

                # Clear existing transaction types
                IQBTransactionType.objects.all().delete()

                # Import new transaction types
                count = 0
                for row in reader:
                    # Skip empty rows
                    if not row.get('Transaction Type', '').strip():
                        continue

                    IQBTransactionType.objects.create(
                        transaction_type=row['Transaction Type'].strip(),
                        include_in_hours=row.get('Include in Hours', '').strip().lower() in ['yes', 'true', '1'],
                        include_in_costs=row.get('Include in Costs', '').strip().lower() in ['yes', 'true', '1'],
                        notes=row.get('Notes', '').strip(),
                        is_active=True
                    )
                    count += 1

                self.message_user(request, f'Successfully imported {count} IQB transaction type records')

            except Exception as e:
                self.message_user(request, f'Error importing CSV: {str(e)}', level='ERROR')

        extra_context['show_import'] = True
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(PayCompCodeMapping)
class PayCompCodeMappingAdmin(admin.ModelAdmin):
    list_display = ['pay_comp_code', 'gl_account', 'gl_name']
    search_fields = ['pay_comp_code', 'gl_account', 'gl_name']
    list_editable = ['gl_account', 'gl_name']

    change_list_template = 'admin/paycompcode_mapping_changelist.html'

    def changelist_view(self, request, extra_context=None):
        """Add import functionality to changelist"""
        extra_context = extra_context or {}

        if request.method == 'POST' and 'csv_file' in request.FILES:
            csv_file = request.FILES['csv_file']

            try:
                import csv as csv_module
                from io import StringIO

                # Read CSV file
                decoded_file = csv_file.read().decode('utf-8-sig')  # utf-8-sig to handle BOM
                io_string = StringIO(decoded_file)
                reader = csv_module.DictReader(io_string)

                # Clear existing mappings
                PayCompCodeMapping.objects.all().delete()

                # Import new mappings
                count = 0
                for row in reader:
                    # Skip empty rows
                    if not row.get('Pay Comp/Add Ded Code', '').strip():
                        continue

                    PayCompCodeMapping.objects.create(
                        pay_comp_code=row['Pay Comp/Add Ded Code'].strip(),
                        gl_account=row['GL Account'].strip(),
                        gl_name=row['GL Name'].strip()
                    )
                    count += 1

                self.message_user(request, f'Successfully imported {count} Pay Comp Code mappings')

            except Exception as e:
                self.message_user(request, f'Error importing CSV: {str(e)}', level='ERROR')

        extra_context['show_import'] = True
        return super().changelist_view(request, extra_context=extra_context)

    actions = ['export_as_csv']

    def export_as_csv(self, request, queryset):
        """Export selected mappings to CSV"""
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="paycompcode_mapping.csv"'

        writer = csv.writer(response)
        writer.writerow(['Pay Comp/Add Ded Code', 'GL Account', 'GL Name'])

        for item in queryset:
            writer.writerow([
                item.pay_comp_code,
                item.gl_account,
                item.gl_name
            ])

        return response
    export_as_csv.short_description = 'Export selected mappings to CSV'


@admin.register(JournalDescriptionMapping)
class JournalDescriptionMappingAdmin(admin.ModelAdmin):
    list_display = ['description', 'gl_account', 'include_in_total_cost', 'is_active']
    search_fields = ['description', 'gl_account']
    list_filter = ['include_in_total_cost', 'is_active']
    list_editable = ['gl_account', 'include_in_total_cost', 'is_active']

    change_list_template = 'admin/journaldescription_mapping_changelist.html'

    fieldsets = (
        ('Mapping Details', {
            'fields': ('description', 'gl_account', 'include_in_total_cost')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'updated_at']

    def changelist_view(self, request, extra_context=None):
        """Add import functionality to changelist"""
        extra_context = extra_context or {}

        if request.method == 'POST' and 'csv_file' in request.FILES:
            csv_file = request.FILES['csv_file']

            try:
                import csv as csv_module
                from io import StringIO

                # Read CSV file
                decoded_file = csv_file.read().decode('utf-8-sig')  # utf-8-sig to handle BOM
                io_string = StringIO(decoded_file)
                reader = csv_module.DictReader(io_string)

                # Clear existing mappings
                JournalDescriptionMapping.objects.all().delete()

                # Import new mappings
                count = 0
                for row in reader:
                    # Skip empty rows
                    if not row.get('Description', '').strip():
                        continue

                    JournalDescriptionMapping.objects.create(
                        description=row['Description'].strip(),
                        gl_account=row['GL Account'].strip(),
                        include_in_total_cost=row.get('Total Cost', '').strip().upper() == 'Y',
                        is_active=True
                    )
                    count += 1

                self.message_user(request, f'Successfully imported {count} journal description mappings')

            except Exception as e:
                self.message_user(request, f'Error importing CSV: {str(e)}', level='ERROR')

        extra_context['show_import'] = True
        return super().changelist_view(request, extra_context=extra_context)

    actions = ['export_as_csv']

    def export_as_csv(self, request, queryset):
        """Export selected mappings to CSV"""
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="journal_description_mapping.csv"'

        writer = csv.writer(response)
        writer.writerow(['Description', 'Total Cost', 'GL Account'])

        for item in queryset:
            writer.writerow([
                item.description,
                'Y' if item.include_in_total_cost else '',
                item.gl_account
            ])

        return response
    export_as_csv.short_description = 'Export selected mappings to CSV'


@admin.register(ValidationResult)
class ValidationResultAdmin(admin.ModelAdmin):
    list_display = ['upload', 'passed', 'created_at']
    list_filter = ['passed', 'created_at']
    readonly_fields = ['upload', 'passed', 'validation_data', 'created_at']


@admin.register(EmployeePayPeriodSnapshot)
class EmployeePayPeriodSnapshotAdmin(admin.ModelAdmin):
    list_display = [
        'pay_period', 'employee_code', 'employee_name',
        'allocation_source', 'total_cost', 'created_at'
    ]
    list_filter = ['pay_period', 'allocation_source', 'employment_status']
    search_fields = ['employee_code', 'employee_name']
    readonly_fields = ['created_at', 'updated_at', 'allocation_finalized_at', 'allocation_finalized_by', 'formatted_cost_allocation']

    def formatted_cost_allocation(self, obj):
        """Display cost allocation in a readable format"""
        import json
        from django.utils.html import format_html
        if obj.cost_allocation:
            formatted = json.dumps(obj.cost_allocation, indent=2)
            return format_html('<pre>{}</pre>', formatted)
        return '-'
    formatted_cost_allocation.short_description = 'Cost Allocation by Location/Department'

    fieldsets = (
        ('Pay Period & Employee', {
            'fields': ('pay_period', 'employee_code', 'employee_name', 'employment_status', 'termination_date')
        }),
        ('Cost Allocation', {
            'fields': ('formatted_cost_allocation', 'allocation_source', 'allocation_finalized_at', 'allocation_finalized_by')
        }),
        ('Payroll Liability GL Accounts (2xxx)', {
            'fields': ('gl_2055_accrued_expenses', 'gl_2310_annual_leave', 'gl_2317_long_service_leave', 'gl_2318_toil_liability', 'gl_2320_sick_leave'),
            'classes': ('collapse',),
        }),
        ('Labour Expense GL Accounts (6xxx)', {
            'fields': (
                'gl_6300', 'gl_6302', 'gl_6305', 'gl_6309', 'gl_6310', 'gl_6312', 'gl_6315',
                'gl_6325', 'gl_6330', 'gl_6331', 'gl_6332', 'gl_6335', 'gl_6338',
                'gl_6340', 'gl_6345_salaries', 'gl_6350', 'gl_6355_sick_leave',
                'gl_6370_superannuation', 'gl_6372_toil', 'gl_6375', 'gl_6380'
            ),
            'classes': ('collapse',),
        }),
        ('Accrual Information', {
            'fields': (
                'accrual_period_start', 'accrual_period_end', 'accrual_days_in_period',
                'accrual_base_wages', 'accrual_superannuation', 'accrual_annual_leave',
                'accrual_long_service_leave', 'accrual_toil',
                'accrual_payroll_tax', 'accrual_workcover', 'accrual_total',
                'accrual_source', 'accrual_employee_type', 'accrual_calculated_at'
            ),
            'classes': ('collapse',),
        }),
        ('Totals', {
            'fields': ('total_cost', 'total_hours')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )