"""
Accrual Wage Processor
Processes Tanda timesheet data to calculate accrued wages and on-costs
"""
from decimal import Decimal
from datetime import datetime
from django.utils import timezone
from django.db.models import Sum
from collections import defaultdict

from reconciliation.models import (
    Employee, TandaTimesheet, PayPeriod, EmployeePayPeriodSnapshot,
    SageLocation, SageDepartment, CostCenterSplit
)
from reconciliation.accrual_calculator import AccrualWageCalculator


class AccrualWageProcessor:
    """
    Processes Tanda timesheet data to calculate accruals
    """

    @classmethod
    def process_accruals(cls, upload, start_date, end_date, pay_period):
        """
        Process accruals for a pay period based on Tanda timesheet data

        Args:
            upload: Upload instance (Tanda_Timesheet)
            start_date (str or date): Start date of accrual period
            end_date (str or date): End date of accrual period
            pay_period: PayPeriod instance (for storing results)

        Returns:
            dict: {
                'processed_count': int,
                'skipped_count': int,
                'employees_not_found': list,
                'employees_terminated': list,
                'validation_errors': list,
                'gl_code_errors': list,
                'total_accrued': Decimal
            }
        """
        # Convert string dates to date objects if needed
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

        # Get all Tanda records for this upload
        tanda_records = TandaTimesheet.objects.filter(upload=upload)

        # Group by employee
        employee_data = defaultdict(lambda: {
            'shift_cost': Decimal('0'),
            'gl_codes': set(),
            'locations': set(),
            'departments': set()
        })

        for record in tanda_records:
            emp_code = record.employee_id
            employee_data[emp_code]['shift_cost'] += Decimal(str(record.shift_cost))

            # Track GL codes and extract location/department
            if record.gl_code:
                employee_data[emp_code]['gl_codes'].add(record.gl_code)

                # Parse GL code (format: location-department)
                if '-' in record.gl_code:
                    parts = record.gl_code.split('-')
                    if len(parts) >= 2:
                        location_code = parts[0]
                        dept_code = parts[1][:2] if len(parts[1]) >= 2 else parts[1]

                        employee_data[emp_code]['locations'].add(location_code)
                        employee_data[emp_code]['departments'].add(dept_code)

        # Track which employees we've processed
        processed_employee_codes = set()

        # Process each employee from Tanda
        processed_count = 0
        skipped_count = 0
        employees_not_found = []
        employees_terminated = []
        employees_auto_pay_only = []  # Employees processed from auto_pay (not in Tanda)
        validation_errors = []
        gl_code_errors = []
        total_accrued = Decimal('0')

        for emp_code, data in employee_data.items():
            try:
                # Check if employee exists
                try:
                    employee = Employee.objects.get(code=emp_code)
                except Employee.DoesNotExist:
                    employees_not_found.append({
                        'employee_code': emp_code,
                        'shift_cost': float(data['shift_cost']),
                        'gl_codes': list(data['gl_codes'])
                    })
                    skipped_count += 1
                    continue

                # Validate employee (check termination date)
                is_valid, reason = AccrualWageCalculator.validate_employee_for_accrual(
                    employee, start_date
                )

                if not is_valid:
                    employees_terminated.append({
                        'employee_code': emp_code,
                        'employee_name': employee.full_name,
                        'termination_date': str(employee.termination_date),
                        'reason': reason
                    })
                    skipped_count += 1
                    continue

                # Calculate accruals
                accruals = AccrualWageCalculator.calculate_accruals(
                    employee=employee,
                    tanda_shift_cost=data['shift_cost'],
                    start_date=start_date,
                    end_date=end_date
                )

                # Validate GL codes
                gl_validation = cls._validate_gl_codes(list(data['gl_codes']))
                if not gl_validation['valid']:
                    gl_code_errors.append({
                        'employee_code': emp_code,
                        'employee_name': employee.full_name,
                        'gl_codes': list(data['gl_codes']),
                        'errors': gl_validation['errors']
                    })

                # Build cost allocation from GL codes
                cost_allocation = cls._build_cost_allocation(list(data['gl_codes']))

                # Create or update EmployeePayPeriodSnapshot
                snapshot, created = EmployeePayPeriodSnapshot.objects.update_or_create(
                    pay_period=pay_period,
                    employee_code=emp_code,
                    defaults={
                        'employee_name': employee.full_name,
                        'employment_status': 'Active' if employee.is_active else 'Terminated',
                        'termination_date': employee.termination_date,

                        # Accrual period info
                        'accrual_period_start': start_date,
                        'accrual_period_end': end_date,
                        'accrual_days_in_period': accruals['days_in_period'],

                        # Accrual amounts (detailed tracking)
                        'accrual_base_wages': accruals['base_wage'],
                        'accrual_superannuation': accruals['superannuation'],
                        'accrual_annual_leave': accruals['annual_leave'],
                        'accrual_payroll_tax': accruals['payroll_tax'],
                        'accrual_workcover': accruals['workcover'],
                        'accrual_total': accruals['total'],

                        # Metadata
                        'accrual_source': accruals['source'],
                        'accrual_calculated_at': timezone.now(),
                        'accrual_employee_type': accruals['employee_type'],

                        # GL Account totals (for journal generation)
                        'gl_6345_salaries': accruals['base_wage'],  # Dr - Salaries expense
                        'gl_6370_superannuation': accruals['superannuation'],  # Dr - Super expense
                        'gl_6300': accruals['annual_leave'],  # Dr - Annual leave accrual expense
                        'gl_6335': accruals['payroll_tax'],  # Dr - Payroll tax expense
                        'gl_6380': accruals['workcover'],  # Dr - Workcover expense
                        'gl_2055_accrued_expenses': accruals['total'],  # Cr - Accrued expenses liability

                        # Total cost (sum of all expense GLs)
                        'total_cost': accruals['total'],

                        # Cost allocation (from GL codes)
                        'cost_allocation': cost_allocation,
                        'allocation_source': 'tanda',
                        'allocation_finalized_at': timezone.now()
                    }
                )

                processed_count += 1
                total_accrued += accruals['total']
                processed_employee_codes.add(emp_code)

            except Exception as e:
                validation_errors.append({
                    'employee_code': emp_code,
                    'error': str(e)
                })
                skipped_count += 1

        # Process employees with auto_pay who were NOT in Tanda timesheet
        auto_pay_employees = Employee.objects.filter(
            auto_pay='Yes'
        ).exclude(
            code__in=processed_employee_codes
        )

        for employee in auto_pay_employees:
            try:
                # Skip if auto_pay_amount is 0 or None
                if not employee.auto_pay_amount or employee.auto_pay_amount <= 0:
                    continue

                # Validate employee (check termination date)
                is_valid, reason = AccrualWageCalculator.validate_employee_for_accrual(
                    employee, start_date
                )

                if not is_valid:
                    employees_terminated.append({
                        'employee_code': employee.code,
                        'employee_name': employee.full_name,
                        'termination_date': str(employee.termination_date) if employee.termination_date else '',
                        'reason': reason
                    })
                    skipped_count += 1
                    continue

                # Calculate accruals (no Tanda shift cost, will use auto_pay)
                accruals = AccrualWageCalculator.calculate_accruals(
                    employee=employee,
                    tanda_shift_cost=Decimal('0'),  # No Tanda data
                    start_date=start_date,
                    end_date=end_date
                )

                # Use default cost account if available
                cost_allocation = {}
                if employee.default_cost_account:
                    # Check if this is a SPL- account
                    if employee.default_cost_account.startswith('SPL-'):
                        # Look up the split
                        try:
                            split = CostCenterSplit.objects.get(split_code=employee.default_cost_account)
                            targets = split.get_targets()

                            # Build cost allocation from split targets
                            for target_account, split_pct in targets:
                                if '-' in target_account:
                                    parts = target_account.split('-')
                                    if len(parts) >= 2:
                                        location_code = parts[0]
                                        dept_code = parts[1][:2] if len(parts[1]) >= 2 else parts[1]

                                        if location_code not in cost_allocation:
                                            cost_allocation[location_code] = {}
                                        cost_allocation[location_code][dept_code] = float(split_pct)
                        except CostCenterSplit.DoesNotExist:
                            # If split not found, skip allocation
                            pass
                    else:
                        # Parse default_cost_account (format: location-department)
                        if '-' in employee.default_cost_account:
                            parts = employee.default_cost_account.split('-')
                            if len(parts) >= 2:
                                location_code = parts[0]
                                dept_code = parts[1][:2] if len(parts[1]) >= 2 else parts[1]
                                cost_allocation = {
                                    location_code: {
                                        dept_code: 100.0
                                    }
                                }

                # Create or update EmployeePayPeriodSnapshot
                snapshot, created = EmployeePayPeriodSnapshot.objects.update_or_create(
                    pay_period=pay_period,
                    employee_code=employee.code,
                    defaults={
                        'employee_name': employee.full_name,
                        'employment_status': 'Active' if employee.is_active else 'Terminated',
                        'termination_date': employee.termination_date,

                        # Accrual period info
                        'accrual_period_start': start_date,
                        'accrual_period_end': end_date,
                        'accrual_days_in_period': accruals['days_in_period'],

                        # Accrual amounts (detailed tracking)
                        'accrual_base_wages': accruals['base_wage'],
                        'accrual_superannuation': accruals['superannuation'],
                        'accrual_annual_leave': accruals['annual_leave'],
                        'accrual_payroll_tax': accruals['payroll_tax'],
                        'accrual_workcover': accruals['workcover'],
                        'accrual_total': accruals['total'],

                        # Metadata
                        'accrual_source': accruals['source'],
                        'accrual_calculated_at': timezone.now(),
                        'accrual_employee_type': accruals['employee_type'],

                        # GL Account totals (for journal generation)
                        'gl_6345_salaries': accruals['base_wage'],  # Dr - Salaries expense
                        'gl_6370_superannuation': accruals['superannuation'],  # Dr - Super expense
                        'gl_6300': accruals['annual_leave'],  # Dr - Annual leave accrual expense
                        'gl_6335': accruals['payroll_tax'],  # Dr - Payroll tax expense
                        'gl_6380': accruals['workcover'],  # Dr - Workcover expense
                        'gl_2055_accrued_expenses': accruals['total'],  # Cr - Accrued expenses liability

                        # Total cost (sum of all expense GLs)
                        'total_cost': accruals['total'],

                        # Cost allocation (from default cost account)
                        'cost_allocation': cost_allocation,
                        'allocation_source': 'employee_default',
                        'allocation_finalized_at': timezone.now()
                    }
                )

                processed_count += 1
                total_accrued += accruals['total']
                processed_employee_codes.add(employee.code)

                # Track this as auto_pay_only employee
                employees_auto_pay_only.append({
                    'employee_code': employee.code,
                    'employee_name': employee.full_name,
                    'auto_pay_amount': float(employee.auto_pay_amount),
                    'accrued_amount': float(accruals['total']),
                    'cost_allocation': employee.default_cost_account or 'N/A'
                })

            except Exception as e:
                validation_errors.append({
                    'employee_code': employee.code,
                    'error': str(e)
                })
                skipped_count += 1

        return {
            'processed_count': processed_count,
            'skipped_count': skipped_count,
            'employees_not_found': employees_not_found,
            'employees_terminated': employees_terminated,
            'employees_auto_pay_only': employees_auto_pay_only,
            'validation_errors': validation_errors,
            'gl_code_errors': gl_code_errors,
            'total_accrued': float(total_accrued)
        }

    @classmethod
    def _validate_gl_codes(cls, gl_codes):
        """
        Validate GL codes against master data

        Args:
            gl_codes (list): List of GL codes (e.g., ['449-5000', '454-5000'])

        Returns:
            dict: {
                'valid': bool,
                'errors': list
            }
        """
        errors = []
        valid = True

        for gl_code in gl_codes:
            if not gl_code or '-' not in gl_code:
                errors.append(f"Malformed GL code: {gl_code}")
                valid = False
                continue

            parts = gl_code.split('-')
            if len(parts) < 2:
                errors.append(f"Malformed GL code: {gl_code}")
                valid = False
                continue

            location_code = parts[0]
            dept_code = parts[1][:2] if len(parts[1]) >= 2 else parts[1]

            # Validate location
            if not SageLocation.objects.filter(location_id=location_code).exists():
                errors.append(f"Invalid location code: {location_code} in {gl_code}")
                valid = False

            # Validate department
            if not SageDepartment.objects.filter(department_id=dept_code).exists():
                errors.append(f"Invalid department code: {dept_code} in {gl_code}")
                valid = False

        return {
            'valid': valid,
            'errors': errors
        }

    @classmethod
    def _build_cost_allocation(cls, gl_codes):
        """
        Build cost allocation dictionary from GL codes

        Args:
            gl_codes (list): List of GL codes (e.g., ['449-5000', '454-5000'])

        Returns:
            dict: Cost allocation in format:
                {
                    '449': {'50': 50.00},
                    '454': {'50': 50.00}
                }
        """
        if not gl_codes:
            return {}

        # Count occurrences of each location-department combination
        location_dept_counts = defaultdict(lambda: defaultdict(int))

        for gl_code in gl_codes:
            if not gl_code or '-' not in gl_code:
                continue

            parts = gl_code.split('-')
            if len(parts) < 2:
                continue

            location_code = parts[0]
            dept_code = parts[1][:2] if len(parts[1]) >= 2 else parts[1]

            location_dept_counts[location_code][dept_code] += 1

        # Calculate total count
        total_count = sum(
            sum(depts.values()) for depts in location_dept_counts.values()
        )

        if total_count == 0:
            return {}

        # Calculate percentages
        allocation = {}
        for location, depts in location_dept_counts.items():
            allocation[location] = {}
            for dept, count in depts.items():
                percentage = (Decimal(count) / Decimal(total_count) * 100).quantize(
                    Decimal('0.01')
                )
                allocation[location][dept] = float(percentage)

        return allocation
