"""
Models for Labour Reconciliation System
Handles Tanda timesheets, Micropay IQB, Micropay Journal, and Sage Intacct export
"""
from django.db import models
from django.contrib.auth.models import User
import uuid
from datetime import datetime
from decimal import Decimal


class Employee(models.Model):
    """Master employee record - matches master_employee_file.csv format"""
    code = models.CharField(primary_key=True, max_length=20, verbose_name='Employee Code')  # Code column

    # Personal details
    surname = models.CharField(max_length=100)
    first_name = models.CharField(max_length=100, verbose_name='First Name')
    date_of_birth = models.DateField(null=True, blank=True, verbose_name='Date of Birth')

    # Employment details
    location = models.CharField(max_length=200, blank=True)
    employment_type = models.CharField(max_length=50, blank=True, verbose_name='Employment Type')  # e.g., "SF - Salaried Full Time"
    date_hired = models.DateField(null=True, blank=True, verbose_name='Date Hired')
    pay_point = models.CharField(max_length=100, blank=True, verbose_name='Pay Point')
    termination_date = models.DateField(null=True, blank=True, verbose_name='Termination Date')
    job_classification = models.CharField(max_length=200, blank=True, verbose_name='Job Classification')

    # Pay information
    auto_pay = models.CharField(max_length=10, blank=True, verbose_name='Auto Pay')  # "Yes" or "No"
    normal_hours_paid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Normal Hours Paid')
    yearly_salary = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Yearly Salary')
    auto_pay_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Auto Pay Amount')
    award_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Award Rate')
    pay_class_description = models.CharField(max_length=200, blank=True, verbose_name='Pay Class Description')
    normal_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Normal Rate')

    # Cost center
    default_cost_account = models.CharField(max_length=50, blank=True, verbose_name='Default Cost Account')
    default_cost_account_description = models.CharField(max_length=200, blank=True, verbose_name='Default Cost Account Description')

    # Additional information
    notes = models.TextField(blank=True, help_text='Additional notes about this employee')

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['surname', 'first_name']
        indexes = [
            models.Index(fields=['employment_type']),
            models.Index(fields=['location']),
            models.Index(fields=['termination_date']),
        ]
        verbose_name = 'Employee'
        verbose_name_plural = 'Employees'

    def __str__(self):
        return f"{self.code} - {self.surname}, {self.first_name}"

    @property
    def full_name(self):
        """Generate full name from first_name and surname"""
        return f"{self.first_name} {self.surname}".strip()

    @property
    def is_salaried(self):
        """Check if employee is salaried based on auto_pay field"""
        return self.auto_pay == 'Yes'

    @property
    def is_active(self):
        """Check if employee is active (no termination date)"""
        return self.termination_date is None


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
        ('Micropay_IQB_Leave', 'Micropay IQB Leave Balance'),
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
    gl_code = models.CharField(max_length=20, blank=True, default='')  # Direct GL mapping (e.g., "454-30")
    
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


class IQBLeaveBalance(models.Model):
    """Leave balances from Micropay IQB Leave Balance reports"""
    upload = models.ForeignKey(Upload, on_delete=models.CASCADE, related_name='leave_balance_records')

    employee_code = models.CharField(max_length=20, db_index=True)
    surname = models.CharField(max_length=100)
    first_name = models.CharField(max_length=100)
    full_name = models.CharField(max_length=200)
    employment_type = models.CharField(max_length=50)
    location = models.CharField(max_length=100)
    years_of_service = models.DecimalField(max_digits=5, decimal_places=2, default=0, null=True, blank=True)  # For LSL probability calculation

    leave_type = models.CharField(max_length=100, db_index=True)  # 'Annual Leave', 'Long Service Leave', 'User Defined Leave'
    leave_description = models.CharField(max_length=200, blank=True)  # For User Defined Leave, e.g., 'time-in-lieu'
    balance_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    balance_value = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    leave_loading = models.DecimalField(max_digits=15, decimal_places=2, default=0)  # Leave Loading Entitlement & Pro Rata

    as_of_date = models.DateField()  # The date this balance is as of

    class Meta:
        indexes = [
            models.Index(fields=['upload', 'employee_code', 'leave_type']),
            models.Index(fields=['as_of_date', 'leave_type']),
        ]

    def __str__(self):
        return f"{self.employee_code} - {self.leave_type}: {self.balance_hours}hrs / ${self.balance_value}"


class LSLProbability(models.Model):
    """Long Service Leave probability table based on years of service"""
    years_from = models.DecimalField(max_digits=5, decimal_places=2, help_text="Years of service from (inclusive)")
    years_to = models.DecimalField(max_digits=5, decimal_places=2, help_text="Years of service to (inclusive)")
    probability = models.DecimalField(max_digits=5, decimal_places=4, help_text="Probability (0.0000 to 1.0000)")

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['years_from']
        verbose_name = 'LSL Probability'
        verbose_name_plural = 'LSL Probabilities'

    def __str__(self):
        return f"{self.years_from}-{self.years_to} years: {self.probability:.4f}"

    @classmethod
    def get_probability(cls, years_of_service):
        """Get probability for given years of service"""
        if years_of_service is None:
            return Decimal('0')

        prob_record = cls.objects.filter(
            is_active=True,
            years_from__lte=years_of_service,
            years_to__gte=years_of_service
        ).first()

        return prob_record.probability if prob_record else Decimal('0')


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


class IQBTransactionType(models.Model):
    """
    Configuration for IQB transaction types
    Defines which transaction types should be included in hours and costs calculations
    """
    transaction_type = models.CharField(max_length=100, unique=True, verbose_name='Transaction Type')
    include_in_hours = models.BooleanField(default=False, verbose_name='Include in Hours')
    include_in_costs = models.BooleanField(default=False, verbose_name='Include in Costs')
    notes = models.TextField(blank=True, help_text='Description or notes about this transaction type')

    is_active = models.BooleanField(default=True, verbose_name='Active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['transaction_type']
        verbose_name = 'IQB Transaction Type'
        verbose_name_plural = 'IQB Transaction Types'

    def __str__(self):
        return self.transaction_type


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


class SageLocation(models.Model):
    """
    Sage Location master data
    Used for filtering in Cost Allocation View
    """
    location_id = models.CharField(max_length=10, primary_key=True)  # '421', '422', '910', etc.
    location_name = models.CharField(max_length=200)  # 'Marmor', 'Terasu', 'Shared Services', etc.
    parent_id = models.CharField(max_length=10, blank=True)
    parent_name = models.CharField(max_length=200, blank=True)
    manager = models.CharField(max_length=200, blank=True)
    parent_entity = models.CharField(max_length=10, blank=True)
    entity_base_currency = models.CharField(max_length=10, default='AUD')

    class Meta:
        ordering = ['location_id']

    def __str__(self):
        return f"{self.location_id} - {self.location_name}"


class SageDepartment(models.Model):
    """
    Sage Department master data
    Used for filtering in Cost Allocation View
    """
    department_id = models.CharField(max_length=10, primary_key=True)  # '50', '70', '90', etc.
    department_name = models.CharField(max_length=200)  # 'Food', 'Accommodation', 'Finance', etc.
    parent_id = models.CharField(max_length=10, blank=True)
    parent_name = models.CharField(max_length=200, blank=True)
    manager = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['department_id']

    def __str__(self):
        return f"{self.department_id} - {self.department_name}"


class PayCompCodeMapping(models.Model):
    """
    Mapping of Pay Comp/Add Ded Codes to GL Accounts
    Example: 'Normal' -> 6345 (Labour - Salaries)
    """
    pay_comp_code = models.CharField(max_length=50, primary_key=True)
    gl_account = models.CharField(max_length=20)
    gl_name = models.CharField(max_length=200)

    class Meta:
        ordering = ['pay_comp_code']

    def __str__(self):
        return f"{self.pay_comp_code} -> {self.gl_account} ({self.gl_name})"


class FinalizedAllocation(models.Model):
    """
    Finalized cost allocation by Location, Department, and GL Account
    This is the snapshot used for journal generation
    Only one allocation exists per pay period - gets overridden when changes are made
    """
    pay_period = models.ForeignKey(PayPeriod, on_delete=models.CASCADE, related_name='finalized_allocations')

    # Location and Department from cost account code (e.g., 421-5000)
    location_id = models.CharField(max_length=10)  # '421'
    location_name = models.CharField(max_length=200)  # 'Marmor'
    department_id = models.CharField(max_length=10)  # '50'
    department_name = models.CharField(max_length=200)  # 'Food'
    cost_account_code = models.CharField(max_length=20)  # '421-5000'

    # GL Account
    gl_account = models.CharField(max_length=20)  # '6345'
    gl_name = models.CharField(max_length=200)  # 'Labour - Salaries'

    # Amount
    amount = models.DecimalField(max_digits=15, decimal_places=2)

    # Metadata
    employee_count = models.IntegerField(default=0)  # How many employees contribute to this
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['pay_period', 'cost_account_code', 'gl_account']
        indexes = [
            models.Index(fields=['pay_period', 'location_id']),
            models.Index(fields=['pay_period', 'department_id']),
            models.Index(fields=['pay_period', 'gl_account']),
        ]
        ordering = ['location_id', 'department_id', 'gl_account']

    def __str__(self):
        return f"{self.pay_period.period_id} - {self.cost_account_code} - {self.gl_account}: ${self.amount}"


class ValidationResult(models.Model):
    """
    Store validation results for each upload
    Tracks whether the upload passed all validation tests
    """
    upload = models.OneToOneField(Upload, on_delete=models.CASCADE, related_name='validation_result')
    passed = models.BooleanField(default=False)
    validation_data = models.JSONField()  # Stores full validation results
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        status = "PASSED" if self.passed else "FAILED"
        return f"{self.upload.file_name} - {status}"
    
class EmployeePayPeriodSnapshot(models.Model):
    """
    Snapshot of employee's payroll data for each pay period
    Stores finalized cost allocations and GL totals
    """
    # Composite primary key
    pay_period = models.ForeignKey(PayPeriod, on_delete=models.CASCADE, related_name='employee_snapshots')
    employee_code = models.CharField(max_length=20, db_index=True)
    
    # Employee details (denormalized for historical accuracy)
    employee_name = models.CharField(max_length=200)
    employment_status = models.CharField(max_length=50, blank=True)  # Active, Terminated, etc.
    termination_date = models.DateField(null=True, blank=True)
    
    # Finalized cost allocation percentages
    # This is the FINAL allocation after any manual overrides
    # Format: Location-Department structure for Sage export
    cost_allocation = models.JSONField(default=dict)
    # Format: {
    #   '449': {                    # Location
    #     '50': 33.33,             # Department: percentage
    #     '30': 16.67
    #   },
    #   '454': {
    #     '50': 50.00
    #   }
    # }
    
    allocation_source = models.CharField(max_length=20, default='iqb')  # iqb, tanda, override
    allocation_finalized_at = models.DateTimeField(null=True, blank=True)
    allocation_finalized_by = models.ForeignKey(
        'auth.User', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='finalized_allocations'
    )
    
    # GL Account Totals (from IQB)
    # Payroll Liability Accounts (2xxx)
    # Note: Field names may not match GL descriptions due to legacy naming, see mapping in mapping_views.py
    gl_2055_accrued_expenses = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # Accrued Expenses - Employment Related
    gl_2310_annual_leave = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_2317_long_service_leave = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_2318_toil_liability = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_2320_sick_leave = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # Actually WorkCover
    gl_2321_paid_parental = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_2325_leasing = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_2330_long_service_leave = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_2350_net_wages = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_2351_other_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_2360_payg_withholding = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_2391_super_sal_sacrifice = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Labour Expense Accounts (6xxx)
    gl_6300 = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # Annual Leave Accrual
    gl_6302 = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6305 = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6309 = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6310 = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6312 = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6315 = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6325 = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6330 = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6331 = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6332 = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6335 = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6338 = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6340 = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6345_salaries = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6350 = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6355_sick_leave = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6370_superannuation = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6372_toil = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6375 = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gl_6380 = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Leave Balances (end of period) - PLACEHOLDERS FOR NOW
    al_closing_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    al_closing_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    lsl_closing_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    lsl_closing_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    toil_closing_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    toil_closing_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Total cost for this employee this period
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Accrual Wages fields (for month-end accruals)
    accrual_period_start = models.DateField(null=True, blank=True)
    accrual_period_end = models.DateField(null=True, blank=True)
    accrual_days_in_period = models.IntegerField(null=True, blank=True)

    # Accrual amounts
    accrual_base_wages = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    accrual_superannuation = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # 12%
    accrual_annual_leave = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # 7.7% for non-casual or calculated from balances
    accrual_long_service_leave = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # LSL accrual from leave balances
    accrual_toil = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # Time-in-lieu accrual from leave balances
    accrual_payroll_tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # 4.95%
    accrual_workcover = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # 1.384%
    accrual_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # Sum of all accruals

    # Accrual metadata
    accrual_source = models.CharField(max_length=50, blank=True)  # 'tanda_auto_pay' or 'tanda_shift_cost'
    accrual_calculated_at = models.DateTimeField(null=True, blank=True)
    accrual_employee_type = models.CharField(max_length=50, blank=True)  # Store employee type at time of accrual

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['pay_period', 'employee_code']
        ordering = ['-pay_period__period_end', 'employee_code']
        indexes = [
            models.Index(fields=['pay_period', 'employee_code']),
            models.Index(fields=['employee_code', 'pay_period']),  # For employee history
            models.Index(fields=['termination_date']),
        ]
        verbose_name = 'Employee Pay Period Snapshot'
        verbose_name_plural = 'Employee Pay Period Snapshots'
    
    def __str__(self):
        return f"{self.employee_name} ({self.employee_code}) - {self.pay_period.period_id}"
    
    def validate_allocation(self):
        """Validate that cost allocations sum to 100%"""
        if not self.cost_allocation:
            return False, "No allocations defined"
        
        # Sum all percentages across all locations and departments
        total = Decimal('0')
        for location, departments in self.cost_allocation.items():
            for dept, percentage in departments.items():
                total += Decimal(str(percentage))
        
        if abs(total - 100) > 0.01:  # 0.01% tolerance
            return False, f"Allocations sum to {total}%, not 100%"
        
        return True, "Valid"
    
    def get_allocation_by_location_dept(self, location_id, dept_id):
        """
        Get allocation percentage for a specific location-department
        
        Args:
            location_id: e.g., '449'
            dept_id: e.g., '50'
        
        Returns:
            float: Percentage (0-100)
        """
        return self.cost_allocation.get(location_id, {}).get(dept_id, 0)
    
    def calculate_allocated_amount(self, gl_amount, location_id, dept_id):
        """
        Calculate allocated amount for a location-department
        
        Args:
            gl_amount: Total GL amount to allocate
            location_id: e.g., '449'
            dept_id: e.g., '50'
        
        Returns:
            Decimal: Allocated amount
        """
        percentage = self.get_allocation_by_location_dept(location_id, dept_id)
        return Decimal(str(gl_amount)) * Decimal(str(percentage)) / 100
    
    def get_all_location_dept_combinations(self):
        """
        Get all location-department combinations with their percentages
        
        Returns:
            list: [{'location': '449', 'department': '50', 'percentage': 33.33}, ...]
        """
        combinations = []
        for location, departments in self.cost_allocation.items():
            for dept, percentage in departments.items():
                combinations.append({
                    'location': location,
                    'department': dept,
                    'percentage': percentage
                })
        return combinations
    
    def get_allocation_summary(self):
        """
        Get human-readable allocation summary
        
        Returns:
            str: e.g., "Location 449, Dept 50: 33.33%; Location 454, Dept 50: 66.67%"
        """
        parts = []
        for location, departments in sorted(self.cost_allocation.items()):
            for dept, percentage in sorted(departments.items()):
                parts.append(f"Location {location}, Dept {dept}: {percentage}%")
        return "; ".join(parts)
    
    def get_gl_totals(self):
        """
        Get all GL account totals as a dictionary
        
        Returns:
            dict: GL account totals
        """
        return {
            '2310': {
                'name': 'Payroll Liab - Annual Leave',
                'amount': self.gl_2310_annual_leave
            },
            '6345': {
                'name': 'Labour - Salaries',
                'amount': self.gl_6345_salaries
            },
            '6355': {
                'name': 'Labour - Sick Leave',
                'amount': self.gl_6355_sick_leave
            },
            '6370': {
                'name': 'Labour - Superannuation',
                'amount': self.gl_6370_superannuation
            },
            '6372': {
                'name': 'Labour - Time in Lieu',
                'amount': self.gl_6372_toil
            }
        }