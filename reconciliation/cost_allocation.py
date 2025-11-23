"""
Cost allocation engine
Handles allocation from IQB, Tanda, and manual overrides
"""
from decimal import Decimal
from django.db.models import Sum, Count, Q
from reconciliation.models import (
    PayPeriod, Upload, IQBDetail, TandaTimesheet,
    CostAllocationRule, LocationMapping, DepartmentCostSummary
)


class CostAllocationEngine:
    """
    Manages cost allocation for employees across cost centers
    """
    
    # GL Account mapping
    GL_ACCOUNTS = {
        '6345': 'Salaries & Wages',
        '6370': 'Superannuation',
        '6300': 'Annual Leave',
        '6310': 'Sick Leave',
        '6320': 'Long Service Leave',
    }
    
    def __init__(self, pay_period):
        self.pay_period = pay_period
        self.iqb_upload = Upload.objects.filter(
            pay_period=pay_period,
            source_system='Micropay_IQB',
            is_active=True
        ).first()
        self.tanda_upload = Upload.objects.filter(
            pay_period=pay_period,
            source_system='Tanda_Timesheet',
            is_active=True
        ).first()
    
    def build_allocations(self, source='iqb'):
        """
        Build cost allocation rules for all employees

        Args:
            source: 'iqb' (default from IQB) or 'tanda' (from Tanda timesheets)

        Returns:
            dict: Summary of allocations created
        """
        if not self.iqb_upload:
            raise ValueError("No IQB data available")

        # Clear existing rules for this period and source only
        CostAllocationRule.objects.filter(pay_period=self.pay_period, source=source).delete()

        if source == 'iqb':
            return self._build_from_iqb()
        elif source == 'tanda':
            return self._build_from_tanda()
        else:
            raise ValueError(f"Unknown source: {source}")
    
    def _build_from_iqb(self):
        """
        Build allocations from IQB cost account codes
        This is the DEFAULT allocation
        """
        # Get all employees with their cost accounts from IQB
        employees = IQBDetail.objects.filter(
            upload=self.iqb_upload
        ).exclude(
            transaction_type__in=['Tax', 'Net Pay']
        ).values('employee_code', 'full_name').distinct()
        
        rules_created = []
        
        for emp in employees:
            emp_code = emp['employee_code']
            emp_name = emp['full_name']
            
            # Get total costs by cost account for this employee
            cost_accounts = IQBDetail.objects.filter(
                upload=self.iqb_upload,
                employee_code=emp_code
            ).exclude(
                transaction_type__in=['Tax', 'Net Pay']
            ).values('cost_account_code').annotate(
                total=Sum('amount')
            )
            
            # Calculate total for percentage
            total_amount = sum(item['total'] for item in cost_accounts if item['total'])
            
            if total_amount == 0:
                continue
            
            # Build allocation dict
            allocations = {}
            for item in cost_accounts:
                cost_account = item['cost_account_code']
                amount = item['total'] or Decimal('0')
                percentage = float((amount / total_amount) * 100)
                
                allocations[cost_account] = {
                    'percentage': round(percentage, 2),
                    'amount': float(amount),
                    'source': 'iqb'
                }
            
            # Create rule
            rule = CostAllocationRule(
                pay_period=self.pay_period,
                employee_code=emp_code,
                employee_name=emp_name,
                source='iqb',
                allocations=allocations
            )
            rule.validate_allocations()
            rule.save()
            
            rules_created.append(rule)
        
        return {
            'source': 'iqb',
            'rules_created': len(rules_created),
            'valid_rules': sum(1 for r in rules_created if r.is_valid),
            'invalid_rules': sum(1 for r in rules_created if not r.is_valid)
        }
    
    def _build_from_tanda(self):
        """
        Build allocations from Tanda timesheet locations
        Requires LocationMapping to be set up
        """
        if not self.tanda_upload:
            raise ValueError("No Tanda data available")
        
        # Get all employees with their location hours from Tanda
        employees = TandaTimesheet.objects.filter(
            upload=self.tanda_upload
        ).values('employee_id', 'employee_name').distinct()
        
        rules_created = []
        mapping_errors = []
        
        for emp in employees:
            emp_id = emp['employee_id']
            emp_name = emp['employee_name']
            
            # Get hours and costs by location + team combination
            location_data = TandaTimesheet.objects.filter(
                upload=self.tanda_upload,
                employee_id=emp_id
            ).values('location_name', 'team_name').annotate(
                total_hours=Sum('shift_hours'),
                total_cost=Sum('shift_cost')
            )

            # Calculate total
            total_hours = sum(item['total_hours'] for item in location_data if item['total_hours'])
            total_cost = sum(item['total_cost'] for item in location_data if item['total_cost'])

            if total_hours == 0 or total_cost == 0:
                continue

            # Map locations to cost accounts
            allocations = {}
            unmapped_locations = []

            for item in location_data:
                location_name = item['location_name']
                team_name = item['team_name']
                hours = item['total_hours'] or Decimal('0')
                cost = item['total_cost'] or Decimal('0')

                # Combine location and team to match LocationMapping format
                tanda_location = f"{location_name} - {team_name}"

                # Look up mapping
                try:
                    mapping = LocationMapping.objects.get(
                        tanda_location=tanda_location,
                        is_active=True
                    )
                    cost_account = mapping.cost_account_code
                except LocationMapping.DoesNotExist:
                    unmapped_locations.append(tanda_location)
                    continue
                
                # Calculate percentage based on cost
                percentage = float((cost / total_cost) * 100)
                
                # Accumulate if same cost account appears multiple times
                if cost_account in allocations:
                    allocations[cost_account]['percentage'] += percentage
                    allocations[cost_account]['amount'] += float(cost)
                    allocations[cost_account]['hours'] += float(hours)
                else:
                    allocations[cost_account] = {
                        'percentage': round(percentage, 2),
                        'amount': float(cost),
                        'hours': float(hours),
                        'source': 'tanda'
                    }
            
            if unmapped_locations:
                mapping_errors.append({
                    'employee': emp_name,
                    'unmapped_locations': unmapped_locations
                })
            
            if not allocations:
                # Fall back to IQB if no mappings
                continue
            
            # Round percentages
            for cost_account in allocations:
                allocations[cost_account]['percentage'] = round(
                    allocations[cost_account]['percentage'], 2
                )
            
            # Create rule
            rule = CostAllocationRule(
                pay_period=self.pay_period,
                employee_code=emp_id,
                employee_name=emp_name,
                source='tanda',
                allocations=allocations
            )
            rule.validate_allocations()
            rule.save()
            
            rules_created.append(rule)
        
        return {
            'source': 'tanda',
            'rules_created': len(rules_created),
            'valid_rules': sum(1 for r in rules_created if r.is_valid),
            'invalid_rules': sum(1 for r in rules_created if not r.is_valid),
            'mapping_errors': mapping_errors
        }
    
    def apply_override(self, employee_code, new_allocations, user):
        """
        Apply manual override to an employee's allocation
        
        Args:
            employee_code: Employee ID
            new_allocations: Dict of {cost_account: percentage}
            user: User making the change
        
        Returns:
            CostAllocationRule: Updated rule
        """
        # Get existing rule or create new one
        rule, created = CostAllocationRule.objects.get_or_create(
            pay_period=self.pay_period,
            employee_code=employee_code,
            defaults={
                'employee_name': employee_code,  # Will be updated
                'source': 'override'
            }
        )
        
        # Get employee's total cost from IQB
        total_cost = IQBDetail.objects.filter(
            upload=self.iqb_upload,
            employee_code=employee_code
        ).exclude(
            transaction_type__in=['Tax', 'Net Pay']
        ).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')
        
        # Build new allocations with amounts
        allocations = {}
        for cost_account, percentage in new_allocations.items():
            amount = float(total_cost) * (percentage / 100)
            allocations[cost_account] = {
                'percentage': percentage,
                'amount': amount,
                'source': 'override'
            }
        
        rule.source = 'override'
        rule.allocations = allocations
        rule.updated_by = user
        rule.validate_allocations()
        rule.save()
        
        return rule
    
    def get_verification_data(self, department_code=None):
        """
        Get data for verification view
        
        Args:
            department_code: Filter by department (e.g., '50' for Food)
        
        Returns:
            dict: Verification data with IQB, Tanda, and override allocations
        """
        # Get all employees with allocation rules
        rules = CostAllocationRule.objects.filter(
            pay_period=self.pay_period
        )
        
        # Filter by department if specified
        if department_code:
            # Get cost accounts for this department
            dept_cost_accounts = []
            for rule in rules:
                for cost_account in rule.allocations.keys():
                    dept = cost_account.split('-')[1][:2] if '-' in cost_account else ''
                    if dept == department_code:
                        dept_cost_accounts.append(cost_account)
            
            # Filter rules that have these cost accounts
            rules = [r for r in rules if any(
                ca in r.allocations for ca in dept_cost_accounts
            )]
        
        verification_data = []
        
        for rule in rules:
            # Get IQB allocation (original)
            iqb_allocations = self._get_iqb_allocation(rule.employee_code)
            
            # Get Tanda allocation (if available)
            tanda_allocations = self._get_tanda_allocation(rule.employee_code)
            
            # Get total costs by GL account
            gl_breakdown = self._get_gl_breakdown(rule.employee_code)
            
            verification_data.append({
                'employee_code': rule.employee_code,
                'employee_name': rule.employee_name,
                'total_cost': sum(gl_breakdown.values()),
                'gl_breakdown': gl_breakdown,
                'iqb_allocation': iqb_allocations,
                'tanda_allocation': tanda_allocations,
                'current_allocation': rule.allocations,
                'source': rule.source,
                'is_valid': rule.is_valid,
                'validation_errors': rule.validation_errors,
                'last_updated': rule.updated_at.isoformat(),
                'updated_by': rule.updated_by.username if rule.updated_by else None
            })
        
        return {
            'pay_period': self.pay_period.period_id,
            'department_code': department_code,
            'employee_count': len(verification_data),
            'employees': verification_data
        }
    
    def _get_iqb_allocation(self, employee_code):
        """Get allocation percentages from IQB"""
        cost_accounts = IQBDetail.objects.filter(
            upload=self.iqb_upload,
            employee_code=employee_code
        ).exclude(
            transaction_type__in=['Tax', 'Net Pay']
        ).values('cost_account_code').annotate(
            total=Sum('amount')
        )
        
        total = sum(item['total'] for item in cost_accounts if item['total'])
        
        if total == 0:
            return {}
        
        return {
            item['cost_account_code']: round(float((item['total'] / total) * 100), 2)
            for item in cost_accounts if item['total']
        }
    
    def _get_tanda_allocation(self, employee_code):
        """Get allocation percentages from Tanda (if available)"""
        if not self.tanda_upload:
            return {}

        location_data = TandaTimesheet.objects.filter(
            upload=self.tanda_upload,
            employee_id=employee_code
        ).values('location_name', 'team_name').annotate(
            total_cost=Sum('shift_cost')
        )

        total = sum(item['total_cost'] for item in location_data if item['total_cost'])

        if total == 0:
            return {}

        allocations = {}
        for item in location_data:
            location_name = item['location_name']
            team_name = item['team_name']
            cost = item['total_cost'] or Decimal('0')

            # Combine location and team to match LocationMapping format
            tanda_location = f"{location_name} - {team_name}"

            try:
                mapping = LocationMapping.objects.get(
                    tanda_location=tanda_location,
                    is_active=True
                )
                cost_account = mapping.cost_account_code
                percentage = round(float((cost / total) * 100), 2)

                if cost_account in allocations:
                    allocations[cost_account] += percentage
                else:
                    allocations[cost_account] = percentage
            except LocationMapping.DoesNotExist:
                continue

        return allocations
    
    def _get_gl_breakdown(self, employee_code):
        """Get employee's costs broken down by GL account"""
        # Mapping of transaction types to GL accounts
        transaction_gl_map = {
            'Hours By Rate': '6345',  # Salaries
            'Annual Leave': '6300',  # Annual Leave
            'Sick Leave': '6310',  # Sick Leave
            'Long Service Leave': '6320',  # LSL
            'Super': '6370',  # Superannuation
        }
        
        breakdown = {}
        
        for trans_type, gl_account in transaction_gl_map.items():
            amount = IQBDetail.objects.filter(
                upload=self.iqb_upload,
                employee_code=employee_code,
                transaction_type=trans_type
            ).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0')
            
            if amount > 0:
                breakdown[gl_account] = float(amount)
        
        return breakdown