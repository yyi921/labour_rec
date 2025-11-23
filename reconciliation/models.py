"""
Models for Labour Reconciliation System
Handles Tanda timesheets, Micropay IQB, Micropay Journal, and Sage Intacct export
"""
from django.db import models
from django.contrib.auth.models import User
import uuid
from datetime import datetime
from decimal import Decimal


class PayPeriod(models.Model):
    """Master table tracking pay periods"""
    period_id = models.CharField(primary_key=True, max_length=20)  # '2025-10-05' (ending date)
    period_start = models.DateField(null=True, blank=True)  # Nullable for Journal-only periods
    period_end = models.DateField()
    period_type = models.CharField(max_length=20, default='fortnightly')
    
    # Track upload status
    has_tanda = models.BooleanField(default=False)
    has_iqb = models.BooleanField(default=False)
    has_journal = models.BooleanField(default=False)
    has_cost_allocation = models.BooleanField(default=False)
    
    # Reconciliation status
    STATUS_CHOICES = [
        ('incomplete', 'Incomplete - Missing Files'),
        ('uploaded', 'Files Uploaded'),
        ('reconciling', 'Reconciliation Running'),
        ('review', 'Under Review - Exceptions Found'),
        ('approved', 'Approved'),
        ('posted', 'Posted to Sage Intacct'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='incomplete')
    
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-period_end']
    
    def __str__(self):
        return f"Pay Period ending {self.period_end}"


class Upload(models.Model):
    """Track all file uploads with versioning"""
    upload_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    pay_period = models.ForeignKey(PayPeriod, on_delete=models.CASCADE, related_name='uploads')
    
    SOURCE_CHOICES = [
        ('Tanda_Timesheet', 'Tanda Timesheet'),
        ('Micropay_IQB', 'Micropay IQB Report'),
        ('Micropay_Journal', 'Micropay GL Journal'),
    ]
    source_system = models.CharField(max_length=50, choices=SOURCE_CHOICES)
    
    file_name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500)
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    # Versioning
    version = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)
    replaced_by = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL)
    
    record_count = models.IntegerField(default=0)
    
    STATUS_CHOICES = [
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('superseded', 'Superseded by newer version'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='processing')
    error_message = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(fields=['pay_period', 'source_system', 'is_active']),
        ]
    
    def __str__(self):
        return f"{self.source_system} - {self.pay_period} (v{self.version})"


class TandaTimesheet(models.Model):
    """Timesheet data from Tanda"""
    upload = models.ForeignKey(Upload, on_delete=models.CASCADE, related_name='tanda_records')
    
    employee_id = models.CharField(max_length=20, db_index=True)
    employee_name = models.CharField(max_length=200)
    employment_type = models.CharField(max_length=50)
    
    location_name = models.CharField(max_length=200)  # Maps to cost center
    team_name = models.CharField(max_length=200)
    award_export_name = models.CharField(max_length=100)  # Leave type indicator
    
    date_shift_start = models.DateField(null=True, blank=True)
    shift_start_time = models.TimeField(null=True, blank=True)
    date_shift_finish = models.DateField(null=True, blank=True)
    shift_finish_time = models.TimeField(null=True, blank=True)
    
    shift_hours = models.DecimalField(max_digits=8, decimal_places=4)
    shift_cost = models.DecimalField(max_digits=12, decimal_places=4)
    
    # Derived fields
    is_leave = models.BooleanField(default=False)  # True if award_export_name contains leave
    leave_type = models.CharField(max_length=50, blank=True)  # 'AnnualLeave', 'SickLeave', etc.
    
    class Meta:
        indexes = [
            models.Index(fields=['upload', 'employee_id']),
            models.Index(fields=['location_name']),
        ]
    
    def save(self, *args, **kwargs):
        # Auto-detect leave types
        leave_keywords = {
            'AnnualLeave': 'Annual Leave',
            'SickLeave': 'Sick Leave',
            'TIL': 'Time in Lieu',
            'LSL': 'Long Service Leave',
            'PHTIL': 'Public Holiday TIL',
        }
        
        for key, value in leave_keywords.items():
            if key.lower() in self.award_export_name.lower():
                self.is_leave = True
                self.leave_type = value
                break
        
        super().save(*args, **kwargs)


class IQBDetail(models.Model):
    """Detailed employee costing from Micropay IQB report"""
    upload = models.ForeignKey(Upload, on_delete=models.CASCADE, related_name='iqb_records')
    
    # Employee info
    employee_code = models.CharField(max_length=20, db_index=True)
    surname = models.CharField(max_length=100)
    first_name = models.CharField(max_length=100)
    full_name = models.CharField(max_length=200)
    employment_type = models.CharField(max_length=50)
    location = models.CharField(max_length=200)
    
    # Cost center
    cost_account_code = models.CharField(max_length=50, db_index=True)
    cost_account_description = models.CharField(max_length=200)
    
    # Transaction details
    pay_comp_code = models.CharField(max_length=50)  # 'Normal', 'Annual', 'Sick', 'Tax', 'Super'
    pay_comp_desc = models.CharField(max_length=200)
    transaction_type = models.CharField(max_length=50)  # 'Hours By Rate', 'Annual Leave', 'Super', 'Tax'
    
    hours = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    
    # Additional fields for leave
    leave_start_date = models.DateField(null=True, blank=True)
    leave_end_date = models.DateField(null=True, blank=True)
    
    # Loading for annual leave
    loading_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    class Meta:
        indexes = [
            models.Index(fields=['upload', 'employee_code']),
            models.Index(fields=['cost_account_code']),
            models.Index(fields=['transaction_type']),
        ]
    
    def __str__(self):
        return f"{self.employee_code} - {self.transaction_type}: ${self.amount}"


class JournalEntry(models.Model):
    """GL Journal entries from Micropay"""
    upload = models.ForeignKey(Upload, on_delete=models.CASCADE, related_name='journal_records')
    
    batch = models.CharField(max_length=20)
    date = models.DateField()
    ledger_account = models.CharField(max_length=20)  # e.g., '-6345' for Labour
    cost_account = models.CharField(max_length=50, db_index=True)  # e.g., '470-6800'
    description = models.CharField(max_length=200)
    transaction = models.CharField(max_length=50)  # 'Normal', 'E1020025', '22T', etc.
    
    debit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    class Meta:
        indexes = [
            models.Index(fields=['upload', 'cost_account']),
            models.Index(fields=['ledger_account']),
        ]
    
    def __str__(self):
        return f"{self.cost_account} - {self.transaction}: ${self.debit}"


class CostCenterSplit(models.Model):
    """Cost center allocation rules from Split_Data.csv"""
    source_account = models.CharField(max_length=50, db_index=True)  # 'SPL-CHEF'
    target_account = models.CharField(max_length=50)  # '458-50'
    percentage = models.DecimalField(max_digits=5, decimal_places=4)  # 0.075 = 7.5%
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['source_account', 'target_account']
    
    def __str__(self):
        return f"{self.source_account} → {self.target_account} ({self.percentage*100}%)"


class ReconciliationRun(models.Model):
    """Track reconciliation execution"""
    run_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    pay_period = models.ForeignKey(PayPeriod, on_delete=models.CASCADE, related_name='recon_runs')
    
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    STATUS_CHOICES = [
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running')
    
    # Summary stats
    total_checks = models.IntegerField(default=0)
    checks_passed = models.IntegerField(default=0)
    checks_failed = models.IntegerField(default=0)
    critical_exceptions = models.IntegerField(default=0)
    warnings = models.IntegerField(default=0)
    
    error_message = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-started_at']


class ReconciliationItem(models.Model):
    """Individual reconciliation exceptions"""
    item_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    recon_run = models.ForeignKey(ReconciliationRun, on_delete=models.CASCADE, related_name='items')
    
    RECON_TYPE_CHOICES = [
        ('hours', 'Hours Reconciliation: Tanda vs IQB'),
        ('cost', 'Cost Reconciliation: IQB vs Journal'),
        ('completeness', 'Completeness Check'),
    ]
    recon_type = models.CharField(max_length=20, choices=RECON_TYPE_CHOICES)
    
    employee_id = models.CharField(max_length=20, blank=True, db_index=True)
    employee_name = models.CharField(max_length=200, blank=True)
    cost_center = models.CharField(max_length=50, blank=True)
    
    expected_value = models.DecimalField(max_digits=15, decimal_places=2, null=True)
    actual_value = models.DecimalField(max_digits=15, decimal_places=2, null=True)
    variance = models.DecimalField(max_digits=15, decimal_places=2, null=True)
    variance_pct = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    
    description = models.TextField()
    
    SEVERITY_CHOICES = [
        ('critical', 'Critical - Requires Action'),
        ('warning', 'Warning - Review Recommended'),
        ('info', 'Information Only'),
    ]
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('under_review', 'Under Review'),
        ('resolved', 'Resolved'),
        ('accepted', 'Accepted - No Action Required'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    
    resolution_notes = models.TextField(blank=True)
    resolved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['recon_run', 'status']),
            models.Index(fields=['severity']),
        ]


class ExceptionResolution(models.Model):
    """Track chat-based modifications with audit trail"""
    resolution_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    reconciliation_item = models.ForeignKey(ReconciliationItem, on_delete=models.CASCADE, related_name='resolutions')
    
    # User interaction
    user_message = models.TextField()  # What user typed in chat
    interpreted_action = models.JSONField()  # Claude's interpretation
    
    # Changes made
    MODIFICATION_TYPES = [
        ('note_added', 'Note Added'),
        ('allocation_changed', 'Cost Allocation Changed'),
        ('hours_adjusted', 'Hours Adjusted'),
        ('cost_adjusted', 'Cost Adjusted'),
        ('employee_reassigned', 'Employee Reassigned'),
        ('accepted_variance', 'Variance Accepted'),
    ]
    modification_type = models.CharField(max_length=50, choices=MODIFICATION_TYPES)
    
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    
    # Audit trail
    modified_by = models.ForeignKey(User, on_delete=models.PROTECT)
    modified_at = models.DateTimeField(auto_now_add=True)
    
    approval_status = models.CharField(max_length=20, default='pending')
    approved_by = models.ForeignKey(User, null=True, blank=True, related_name='approvals', on_delete=models.SET_NULL)
    
    # Impact tracking
    triggered_rerun = models.BooleanField(default=False)
    rerun_timestamp = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-modified_at']


class LabourCostSummary(models.Model):
    """Aggregated labour costs by employee and cost center - for reporting"""
    pay_period = models.ForeignKey(PayPeriod, on_delete=models.CASCADE, related_name='cost_summaries')
    
    employee_code = models.CharField(max_length=20, db_index=True)
    employee_name = models.CharField(max_length=200)
    cost_account_code = models.CharField(max_length=50, db_index=True)
    
    # Cost breakdown by type
    normal_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    overtime_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    penalty_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Leave costs
    annual_leave = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    annual_leave_loading = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sick_leave = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    lsl = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_leave = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # On-costs
    superannuation = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    workcover = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # Phase 2
    payroll_tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # Phase 2
    
    # Totals
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['pay_period', 'employee_code', 'cost_account_code']
        indexes = [
            models.Index(fields=['pay_period', 'cost_account_code']),
        ]


class SageIntacctExport(models.Model):
    """Track exports to Sage Intacct"""
    export_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    pay_period = models.ForeignKey(PayPeriod, on_delete=models.CASCADE, related_name='exports')
    
    file_path = models.CharField(max_length=500)
    exported_by = models.ForeignKey(User, on_delete=models.PROTECT)
    exported_at = models.DateTimeField(auto_now_add=True)
    
    record_count = models.IntegerField(default=0)
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    STATUS_CHOICES = [
        ('generated', 'Generated - Ready for Upload'),
        ('uploaded', 'Uploaded to Sage Intacct'),
        ('posted', 'Posted in Sage Intacct'),
        ('failed', 'Failed'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='generated')
    
    class Meta:
        ordering = ['-exported_at']

class EmployeeReconciliation(models.Model):
    """
    Joint reconciliation view combining Tanda and IQB data by employee
    Provides foundation for budget/forecast analysis
    """
    pay_period = models.ForeignKey(PayPeriod, on_delete=models.CASCADE, related_name='employee_reconciliations', null=True, blank=True)
    recon_run = models.ForeignKey(ReconciliationRun, on_delete=models.CASCADE, related_name='employee_recons')

    employee_id = models.CharField(max_length=20, db_index=True)
    employee_name = models.CharField(max_length=200)
    employment_type = models.CharField(max_length=100, blank=True)  # From IQB

    # Auto Pay for salaried employees
    is_salaried = models.BooleanField(default=False)
    auto_pay_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Tanda data (actual worked)
    tanda_total_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tanda_total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tanda_shift_count = models.IntegerField(default=0)
    tanda_earliest_shift = models.DateTimeField(null=True, blank=True)
    tanda_latest_shift = models.DateTimeField(null=True, blank=True)
    tanda_locations = models.JSONField(default=list)  # List of locations worked
    
    # Tanda breakdown by type
    tanda_normal_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tanda_leave_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tanda_leave_breakdown = models.JSONField(default=dict)  # {'Annual Leave': 8, 'Sick Leave': 4}
    
    # IQB data (paid)
    iqb_total_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    iqb_gross_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    iqb_superannuation = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    iqb_total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # IQB breakdown by transaction type
    iqb_normal_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    iqb_normal_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    iqb_overtime_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    iqb_overtime_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    iqb_annual_leave_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    iqb_annual_leave_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    iqb_sick_leave_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    iqb_sick_leave_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    iqb_other_leave_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    iqb_other_leave_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Cost centers worked (for multi-CC employees)
    cost_centers = models.JSONField(default=list)  # ['470-6800', '910-9300']
    
    # Variances
    hours_variance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    hours_variance_pct = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    cost_variance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cost_variance_pct = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    
    # Reconciliation status
    hours_match = models.BooleanField(default=False)
    cost_match = models.BooleanField(default=False)
    has_issues = models.BooleanField(default=False)
    issue_description = models.TextField(blank=True)
    
    class Meta:
        unique_together = ['pay_period', 'employee_id']
        indexes = [
            models.Index(fields=['pay_period', 'has_issues']),
            models.Index(fields=['recon_run', 'has_issues']),
            models.Index(fields=['employee_id']),
        ]

    def __str__(self):
        return f"{self.employee_id} - {self.employee_name} (Period: {self.pay_period.period_id})"


class JournalReconciliation(models.Model):
    """
    Reconciliation of IQB vs Journal entries by description
    """
    recon_run = models.ForeignKey(ReconciliationRun, on_delete=models.CASCADE, related_name='journal_recons')

    description = models.CharField(max_length=200, db_index=True)
    gl_account = models.CharField(max_length=20, blank=True)
    include_in_total_cost = models.BooleanField(default=False)
    is_mapped = models.BooleanField(default=True)  # False if missing from mapping

    # Journal amounts (debit - credit)
    journal_debit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    journal_credit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    journal_net = models.DecimalField(max_digits=15, decimal_places=2, default=0)  # debit - credit

    class Meta:
        unique_together = ['recon_run', 'description']
        ordering = ['description']

    def __str__(self):
        return f"{self.description}: ${self.journal_net:,.2f}"
    



class CostAllocationRule(models.Model):
    """
    Cost allocation rules for employees
    Can be sourced from: IQB, Tanda, or Manual Override
    """
    pay_period = models.ForeignKey(PayPeriod, on_delete=models.CASCADE, related_name='allocation_rules')
    employee_code = models.CharField(max_length=20, db_index=True)
    employee_name = models.CharField(max_length=200)
    
    # Source of allocation
    SOURCE_CHOICES = [
        ('iqb', 'IQB Default'),
        ('tanda', 'Tanda Timesheet'),
        ('override', 'Manual Override'),
    ]
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='iqb')
    
    # Allocation details
    allocations = models.JSONField(default=dict)
    # Format: {
    #   '449-5000': {'percentage': 0.33, 'amount': 1234.56, 'source': 'tanda'},
    #   '454-5000': {'percentage': 0.67, 'amount': 2345.67, 'source': 'tanda'}
    # }
    
    # Validation
    total_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    is_valid = models.BooleanField(default=False)
    validation_errors = models.JSONField(default=list)
    
    # Tracking
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        'auth.User', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='allocation_updates'
    )
    
    class Meta:
        unique_together = ['pay_period', 'employee_code']
        indexes = [
            models.Index(fields=['pay_period', 'source']),
            models.Index(fields=['employee_code']),
        ]
    
    def __str__(self):
        return f"{self.employee_code} - {self.employee_name} ({self.pay_period.period_id})"
    
    def validate_allocations(self):
        """Validate that allocations sum to 100%"""
        errors = []
        
        if not self.allocations:
            errors.append("No allocations defined")
            self.is_valid = False
            self.validation_errors = errors
            return False
        
        total_pct = sum(alloc['percentage'] for alloc in self.allocations.values())
        self.total_percentage = Decimal(str(total_pct))

        # Allow 0.05% tolerance for rounding
        if abs(total_pct - 100) > 0.05:
            errors.append(f"Allocations sum to {total_pct}%, not 100%")
        
        # Check for invalid cost accounts
        for cost_account in self.allocations.keys():
            if not cost_account or '-' not in cost_account:
                errors.append(f"Invalid cost account format: {cost_account}")
        
        self.is_valid = len(errors) == 0
        self.validation_errors = errors
        return self.is_valid


class LocationMapping(models.Model):
    """
    Maps Tanda location names to cost account codes
    Example: 'TSV - OPH Chef' -> '449-5000'
    """
    tanda_location = models.CharField(max_length=200, unique=True)
    cost_account_code = models.CharField(max_length=20)
    department_code = models.CharField(max_length=10)  # e.g., '50' for Food
    department_name = models.CharField(max_length=100)  # e.g., 'Food'
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['tanda_location']
    
    def __str__(self):
        return f"{self.tanda_location} -> {self.cost_account_code}"


class DepartmentCostSummary(models.Model):
    """
    Department-level cost summary by GL account
    Used for verification view
    """
    pay_period = models.ForeignKey(PayPeriod, on_delete=models.CASCADE, related_name='dept_summaries')
    department_code = models.CharField(max_length=10)  # '30', '50', '70', etc.
    department_name = models.CharField(max_length=100)  # 'Beverage', 'Food', 'Accommodation'
    
    # GL accounts
    gl_account = models.CharField(max_length=20)  # '6345', '6370', '6300', etc.
    gl_account_name = models.CharField(max_length=100)  # 'Salaries', 'Superannuation', 'Annual Leave'
    
    # Totals
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    employee_count = models.IntegerField(default=0)
    
    # Breakdown by cost center within department
    cost_center_breakdown = models.JSONField(default=dict)
    # Format: {'449-5000': 12345.67, '454-5000': 23456.78}
    
    class Meta:
        unique_together = ['pay_period', 'department_code', 'gl_account']
        indexes = [
            models.Index(fields=['pay_period', 'department_code']),
        ]
    
    def __str__(self):
        return f"{self.department_name} - {self.gl_account_name} ({self.pay_period.period_id})"