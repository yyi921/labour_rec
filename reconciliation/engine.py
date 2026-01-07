"""
Enhanced Reconciliation Engine - Joint database approach
"""
from django.db.models import Sum, Q, Count, Min, Max
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import decimal
import pytz
import pandas as pd
import os
from reconciliation.models import (
    PayPeriod, Upload, TandaTimesheet, IQBDetail, JournalEntry,
    CostCenterSplit, ReconciliationRun, ReconciliationItem,
    EmployeeReconciliation, JournalReconciliation
)


class ReconciliationEngine:
    """
    Enhanced three-way reconciliation with joint database
    """

    def __init__(self, pay_period):
        self.pay_period = pay_period
        self.recon_run = None
        self.exceptions = []
        self.employee_recons = []

        # Load allowed transaction types from configuration
        self.allowed_transaction_types = self._load_transaction_type_config()

        # Load master employee file
        self.master_employees = self._load_master_employee_file()

        # Load journal mapping
        self.journal_mapping = self._load_journal_mapping()

    def _load_transaction_type_config(self):
        """
        Load IQB transaction type configuration from database

        Returns:
            dict: {
                'hours': list of transaction types to include in hours calculation,
                'costs': list of transaction types to include in costs calculation
            }
        """
        try:
            from .models import IQBTransactionType

            # Get active transaction types from database
            transaction_types = IQBTransactionType.objects.filter(is_active=True)

            # Get transaction types for hours (include_in_hours = True)
            hours_types = list(transaction_types.filter(include_in_hours=True).values_list('transaction_type', flat=True))

            # Get transaction types for costs (include_in_costs = True)
            costs_types = list(transaction_types.filter(include_in_costs=True).values_list('transaction_type', flat=True))

            return {
                'hours': hours_types,
                'costs': costs_types
            }
        except Exception as e:
            print(f"Warning: Could not load transaction type config from database: {e}")
            print("Using default transaction types")
            # Fallback to default list
            return {
                'hours': [
                    'Annual Leave', 'Auto Pay', 'Hours By Rate', 'Long Service Leave',
                    'Other Leave', 'Sick Leave', 'Term Post 93 AL Gross',
                    'Term Post 93 LL Gross', 'User Defined Leave'
                ],
                'costs': [
                    'Annual Leave', 'Auto Pay', 'Hours By Rate', 'Long Service Leave',
                    'Non Standard Add Before', 'Other Leave', 'Sick Leave',
                    'Standard Add Before', 'Super', 'Term ETP - Taxable (Code: O)',
                    'Term Post 93 AL Gross', 'Term Post 93 LL Gross', 'User Defined Leave'
                ]
            }

    def _load_master_employee_file(self):
        """
        Load master employee file with auto pay information

        Returns:
            dict: {employee_code: {
                'employment_type': str,
                'is_salaried': bool,
                'auto_pay_amount': Decimal
            }}
        """
        config_path = os.path.join('data', 'master_employee_file.csv')

        try:
            df = pd.read_csv(config_path)

            employees = {}
            for _, row in df.iterrows():
                emp_code = str(row.get('Code', '')).strip()
                if not emp_code:
                    continue

                employment_type = str(row.get('Employment Type', '')).strip()
                auto_pay = str(row.get('Auto Pay', '')).strip().upper()
                auto_pay_amount_raw = row.get('Auto Pay Amount', 0)

                # Determine if salaried (Employment Type contains "Salaried" or "SF")
                is_salaried = 'SALARIED' in employment_type.upper() or employment_type.startswith('SF')

                # Parse auto pay amount (handle currency symbols, commas, etc.)
                auto_pay_amount = Decimal('0')
                if pd.notna(auto_pay_amount_raw) and auto_pay_amount_raw != '':
                    try:
                        # Remove currency symbols and commas
                        clean_amount = str(auto_pay_amount_raw).replace('$', '').replace(',', '').strip()
                        auto_pay_amount = Decimal(clean_amount)
                    except (ValueError, decimal.InvalidOperation):
                        pass  # Keep as 0 if conversion fails

                employees[emp_code] = {
                    'employment_type': employment_type,
                    'is_salaried': is_salaried and auto_pay == 'YES',
                    'auto_pay_amount': auto_pay_amount
                }

            print(f"Loaded {len(employees)} employees from master file")
            return employees

        except Exception as e:
            print(f"Warning: Could not load master employee file from {config_path}: {e}")
            return {}

    def _load_journal_mapping(self):
        """
        Load journal mapping from database (JournalDescriptionMapping model)

        Returns:
            dict: {description: {
                'gl_account': str,
                'include_in_total_cost': bool
            }}
        """
        from reconciliation.models import JournalDescriptionMapping

        try:
            # Load from database
            mappings = JournalDescriptionMapping.objects.filter(is_active=True)

            mapping = {}
            for m in mappings:
                mapping[m.description] = {
                    'gl_account': m.gl_account,
                    'include_in_total_cost': m.include_in_total_cost
                }

            print(f"Loaded {len(mapping)} journal mappings from database")

            # If database is empty, try CSV as fallback
            if not mapping:
                config_path = os.path.join('data', 'Micropay_journal_mapping.csv')
                df = pd.read_csv(config_path)

                for _, row in df.iterrows():
                    description = str(row.get('Description', '')).strip()
                    if not description:
                        continue

                    gl_account = str(row.get('GL Account', '')).strip()
                    total_cost = str(row.get('Total Cost', '')).strip().upper()

                    mapping[description] = {
                        'gl_account': gl_account,
                        'include_in_total_cost': total_cost == 'Y'
                    }

                print(f"Loaded {len(mapping)} journal mappings from CSV fallback")

            return mapping

        except Exception as e:
            print(f"Warning: Could not load journal mapping: {e}")
            return {}

    def run_reconciliation(self):
        """
        Run complete reconciliation for the pay period
        """
        # Delete existing employee reconciliations for this pay period
        # This ensures we don't have duplicates when re-running reconciliation
        deleted_emp_count = EmployeeReconciliation.objects.filter(
            pay_period=self.pay_period
        ).delete()[0]

        if deleted_emp_count > 0:
            print(f"Deleted {deleted_emp_count} existing employee reconciliation records for period {self.pay_period.period_id}")

        # Create reconciliation run
        self.recon_run = ReconciliationRun.objects.create(
            pay_period=self.pay_period,
            status='running'
        )

        # Delete existing journal reconciliations for this recon run's pay period
        # (since recon_run is linked to pay_period, we can clean up old journal recons)
        deleted_journal_count = JournalReconciliation.objects.filter(
            recon_run__pay_period=self.pay_period
        ).delete()[0]

        if deleted_journal_count > 0:
            print(f"Deleted {deleted_journal_count} existing journal reconciliation records for period {self.pay_period.period_id}")

        try:
            # Build joint employee reconciliation database
            self._build_employee_reconciliation()

            # Run all checks
            self._check_employee_hours_and_costs()
            self._check_cost_center_totals()
            self._check_completeness()

            # Bulk create employee reconciliations
            EmployeeReconciliation.objects.bulk_create(self.employee_recons)

            # Reconcile journal entries
            self._reconcile_journal_entries()

            # Calculate summary stats
            total_checks = len(self.exceptions)
            critical = sum(1 for e in self.exceptions if e.severity == 'critical')
            warnings = sum(1 for e in self.exceptions if e.severity == 'warning')
            passed = total_checks - critical - warnings
            
            # Update run status
            self.recon_run.status = 'completed'
            self.recon_run.completed_at = timezone.now()
            self.recon_run.total_checks = total_checks
            self.recon_run.checks_passed = passed
            self.recon_run.checks_failed = critical + warnings
            self.recon_run.critical_exceptions = critical
            self.recon_run.warnings = warnings
            self.recon_run.save()
            
            # Bulk create all exceptions
            ReconciliationItem.objects.bulk_create(self.exceptions)
            
            # Update pay period status
            if critical > 0:
                self.pay_period.status = 'review'
            elif warnings > 0:
                self.pay_period.status = 'review'
            else:
                self.pay_period.status = 'uploaded'
            self.pay_period.save()
            
            return self.recon_run
            
        except Exception as e:
            self.recon_run.status = 'failed'
            self.recon_run.error_message = str(e)
            self.recon_run.save()
            raise
    
    def _build_employee_reconciliation(self):
        """
        Build joint reconciliation database combining Tanda and IQB data
        This creates a unified view for each employee with all relevant data
        """
        # Get active uploads
        tanda_upload = Upload.objects.filter(
            pay_period=self.pay_period,
            source_system='Tanda_Timesheet',
            is_active=True
        ).first()
        
        iqb_upload = Upload.objects.filter(
            pay_period=self.pay_period,
            source_system='Micropay_IQB',
            is_active=True
        ).first()
        
        if not tanda_upload or not iqb_upload:
            return
        
        # Get all unique employees from both systems
        tanda_employees = set(TandaTimesheet.objects.filter(
            upload=tanda_upload
        ).values_list('employee_id', flat=True).distinct())
        
        iqb_employees = set(IQBDetail.objects.filter(
            upload=iqb_upload
        ).values_list('employee_code', flat=True).distinct())
        
        all_employees = tanda_employees | iqb_employees
        
        # Build reconciliation for each employee
        for emp_id in all_employees:
            emp_recon = self._build_employee_data(emp_id, tanda_upload, iqb_upload)
            self.employee_recons.append(emp_recon)
    
    def _build_employee_data(self, emp_id, tanda_upload, iqb_upload):
        """
        Build comprehensive employee reconciliation data
        """
        emp_recon = EmployeeReconciliation(
            pay_period=self.pay_period,
            recon_run=self.recon_run,
            employee_id=emp_id
        )
        
        # Get Tanda data
        tanda_records = TandaTimesheet.objects.filter(
            upload=tanda_upload,
            employee_id=emp_id
        )
        
        if tanda_records.exists():
            # Basic totals
            tanda_totals = tanda_records.aggregate(
                total_hours=Sum('shift_hours'),
                total_cost=Sum('shift_cost'),
                shift_count=Count('id')
            )
            
            emp_recon.employee_name = tanda_records.first().employee_name
            emp_recon.tanda_total_hours = tanda_totals['total_hours'] or 0
            emp_recon.tanda_total_cost = tanda_totals['total_cost'] or 0
            emp_recon.tanda_shift_count = tanda_totals['shift_count'] or 0
            
            # Get shift date range (for future scheduling optimization)
            shifts_with_dates = tanda_records.filter(
                date_shift_start__isnull=False,
                shift_start_time__isnull=False
            )
            
            if shifts_with_dates.exists():
                earliest = shifts_with_dates.aggregate(
                    min_date=Min('date_shift_start'),
                    min_time=Min('shift_start_time')
                )
                latest = shifts_with_dates.aggregate(
                    max_date=Max('date_shift_finish'),
                    max_time=Max('shift_finish_time')
                )
                
                # Combine date and time for earliest shift
                if earliest['min_date'] and earliest['min_time']:
                    naive_dt = datetime.combine(
                        earliest['min_date'],
                        earliest['min_time']
                    )
                    emp_recon.tanda_earliest_shift = timezone.make_aware(naive_dt)

                # Combine date and time for latest shift
                if latest['max_date'] and latest['max_time']:
                    naive_dt = datetime.combine(
                        latest['max_date'],
                        latest['max_time']
                    )
                    emp_recon.tanda_latest_shift = timezone.make_aware(naive_dt)
            
            # Get unique locations (for multi-location employees)
            locations = list(tanda_records.values_list(
                'location_name', flat=True
            ).distinct())
            emp_recon.tanda_locations = locations
            
            # Breakdown by leave type
            normal_hours = tanda_records.filter(is_leave=False).aggregate(
                hours=Sum('shift_hours')
            )['hours'] or 0
            
            leave_hours = tanda_records.filter(is_leave=True).aggregate(
                hours=Sum('shift_hours')
            )['hours'] or 0
            
            emp_recon.tanda_normal_hours = normal_hours
            emp_recon.tanda_leave_hours = leave_hours
            
            # Detailed leave breakdown
            leave_breakdown = {}
            for leave_type in ['Annual Leave', 'Sick Leave', 'Long Service Leave', 'Time in Lieu']:
                hours = tanda_records.filter(leave_type=leave_type).aggregate(
                    hours=Sum('shift_hours')
                )['hours']
                if hours:
                    leave_breakdown[leave_type] = float(hours)
            
            emp_recon.tanda_leave_breakdown = leave_breakdown
        
        # Get IQB data
        iqb_records = IQBDetail.objects.filter(
            upload=iqb_upload,
            employee_code=emp_id
        )

        if iqb_records.exists():
            if not emp_recon.employee_name:
                emp_recon.employee_name = iqb_records.first().full_name

            # Get employment type from IQB
            emp_recon.employment_type = iqb_records.first().employment_type

            # Get cost centers this employee worked in
            cost_centers = list(iqb_records.values_list(
                'cost_account_code', flat=True
            ).distinct())
            emp_recon.cost_centers = cost_centers

            # Get auto pay information from master employee file
            if emp_id in self.master_employees:
                master_info = self.master_employees[emp_id]
                emp_recon.is_salaried = master_info['is_salaried']
                emp_recon.auto_pay_amount = master_info['auto_pay_amount']
                # Override employment type from master file if available
                if master_info['employment_type']:
                    emp_recon.employment_type = master_info['employment_type']

            # Filter records for hours calculation (only allowed transaction types)
            hours_records = iqb_records.filter(
                transaction_type__in=self.allowed_transaction_types['hours']
            )
            emp_recon.iqb_total_hours = hours_records.aggregate(
                hours=Sum('hours')
            )['hours'] or 0
            
            # Normal pay and hours (Hours By Rate + Normal)
            normal = iqb_records.filter(
                transaction_type='Hours By Rate',
                pay_comp_code='Normal'
            ).aggregate(
                amount=Sum('amount'),
                hours=Sum('hours')
            )
            emp_recon.iqb_normal_pay = normal['amount'] or 0
            emp_recon.iqb_normal_hours = normal['hours'] or 0
            
            # Overtime/penalty rates (Hours By Rate + penalty codes)
            overtime = iqb_records.filter(
                transaction_type='Hours By Rate'
            ).exclude(
                pay_comp_code='Normal'
            ).aggregate(
                amount=Sum('amount'),
                hours=Sum('hours')
            )
            emp_recon.iqb_overtime_pay = overtime['amount'] or 0
            emp_recon.iqb_overtime_hours = overtime['hours'] or 0
            
            # Annual leave
            annual = iqb_records.filter(
                transaction_type='Annual Leave'
            ).aggregate(
                amount=Sum('amount'),
                hours=Sum('hours')
            )
            emp_recon.iqb_annual_leave_pay = annual['amount'] or 0
            emp_recon.iqb_annual_leave_hours = annual['hours'] or 0
            
            # Sick leave
            sick = iqb_records.filter(
                transaction_type='Sick Leave'
            ).aggregate(
                amount=Sum('amount'),
                hours=Sum('hours')
            )
            emp_recon.iqb_sick_leave_pay = sick['amount'] or 0
            emp_recon.iqb_sick_leave_hours = sick['hours'] or 0
            
            # Other leave (LSL, TIL, etc.)
            other_leave = iqb_records.filter(
                transaction_type__in=['Long Service Leave', 'Other Leave', 'User Defined Leave']
            ).aggregate(
                amount=Sum('amount'),
                hours=Sum('hours')
            )
            emp_recon.iqb_other_leave_pay = other_leave['amount'] or 0
            emp_recon.iqb_other_leave_hours = other_leave['hours'] or 0
            
            # Superannuation
            super_amount = iqb_records.filter(
                transaction_type='Super'
            ).aggregate(
                amount=Sum('amount')
            )['amount'] or 0
            emp_recon.iqb_superannuation = super_amount

            # Filter records for costs calculation (only allowed transaction types, excluding Super)
            cost_records = iqb_records.filter(
                transaction_type__in=self.allowed_transaction_types['costs']
            ).exclude(
                transaction_type='Super'  # Exclude Super from gross pay
            )

            # Gross pay (filtered cost transaction types, excluding Super)
            gross = cost_records.aggregate(
                amount=Sum('amount')
            )['amount'] or 0
            emp_recon.iqb_gross_pay = gross

            # Total cost (same as gross pay, super is kept separate)
            emp_recon.iqb_total_cost = gross
        
        # Calculate variances
        emp_recon.hours_variance = abs(
            emp_recon.tanda_total_hours - emp_recon.iqb_total_hours
        )

        if emp_recon.tanda_total_hours > 0:
            emp_recon.hours_variance_pct = (
                emp_recon.hours_variance / emp_recon.tanda_total_hours * 100
            )

        # For cost variance: use Auto Pay Amount for salaried employees, Tanda cost for others
        expected_cost = emp_recon.auto_pay_amount if emp_recon.is_salaried else emp_recon.tanda_total_cost

        emp_recon.cost_variance = abs(
            expected_cost - emp_recon.iqb_gross_pay  # Compare against gross pay (excluding super)
        )

        if expected_cost > 0:
            emp_recon.cost_variance_pct = (
                emp_recon.cost_variance / expected_cost * 100
            )
        
        # Determine if there are issues
        emp_recon.hours_match = emp_recon.hours_variance <= 1  # 1 hour threshold
        emp_recon.cost_match = emp_recon.cost_variance <= 10 or emp_recon.cost_variance_pct <= 1
        emp_recon.has_issues = not (emp_recon.hours_match and emp_recon.cost_match)
        
        # Build issue description
        issues = []
        if not emp_recon.hours_match:
            issues.append(f"Hours variance: {emp_recon.hours_variance:.2f} hrs")
        if not emp_recon.cost_match:
            issues.append(f"Cost variance: ${emp_recon.cost_variance:.2f}")
        emp_recon.issue_description = "; ".join(issues)
        
        return emp_recon
    
    def _check_employee_hours_and_costs(self):
        """
        Check hours and costs for each employee using the joint database
        """
        for emp_recon in self.employee_recons:
            # Check for missing employees
            if emp_recon.tanda_total_hours == 0 and emp_recon.iqb_total_hours > 0:
                self.exceptions.append(ReconciliationItem(
                    recon_run=self.recon_run,
                    recon_type='hours',
                    employee_id=emp_recon.employee_id,
                    employee_name=emp_recon.employee_name,
                    expected_value=Decimal(str(emp_recon.iqb_total_hours)),
                    actual_value=Decimal('0'),
                    variance=Decimal(str(emp_recon.iqb_total_hours)),
                    severity='critical',
                    status='open',
                    description=f"Employee {emp_recon.employee_name} has {emp_recon.iqb_total_hours:.2f} hours in IQB but NO timesheet in Tanda. Missing timesheet?"
                ))
            
            elif emp_recon.tanda_total_hours > 0 and emp_recon.iqb_total_hours == 0:
                self.exceptions.append(ReconciliationItem(
                    recon_run=self.recon_run,
                    recon_type='hours',
                    employee_id=emp_recon.employee_id,
                    employee_name=emp_recon.employee_name,
                    expected_value=Decimal(str(emp_recon.tanda_total_hours)),
                    actual_value=Decimal('0'),
                    variance=Decimal(str(emp_recon.tanda_total_hours)),
                    severity='critical',
                    status='open',
                    description=f"Employee {emp_recon.employee_name} has {emp_recon.tanda_total_hours:.2f} hours in Tanda but NO records in IQB. Not paid?"
                ))
            
            # Check hours variance
            elif not emp_recon.hours_match:
                severity = 'critical' if emp_recon.hours_variance > 8 else 'warning'
                
                self.exceptions.append(ReconciliationItem(
                    recon_run=self.recon_run,
                    recon_type='hours',
                    employee_id=emp_recon.employee_id,
                    employee_name=emp_recon.employee_name,
                    expected_value=Decimal(str(emp_recon.tanda_total_hours)),
                    actual_value=Decimal(str(emp_recon.iqb_total_hours)),
                    variance=Decimal(str(emp_recon.hours_variance)),
                    variance_pct=Decimal(str(emp_recon.hours_variance_pct)),
                    severity=severity,
                    status='open',
                    description=f"Hours variance for {emp_recon.employee_name}: Tanda shows {emp_recon.tanda_total_hours:.2f} hours but IQB shows {emp_recon.iqb_total_hours:.2f} hours (variance: {emp_recon.hours_variance:.2f} hours, {emp_recon.hours_variance_pct:.1f}%)"
                ))
            
            # Check cost variance
            if not emp_recon.cost_match and emp_recon.tanda_total_cost > 0 and emp_recon.iqb_total_cost > 0:
                severity = 'critical' if emp_recon.cost_variance_pct > 5 else 'warning'
                
                self.exceptions.append(ReconciliationItem(
                    recon_run=self.recon_run,
                    recon_type='cost',
                    employee_id=emp_recon.employee_id,
                    employee_name=emp_recon.employee_name,
                    expected_value=Decimal(str(emp_recon.tanda_total_cost)),
                    actual_value=Decimal(str(emp_recon.iqb_total_cost)),
                    variance=Decimal(str(emp_recon.cost_variance)),
                    variance_pct=Decimal(str(emp_recon.cost_variance_pct)),
                    severity=severity,
                    status='open',
                    description=f"Cost variance for {emp_recon.employee_name}: Tanda cost ${emp_recon.tanda_total_cost:,.2f} but IQB cost ${emp_recon.iqb_total_cost:,.2f} (variance: ${emp_recon.cost_variance:,.2f}, {emp_recon.cost_variance_pct:.1f}%)"
                ))
    
    def _check_cost_center_totals(self):
        """
        Check cost center totals: IQB vs Journal with split allocations
        """
        # Get active uploads
        iqb_upload = Upload.objects.filter(
            pay_period=self.pay_period,
            source_system='Micropay_IQB',
            is_active=True
        ).first()
        
        journal_upload = Upload.objects.filter(
            pay_period=self.pay_period,
            source_system='Micropay_Journal',
            is_active=True
        ).first()
        
        if not iqb_upload or not journal_upload:
            return
        
        # Sum IQB amounts by cost account (only allowed transaction types for costs)
        iqb_totals = IQBDetail.objects.filter(
            upload=iqb_upload,
            transaction_type__in=self.allowed_transaction_types['costs']
        ).values('cost_account_code').annotate(
            total_amount=Sum('amount')
        )
        
        # Apply split allocations
        iqb_with_splits = self._apply_split_allocations(iqb_totals)
        
        # Sum Journal debits by cost account (Labour account only)
        journal_totals = JournalEntry.objects.filter(
            upload=journal_upload,
            ledger_account='-6345'
        ).values('cost_account').annotate(
            total_debit=Sum('debit')
        )
        
        # Convert to dict
        journal_dict = {
            item['cost_account']: float(item['total_debit'] or 0)
            for item in journal_totals
        }
        
        # Compare cost centers
        for cost_account, iqb_amount in iqb_with_splits.items():
            journal_amount = journal_dict.get(cost_account, 0)
            
            variance = abs(iqb_amount - journal_amount)
            variance_pct = (variance / iqb_amount * 100) if iqb_amount > 0 else 0
            
            # Check thresholds: >$10 OR >1%
            if variance > 10 and variance_pct > 1:
                severity = 'critical' if variance_pct > 5 else 'warning'
                
                self.exceptions.append(ReconciliationItem(
                    recon_run=self.recon_run,
                    recon_type='cost',
                    cost_center=cost_account,
                    expected_value=Decimal(str(iqb_amount)),
                    actual_value=Decimal(str(journal_amount)),
                    variance=Decimal(str(variance)),
                    variance_pct=Decimal(str(variance_pct)),
                    severity=severity,
                    status='open',
                    description=f"Cost variance for {cost_account}: IQB total ${iqb_amount:,.2f} but Journal shows ${journal_amount:,.2f} (variance: ${variance:,.2f}, {variance_pct:.2f}%)"
                ))
            
            elif journal_amount == 0 and iqb_amount > 0:
                self.exceptions.append(ReconciliationItem(
                    recon_run=self.recon_run,
                    recon_type='cost',
                    cost_center=cost_account,
                    expected_value=Decimal(str(iqb_amount)),
                    actual_value=Decimal('0'),
                    variance=Decimal(str(iqb_amount)),
                    severity='critical',
                    status='open',
                    description=f"Cost center {cost_account} has ${iqb_amount:,.2f} in IQB but NO entry in Journal. Missing GL posting?"
                ))
    
    def _apply_split_allocations(self, iqb_totals):
        """Apply split allocations for SPL- accounts"""
        result = {}
        
        for item in iqb_totals:
            cost_account = item['cost_account_code']
            amount = float(item['total_amount'] or 0)
            
            if cost_account.startswith('SPL-'):
                splits = CostCenterSplit.objects.filter(
                    source_account=cost_account,
                    is_active=True
                )
                
                if splits.exists():
                    for split in splits:
                        target = split.target_account
                        allocated = amount * float(split.percentage)
                        result[target] = result.get(target, 0) + allocated
                else:
                    result[cost_account] = result.get(cost_account, 0) + amount
            else:
                result[cost_account] = result.get(cost_account, 0) + amount
        
        return result
    
    def _check_completeness(self):
        """Completeness checks"""
        # Check if all 3 files uploaded
        if not (self.pay_period.has_tanda and self.pay_period.has_iqb and self.pay_period.has_journal):
            missing = []
            if not self.pay_period.has_tanda:
                missing.append('Tanda Timesheet')
            if not self.pay_period.has_iqb:
                missing.append('Micropay IQB')
            if not self.pay_period.has_journal:
                missing.append('Micropay Journal')
            
            self.exceptions.append(ReconciliationItem(
                recon_run=self.recon_run,
                recon_type='completeness',
                severity='critical',
                status='open',
                description=f"Incomplete data: Missing {', '.join(missing)}"
            ))

    def _reconcile_journal_entries(self):
        """
        Reconcile journal entries using the mapping file
        Sum debit - credit for each description
        """
        # Get journal upload
        journal_upload = Upload.objects.filter(
            pay_period=self.pay_period,
            source_system='Micropay_Journal',
            is_active=True
        ).first()

        if not journal_upload:
            print("No journal upload found for reconciliation")
            return

        # Group journal entries by description and sum debit/credit
        journal_entries = JournalEntry.objects.filter(
            upload=journal_upload
        ).values('description').annotate(
            total_debit=Sum('debit'),
            total_credit=Sum('credit')
        )

        journal_recons = []

        for entry in journal_entries:
            description = entry['description']
            total_debit = entry['total_debit'] or Decimal('0')
            total_credit = entry['total_credit'] or Decimal('0')
            net_amount = total_debit - total_credit

            # Check if description is in mapping
            is_mapped = description in self.journal_mapping
            gl_account = ''
            include_in_total_cost = False

            if is_mapped:
                mapping_info = self.journal_mapping[description]
                gl_account = mapping_info['gl_account']
                include_in_total_cost = mapping_info['include_in_total_cost']

            journal_recon = JournalReconciliation(
                recon_run=self.recon_run,
                description=description,
                gl_account=gl_account,
                include_in_total_cost=include_in_total_cost,
                is_mapped=is_mapped,
                journal_debit=total_debit,
                journal_credit=total_credit,
                journal_net=net_amount
            )

            journal_recons.append(journal_recon)

        # Bulk create journal reconciliations
        JournalReconciliation.objects.bulk_create(journal_recons)

        # Calculate totals
        total_cost_sum = sum(jr.journal_net for jr in journal_recons if jr.include_in_total_cost)
        unmapped_count = sum(1 for jr in journal_recons if not jr.is_mapped)

        print(f"Journal reconciliation complete:")
        print(f"  Total descriptions: {len(journal_recons)}")
        print(f"  Unmapped descriptions: {unmapped_count}")
        print(f"  Total Cost (marked Y): ${total_cost_sum:,.2f}")


def trigger_reconciliation(pay_period):
    """Convenience function to trigger reconciliation"""
    engine = ReconciliationEngine(pay_period)
    return engine.run_reconciliation()