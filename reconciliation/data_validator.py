"""
Data validation module for uploaded files
Validates Cost Account Codes, Pay Comp Codes, and Employee Codes
"""
import csv
import os
from django.conf import settings
from reconciliation.models import (
    Upload, IQBDetail, SageLocation, SageDepartment,
    PayCompCodeMapping, LocationMapping
)


class DataValidator:
    """Validates uploaded data against master files and mappings"""

    @staticmethod
    def load_master_employees():
        """Load master employee file and return set of valid employee codes"""
        csv_path = os.path.join(settings.BASE_DIR, 'data', 'master_employee_file.csv')

        if not os.path.exists(csv_path):
            return None

        employee_codes = set()
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get('Code', '').strip()
                if code:
                    employee_codes.add(code)

        return employee_codes

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
            # Test: Employee Code validation
            employee_validation = DataValidator._validate_employee_codes_tanda(upload)
            results['validations'].append(employee_validation)
            if not employee_validation['passed']:
                results['passed'] = False

        return results

    @staticmethod
    def _validate_cost_account_locations(upload):
        """Validate that location codes in Cost Account Codes exist in SageLocation"""
        test_result = {
            'test_name': 'Cost Account Code - Location Validation',
            'description': 'Check if location codes (first 3 digits) match Sage Location master data',
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
        """Validate that department codes in Cost Account Codes exist in SageDepartment"""
        test_result = {
            'test_name': 'Cost Account Code - Department Validation',
            'description': 'Check if department codes (first 2 digits after dash) match Sage Department master data',
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
        """Validate that cost account codes exist in LocationMapping (Split_Data)"""
        test_result = {
            'test_name': 'Cost Account Code - Split Data Validation',
            'description': 'Check if cost account codes exist in LocationMapping/Split_Data',
            'passed': True,
            'errors': []
        }

        # Get all valid cost account codes from LocationMapping
        valid_cost_accounts = set(LocationMapping.objects.values_list('cost_account_code', flat=True))

        # Get unique cost account codes from IQB
        cost_accounts = IQBDetail.objects.filter(upload=upload).values_list('cost_account_code', flat=True).distinct()

        missing_accounts = []
        for cost_account in cost_accounts:
            if not cost_account:
                continue

            if cost_account not in valid_cost_accounts:
                missing_accounts.append(cost_account)

        if missing_accounts:
            test_result['passed'] = False
            test_result['errors'].append({
                'message': 'Cost account codes not found in Split_Data/LocationMapping',
                'missing_accounts': missing_accounts[:20],  # First 20 examples
                'total_count': len(missing_accounts)
            })

        return test_result

    @staticmethod
    def _validate_pay_comp_codes(upload):
        """Validate that Pay Comp/Add Ded Codes exist in PayCompCodeMapping"""
        test_result = {
            'test_name': 'Pay Comp/Add Ded Code Validation',
            'description': 'Check if pay_comp_code values match PayCompCode Mapping',
            'passed': True,
            'errors': []
        }

        # Get all valid pay comp codes
        valid_pay_comp_codes = set(PayCompCodeMapping.objects.values_list('pay_comp_code', flat=True))

        # Get unique pay comp codes from IQB
        pay_comp_codes = IQBDetail.objects.filter(upload=upload).values_list('pay_comp_code', flat=True).distinct()

        missing_codes = []
        for pay_comp_code in pay_comp_codes:
            if not pay_comp_code:
                continue

            if pay_comp_code not in valid_pay_comp_codes:
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
