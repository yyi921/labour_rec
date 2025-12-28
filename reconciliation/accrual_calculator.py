"""
Accrual Wage Calculator
Calculates accrued wages and on-costs for employees
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date
from django.utils import timezone


class AccrualWageCalculator:
    """
    Calculates accrued wages and on-costs

    On-cost rates:
    - Superannuation: 12%
    - Annual Leave: 7.7% (non-casual only)
    - Payroll Tax: 4.95%
    - WorkCover: 1.384%
    """

    # On-cost rates
    SUPER_RATE = Decimal('0.12')  # 12%
    ANNUAL_LEAVE_RATE = Decimal('0.077')  # 7.7%
    PAYROLL_TAX_RATE = Decimal('0.0495')  # 4.95%
    WORKCOVER_RATE = Decimal('0.01384')  # 1.384%

    # Fortnightly pay period days
    FORTNIGHTLY_DAYS = 14

    @classmethod
    def calculate_pro_rated_auto_pay(cls, auto_pay_amount, start_date, end_date):
        """
        Calculate pro-rated auto pay amount based on number of days

        Args:
            auto_pay_amount (Decimal): Fortnightly auto pay amount
            start_date (date): Start date of accrual period
            end_date (date): End date of accrual period

        Returns:
            dict: {
                'base_wage': Decimal,
                'days_in_period': int,
                'daily_rate': Decimal
            }
        """
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

        # Calculate number of days (inclusive)
        days_in_period = (end_date - start_date).days + 1

        # Calculate daily rate
        daily_rate = Decimal(str(auto_pay_amount)) / cls.FORTNIGHTLY_DAYS

        # Calculate pro-rated wage
        base_wage = daily_rate * days_in_period
        base_wage = base_wage.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        return {
            'base_wage': base_wage,
            'days_in_period': days_in_period,
            'daily_rate': daily_rate,
            'source': 'tanda_auto_pay'
        }

    @classmethod
    def calculate_on_costs(cls, base_wage, employee_type):
        """
        Calculate all on-costs based on base wage

        Args:
            base_wage (Decimal): Base wage amount
            employee_type (str): Employee type (e.g., 'Casual', 'Full Time', 'Part Time')

        Returns:
            dict: {
                'superannuation': Decimal,
                'annual_leave': Decimal,
                'payroll_tax': Decimal,
                'workcover': Decimal,
                'total_on_costs': Decimal,
                'grand_total': Decimal
            }
        """
        base_wage = Decimal(str(base_wage))

        # Calculate superannuation (all employees)
        superannuation = (base_wage * cls.SUPER_RATE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Calculate annual leave (non-casual only)
        is_casual = employee_type and 'casual' in employee_type.lower()
        annual_leave = Decimal('0')
        if not is_casual:
            annual_leave = (base_wage * cls.ANNUAL_LEAVE_RATE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Calculate payroll tax (all employees)
        payroll_tax = (base_wage * cls.PAYROLL_TAX_RATE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Calculate workcover (all employees)
        workcover = (base_wage * cls.WORKCOVER_RATE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Total on-costs
        total_on_costs = superannuation + annual_leave + payroll_tax + workcover

        # Grand total (base wage + on-costs)
        grand_total = base_wage + total_on_costs

        return {
            'superannuation': superannuation,
            'annual_leave': annual_leave,
            'payroll_tax': payroll_tax,
            'workcover': workcover,
            'total_on_costs': total_on_costs,
            'grand_total': grand_total
        }

    @classmethod
    def calculate_accruals(cls, employee, tanda_shift_cost, start_date, end_date):
        """
        Calculate all accruals for an employee

        Args:
            employee: Employee model instance
            tanda_shift_cost (Decimal): Total shift cost from Tanda (if no auto pay)
            start_date (date or str): Start date of accrual period
            end_date (date or str): End date of accrual period

        Returns:
            dict: {
                'base_wage': Decimal,
                'superannuation': Decimal,
                'annual_leave': Decimal,
                'payroll_tax': Decimal,
                'workcover': Decimal,
                'total': Decimal,
                'source': str,
                'days_in_period': int,
                'employee_type': str
            }
        """
        # Determine base wage source
        if employee.auto_pay == 'Yes' and employee.auto_pay_amount and employee.auto_pay_amount > 0:
            # Use pro-rated auto pay
            pay_calc = cls.calculate_pro_rated_auto_pay(
                employee.auto_pay_amount,
                start_date,
                end_date
            )
            base_wage = pay_calc['base_wage']
            days_in_period = pay_calc['days_in_period']
            source = 'tanda_auto_pay'
        else:
            # Use Tanda shift cost
            base_wage = Decimal(str(tanda_shift_cost)) if tanda_shift_cost else Decimal('0')
            if isinstance(start_date, str):
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            if isinstance(end_date, str):
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            days_in_period = (end_date - start_date).days + 1
            source = 'tanda_shift_cost'

        # Calculate on-costs
        on_costs = cls.calculate_on_costs(base_wage, employee.employment_type)

        return {
            'base_wage': base_wage,
            'superannuation': on_costs['superannuation'],
            'annual_leave': on_costs['annual_leave'],
            'payroll_tax': on_costs['payroll_tax'],
            'workcover': on_costs['workcover'],
            'total': on_costs['grand_total'],
            'source': source,
            'days_in_period': days_in_period,
            'employee_type': employee.employment_type or ''
        }

    @classmethod
    def validate_employee_for_accrual(cls, employee, start_date):
        """
        Validate if employee should be included in accrual calculation

        Args:
            employee: Employee model instance
            start_date (date or str): Start date of accrual period

        Returns:
            tuple: (is_valid, reason)
        """
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()

        # Check if terminated before start period
        if employee.termination_date and employee.termination_date < start_date:
            return False, f"Terminated before start period ({employee.termination_date})"

        return True, "Valid"
