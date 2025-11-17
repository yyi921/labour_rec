from django.contrib import admin
from .models import (
    PayPeriod, Upload, TandaTimesheet, IQBDetail, JournalEntry,
    CostCenterSplit, ReconciliationRun, ReconciliationItem,
    ExceptionResolution, LabourCostSummary, SageIntacctExport
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