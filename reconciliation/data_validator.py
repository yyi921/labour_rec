"""
Data validation module for uploaded files
Validates Cost Account Codes, Pay Comp Codes, and Employee Codes
"""
import csv
import os
from django.conf import settings
from reconciliation.models import (
    Upload, IQBDetail, SageLocation, SageDepartment,
    PayCompCodeMapping, LocationMapping, Employee
)


class DataValidator:
    """Validates uploaded data against master files and mappings"""

    @staticmethod
    def load_master_employees():
        """Load employee codes from database and return set of valid employee codes"""
        # Load from database Employee model
        employee_codes = set(Employee.objects.values_list('code', flat=True))

        # If database is empty, try to load from CSV as fallback
        if not employee_codes:
            csv_path = os.path.join(settings.BASE_DIR, 'data', 'master_employee_file.csv')
            if os.path.exists(csv_path):
                with open(csv_path, 'r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        code = row.get('Code', '').strip()
                        if code:
                            employee_codes.add(code)

        return employee_codes if employee_codes else None

    @staticmethod
    def validate_upload(upload):
        """
        Validate an upload against all validation rules

        Returns:
            dict with validation results:
            {
                'passed': bool,
                'validations': [
                    {
                        'test_name': str,
                        'passed': bool,
                        'errors': list of error dicts
                    }
                ]
            }
        """
        results = {
            'passed': True,
            'validations': []
        }

        # Only validate IQB files for now (has Cost Account Codes and Pay Comp Codes)
        if upload.source_system == 'Micropay_IQB':
            # Test 1: Cost Account Code - Location validation
            location_validation = DataValidator._validate_cost_account_locations(upload)
            results['validations'].append(location_validation)
            if not location_validation['passed']:
                results['passed'] = False

            # Test 2: Cost Account Code - Department validation
            department_validation = DataValidator._validate_cost_account_departments(upload)
            results['validations'].append(department_validation)
            if not department_validation['passed']:
                results['passed'] = False

            # Test 3: Cost Account Code - Split_Data validation
            split_data_validation = DataValidator._validate_cost_account_in_split_data(upload)
            results['validations'].append(split_data_validation)
            if not split_data_validation['passed']:
                results['passed'] = False

            # Test 4: Pay Comp/Add Ded Code validation
            pay_comp_validation = DataValidator._validate_pay_comp_codes(upload)
            results['validations'].append(pay_comp_validation)
            if not pay_comp_validation['passed']:
                results['passed'] = False

            # Test 5: Employee Code validation
            employee_validation = DataValidator._validate_employee_codes(upload)
            results['validations'].append(employee_validation)
            if not employee_validation['passed']:
                results['passed'] = False

        elif upload.source_system == 'Tanda_Timesheet':
            # Test 1: Employee Code validation
            employee_validation = DataValidator._validate_employee_codes_tanda(upload)
            results['validations'].append(employee_validation)
            if not employee_validation['passed']:
                results['passed'] = False

            # Test 2: GLCode validation (checks both location and department)
            glcode_validation = DataValidator._validate_tanda_gl_codes(upload)
            results['validations'].append(glcode_validation)
            if not glcode_validation['passed']:
                results['passed'] = False

        elif upload.source_system == 'Micropay_IQB_Leave':
            # Validate leave balance files
            leave_balance_validation = DataValidator._validate_leave_balance(upload)
            results['validations'].append(leave_balance_validation)
            if not leave_balance_validation['passed']:
                results['passed'] = False

        return results

    @staticmethod
    def _validate_cost_account_locations(upload):
        """Validate that location codes in Cost Account Codes exist in SageLocation
        Note: SPL accounts (split accounts) are excluded from this check"""
        test_result = {
            'test_name': 'Cost Account Code - Location Validation',
            'description': 'Check if location codes (first 3 digits) match Sage Location master data (excludes SPL split accounts)',
            'passed': True,
            'errors': []
        }

        # Get all valid location IDs
        valid_locations = set(SageLocation.objects.values_list('location_id', flat=True))

        # Get unique cost account codes from IQB
        cost_accounts = IQBDetail.objects.filter(upload=upload).values_list('cost_account_code', flat=True).distinct()

        invalid_locations = {}
        for cost_account in cost_accounts:
            if not cost_account or '-' not in cost_account:
                continue

            # Skip SPL (split) accounts - they will be validated in Split_Data check
            if cost_account.startswith('SPL'):
                continue

            location_code = cost_account.split('-')[0]

            if location_code not in valid_locations:
                if location_code not in invalid_locations:
                    invalid_locations[location_code] = []
                invalid_locations[location_code].append(cost_account)

        if invalid_locations:
            test_result['passed'] = False
            for location_code, accounts in invalid_locations.items():
                test_result['errors'].append({
                    'invalid_location': location_code,
                    'cost_accounts': accounts[:10],  # Limit to first 10 examples
                    'total_count': len(accounts)
                })

        return test_result

    @staticmethod
    def _validate_cost_account_departments(upload):
        """Validate that department codes in Cost Account Codes exist in SageDepartment
        Note: SPL accounts (split accounts) are excluded from this check"""
        test_result = {
            'test_name': 'Cost Account Code - Department Validation',
            'description': 'Check if department codes (first 2 digits after dash) match Sage Department master data (excludes SPL split accounts)',
            'passed': True,
            'errors': []
        }

        # Get all valid department IDs
        valid_departments = set(SageDepartment.objects.values_list('department_id', flat=True))

        # Get unique cost account codes from IQB
        cost_accounts = IQBDetail.objects.filter(upload=upload).values_list('cost_account_code', flat=True).distinct()

        invalid_departments = {}
        for cost_account in cost_accounts:
            if not cost_account or '-' not in cost_account:
                continue

            # Skip SPL (split) accounts - they will be validated in Split_Data check
            if cost_account.startswith('SPL'):
                continue

            parts = cost_account.split('-')
            if len(parts) < 2 or len(parts[1]) < 2:
                continue

            department_code = parts[1][:2]  # First 2 digits after dash

            if department_code not in valid_departments:
                if department_code not in invalid_departments:
                    invalid_departments[department_code] = []
                invalid_departments[department_code].append(cost_account)

        if invalid_departments:
            test_result['passed'] = False
            for department_code, accounts in invalid_departments.items():
                test_result['errors'].append({
                    'invalid_department': department_code,
                    'cost_accounts': accounts[:10],
                    'total_count': len(accounts)
                })

        return test_result

    @staticmethod
    def _validate_cost_account_in_split_data(upload):
        """Validate that SPL (split) account codes exist in CostCenterSplit (Split_Data)
        Only validates accounts starting with 'SPL' prefix"""
        test_result = {
            'test_name': 'Cost Account Code - Split Data Validation',
            'description': 'Check if SPL split account codes exist in Split_Data (CostCenterSplit)',
            'passed': True,
            'errors': []
        }

        # Import CostCenterSplit
        from reconciliation.models import CostCenterSplit

        # Get all valid SPL source accounts from CostCenterSplit
        valid_spl_accounts = set(CostCenterSplit.objects.values_list('source_account', flat=True).distinct())

        # Get unique cost account codes from IQB
        cost_accounts = IQBDetail.objects.filter(upload=upload).values_list('cost_account_code', flat=True).distinct()

        missing_accounts = []
        for cost_account in cost_accounts:
            if not cost_account:
                continue

            # Only validate SPL (split) accounts
            if not cost_account.startswith('SPL'):
                continue

            if cost_account not in valid_spl_accounts:
                missing_accounts.append(cost_account)

        if missing_accounts:
            test_result['passed'] = False
            test_result['errors'].append({
                'message': 'SPL split account codes not found in Split_Data/LocationMapping',
                'missing_accounts': missing_accounts[:20],  # First 20 examples
                'total_count': len(missing_accounts)
            })

        return test_result

    @staticmethod
    def _validate_pay_comp_codes(upload):
        """Validate that Pay Comp/Add Ded Codes exist in PayCompCodeMapping
        Note: Leading zeros are stripped from codes before comparison"""
        test_result = {
            'test_name': 'Pay Comp/Add Ded Code Validation',
            'description': 'Check if pay_comp_code values match PayCompCode Mapping (leading zeros stripped)',
            'passed': True,
            'errors': []
        }

        # Get all valid pay comp codes and create normalized lookup
        valid_pay_comp_codes = set(PayCompCodeMapping.objects.values_list('pay_comp_code', flat=True))
        # Add normalized versions (strip leading zeros from numeric codes)
        normalized_valid_codes = set()
        for code in valid_pay_comp_codes:
            if code:
                normalized_valid_codes.add(code)
                # If code is numeric, add version with leading zeros stripped
                if code.isdigit():
                    normalized_valid_codes.add(code.lstrip('0') or '0')

        # Get unique pay comp codes from IQB
        pay_comp_codes = IQBDetail.objects.filter(upload=upload).values_list('pay_comp_code', flat=True).distinct()

        missing_codes = []
        for pay_comp_code in pay_comp_codes:
            if not pay_comp_code:
                continue

            # Check both original and normalized version (strip leading zeros if numeric)
            check_code = pay_comp_code
            if pay_comp_code.isdigit():
                check_code = pay_comp_code.lstrip('0') or '0'

            if pay_comp_code not in valid_pay_comp_codes and check_code not in normalized_valid_codes:
                missing_codes.append(pay_comp_code)

        if missing_codes:
            test_result['passed'] = False
            test_result['errors'].append({
                'message': 'Pay Comp/Add Ded Codes not found in PayCompCode Mapping',
                'missing_codes': missing_codes[:20],
                'total_count': len(missing_codes)
            })

        return test_result

    @staticmethod
    def _validate_employee_codes(upload):
        """Validate that employee codes exist in master_employee_file"""
        test_result = {
            'test_name': 'Employee Code Validation',
            'description': 'Check if employee codes match master employee file',
            'passed': True,
            'errors': []
        }

        # Load master employee codes
        valid_employee_codes = DataValidator.load_master_employees()

        if valid_employee_codes is None:
            test_result['errors'].append({
                'message': 'Could not load master_employee_file.csv'
            })
            test_result['passed'] = False
            return test_result

        # Get unique employee codes from IQB
        employee_codes = IQBDetail.objects.filter(upload=upload).values_list('employee_code', flat=True).distinct()

        missing_codes = []
        for employee_code in employee_codes:
            if not employee_code:
                continue

            if employee_code not in valid_employee_codes:
                missing_codes.append(employee_code)

        if missing_codes:
            test_result['passed'] = False
            test_result['errors'].append({
                'message': 'Employee codes not found in master employee file',
                'missing_codes': missing_codes[:20],
                'total_count': len(missing_codes)
            })

        return test_result

    @staticmethod
    def _validate_employee_codes_tanda(upload):
        """Validate that employee codes in Tanda exist in master_employee_file"""
        test_result = {
            'test_name': 'Employee Code Validation',
            'description': 'Check if employee codes match master employee file',
            'passed': True,
            'errors': []
        }

        # Load master employee codes
        valid_employee_codes = DataValidator.load_master_employees()

        if valid_employee_codes is None:
            test_result['errors'].append({
                'message': 'Could not load master_employee_file.csv'
            })
            test_result['passed'] = False
            return test_result

        # Get unique employee codes from Tanda
        from reconciliation.models import TandaTimesheet
        employee_codes = TandaTimesheet.objects.filter(upload=upload).values_list('employee_id', flat=True).distinct()

        missing_codes = []
        for employee_code in employee_codes:
            if not employee_code:
                continue

            if str(employee_code) not in valid_employee_codes:
                missing_codes.append(str(employee_code))

        if missing_codes:
            test_result['passed'] = False
            test_result['errors'].append({
                'message': 'Employee codes not found in master employee file',
                'missing_codes': missing_codes[:20],
                'total_count': len(missing_codes)
            })

        return test_result

    @staticmethod
    def _validate_tanda_gl_codes(upload):
        """Validate that GLCodes in Tanda timesheets match Sage Location and Department master data
        GLCode format: [location]-[department] (e.g., '910-93')"""
        test_result = {
            'test_name': 'Tanda GLCode Validation',
            'description': 'Check if GLCodes match Sage Location and Department master data (format: location-department)',
            'passed': True,
            'errors': []
        }

        # Get all valid location and department IDs
        valid_locations = set(SageLocation.objects.values_list('location_id', flat=True))
        valid_departments = set(SageDepartment.objects.values_list('department_id', flat=True))

        # Get unique GLCodes from Tanda upload
        from reconciliation.models import TandaTimesheet
        gl_codes = TandaTimesheet.objects.filter(upload=upload).values_list('gl_code', flat=True).distinct()

        invalid_locations = {}
        invalid_departments = {}
        malformed_codes = []

        for gl_code in gl_codes:
            if not gl_code:
                continue

            # Parse GLCode: location-department
            if '-' not in gl_code:
                malformed_codes.append(gl_code)
                continue

            parts = gl_code.split('-')
            if len(parts) != 2:
                malformed_codes.append(gl_code)
                continue

            location_code = parts[0].strip()
            department_code = parts[1].strip()

            # Validate location code
            if location_code and location_code not in valid_locations:
                if location_code not in invalid_locations:
                    invalid_locations[location_code] = []
                invalid_locations[location_code].append(gl_code)

            # Validate department code
            if department_code and department_code not in valid_departments:
                if department_code not in invalid_departments:
                    invalid_departments[department_code] = []
                invalid_departments[department_code].append(gl_code)

        # Report malformed GLCodes
        if malformed_codes:
            test_result['passed'] = False
            test_result['errors'].append({
                'message': 'GLCodes with incorrect format (expected: location-department)',
                'malformed_codes': malformed_codes[:20],
                'total_count': len(malformed_codes)
            })

        # Report invalid location codes
        if invalid_locations:
            test_result['passed'] = False
            for location_code, codes in invalid_locations.items():
                test_result['errors'].append({
                    'invalid_location': location_code,
                    'gl_codes': codes[:10],
                    'total_count': len(codes),
                    'error_type': 'location'
                })

        # Report invalid department codes
        if invalid_departments:
            test_result['passed'] = False
            for department_code, codes in invalid_departments.items():
                test_result['errors'].append({
                    'invalid_department': department_code,
                    'gl_codes': codes[:10],
                    'total_count': len(codes),
                    'error_type': 'department'
                })

        return test_result

    @staticmethod
    def _validate_leave_balance(upload):
        """
        Validate leave balance file logic:
        - If multiple leave balance files exist for this pay period, check that:
          * The earliest date is the opening balance
          * The latest date matches the pay period ID (closing balance)
        - If only one leave balance file exists, check that:
          * Either an opening balance exists in the system (from an earlier pay period)
          * OR the file date matches the pay period ID (can use it as both opening and closing)
        """
        test_result = {
            'test_name': 'Leave Balance File Validation',
            'description': 'Check if leave balance files have proper opening and closing balances',
            'passed': True,
            'errors': []
        }

        pay_period = upload.pay_period
        pay_period_date = pay_period.period_end

        # Get all leave balance uploads for this pay period (including this one)
        all_leave_uploads = Upload.objects.filter(
            pay_period=pay_period,
            source_system='Micropay_IQB_Leave',
            is_active=True
        ).order_by('uploaded_at')

        if all_leave_uploads.count() == 0:
            test_result['passed'] = False
            test_result['errors'].append({
                'message': 'No leave balance files found for this pay period'
            })
            return test_result

        # Get the as_of_date for each leave balance file
        from reconciliation.models import IQBLeaveBalance
        leave_dates = []
        for lb_upload in all_leave_uploads:
            # Get the as_of_date from the records
            as_of_date = IQBLeaveBalance.objects.filter(
                upload=lb_upload
            ).values_list('as_of_date', flat=True).first()

            if as_of_date:
                leave_dates.append({
                    'upload': lb_upload,
                    'date': as_of_date
                })

        if not leave_dates:
            test_result['passed'] = False
            test_result['errors'].append({
                'message': 'Could not determine dates for leave balance files'
            })
            return test_result

        # Sort by date
        leave_dates.sort(key=lambda x: x['date'])

        if len(leave_dates) >= 2:
            # Two or more files: earliest is opening, latest should match pay period
            opening_date = leave_dates[0]['date']
            closing_date = leave_dates[-1]['date']

            if closing_date != pay_period_date:
                test_result['passed'] = False
                test_result['errors'].append({
                    'message': f'Closing balance date ({closing_date}) does not match pay period end date ({pay_period_date})',
                    'opening_date': str(opening_date),
                    'closing_date': str(closing_date),
                    'expected_closing_date': str(pay_period_date)
                })

        elif len(leave_dates) == 1:
            # Only one file: check if it matches pay period OR if opening balance exists elsewhere
            single_date = leave_dates[0]['date']

            if single_date == pay_period_date:
                # This is the closing balance, check if opening balance exists from earlier period
                # Look for leave balance from any earlier pay period
                earlier_leave_upload = Upload.objects.filter(
                    source_system='Micropay_IQB_Leave',
                    is_active=True,
                    pay_period__period_end__lt=pay_period_date
                ).order_by('-pay_period__period_end').first()

                if not earlier_leave_upload:
                    test_result['passed'] = False
                    test_result['errors'].append({
                        'message': f'Only one leave balance file found for closing balance ({single_date}), but no opening balance exists from an earlier pay period',
                        'suggestion': 'Upload an opening balance file with an earlier date, or if this is the first pay period, upload both opening and closing balance files'
                    })
            else:
                # File date doesn't match pay period
                test_result['passed'] = False
                test_result['errors'].append({
                    'message': f'Single leave balance file date ({single_date}) does not match pay period end date ({pay_period_date})',
                    'suggestion': f'Either upload a closing balance file for {pay_period_date}, or if this is the opening balance, upload both opening and closing files'
                })

        return test_result
