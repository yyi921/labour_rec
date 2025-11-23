from django.contrib import admin
from .models import (
    PayPeriod, Upload, TandaTimesheet, IQBDetail, JournalEntry,
    CostCenterSplit, ReconciliationRun, ReconciliationItem,
    ExceptionResolution, LabourCostSummary, SageIntacctExport,
    EmployeeReconciliation, JournalReconciliation, LocationMapping
)

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