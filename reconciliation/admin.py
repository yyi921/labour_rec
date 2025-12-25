from django.contrib import admin
from .models import (
    Employee, PayPeriod, Upload, TandaTimesheet, IQBDetail, JournalEntry,
    CostCenterSplit, ReconciliationRun, ReconciliationItem,
    ExceptionResolution, LabourCostSummary, SageIntacctExport,
    EmployeeReconciliation, JournalReconciliation, LocationMapping,
    ValidationResult, EmployeePayPeriodSnapshot, IQBLeaveBalance
)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = [
        'employee_code', 'full_name', 'employment_type', 'employment_status',
        'is_salaried', 'location', 'department', 'hire_date', 'termination_date'
    ]
    list_filter = ['employment_status', 'employment_type', 'is_salaried', 'location', 'department']
    search_fields = ['employee_code', 'first_name', 'surname', 'full_name', 'email']
    list_editable = ['employment_status']
    date_hierarchy = 'hire_date'

    fieldsets = (
        ('Employee Information', {
            'fields': ('employee_code', 'first_name', 'surname', 'full_name')
        }),
        ('Employment Details', {
            'fields': (
                'employment_type', 'employment_status', 'is_salaried',
                'hire_date', 'termination_date'
            )
        }),
        ('Organizational Details', {
            'fields': ('location', 'department', 'job_title', 'manager')
        }),
        ('Pay Information', {
            'fields': ('base_salary', 'pay_rate_type')
        }),
        ('Contact Information', {
            'fields': ('email', 'phone')
        }),
        ('Additional Information', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'updated_at']

    # Enable CSV export
    actions = ['export_as_csv']

    def export_as_csv(self, request, queryset):
        """Export selected employees to CSV"""
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="employees.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Employee Code', 'First Name', 'Surname', 'Full Name',
            'Employment Type', 'Employment Status', 'Is Salaried',
            'Location', 'Department', 'Job Title', 'Manager',
            'Hire Date', 'Termination Date', 'Email', 'Phone',
            'Base Salary', 'Pay Rate Type'
        ])

        for employee in queryset:
            writer.writerow([
                employee.employee_code,
                employee.first_name,
                employee.surname,
                employee.full_name,
                employee.employment_type,
                employee.employment_status,
                employee.is_salaried,
                employee.location,
                employee.department,
                employee.job_title,
                employee.manager,
                employee.hire_date,
                employee.termination_date,
                employee.email,
                employee.phone,
                employee.base_salary,
                employee.pay_rate_type,
            ])

        return response
    export_as_csv.short_description = 'Export selected employees to CSV'


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

@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ['cost_account', 'transaction', 'debit', 'hours', 'date']
    list_filter = ['ledger_account', 'transaction']
    search_fields = ['cost_account', 'description']

@admin.register(IQBLeaveBalance)
class IQBLeaveBalanceAdmin(admin.ModelAdmin):
    list_display = ['employee_code', 'full_name', 'leave_type', 'balance_hours', 'balance_value', 'leave_loading', 'as_of_date']
    list_filter = ['leave_type', 'employment_type', 'as_of_date', 'location']
    search_fields = ['employee_code', 'surname', 'first_name', 'full_name']
    readonly_fields = ['upload', 'as_of_date']

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
            'fields': ('gl_2310_annual_leave', 'gl_2317_long_service_leave', 'gl_2318_toil_liability', 'gl_2320_sick_leave'),
            'classes': ('collapse',),
        }),
        ('Labour Expense GL Accounts (6xxx)', {
            'fields': (
                'gl_6302', 'gl_6305', 'gl_6309', 'gl_6310', 'gl_6312', 'gl_6315',
                'gl_6325', 'gl_6330', 'gl_6331', 'gl_6332', 'gl_6335', 'gl_6338',
                'gl_6340', 'gl_6345_salaries', 'gl_6350', 'gl_6355_sick_leave',
                'gl_6370_superannuation', 'gl_6372_toil', 'gl_6375', 'gl_6380'
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