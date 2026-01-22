"""
File parsers for Tanda, Micropay IQB, and Micropay Journal
"""
import pandas as pd
from datetime import datetime
from decimal import Decimal
from reconciliation.models import (
    TandaTimesheet, IQBDetail, IQBDetailV2, JournalEntry, IQBLeaveBalance, Upload,
    SageLocation, SageDepartment, IQBTransactionType
)


class TandaParser:
    """Parse Tanda timesheet files"""
    
    @staticmethod
    def parse(upload, df):
        """
        Parse Tanda timesheet DataFrame and create database records
        
        Args:
            upload: Upload model instance
            df: pandas DataFrame with Tanda data
            
        Returns:
            int: Number of records created
        """
        records = []
        
        for _, row in df.iterrows():
            # Skip rows with no employee ID
            if pd.isna(row.get('Employee ID')):
                continue
            
            # Parse dates and times
            date_shift_start = TandaParser._parse_date(row.get('Date Shift Start.Date'))
            shift_start_time = TandaParser._parse_time(row.get('Shift Start Time'))
            date_shift_finish = TandaParser._parse_date(row.get('Date Shift Finish.Date'))
            shift_finish_time = TandaParser._parse_time(row.get('Shift Finish Time'))
            
            # Parse hours and cost
            shift_hours = TandaParser._parse_decimal(row.get('Shift Hours by GL'), 0)
            shift_cost = TandaParser._parse_decimal(row.get('Shift Cost by GL'), 0)
            
            record = TandaTimesheet(
                upload=upload,
                employee_id=str(row.get('Employee ID', '')).strip(),
                employee_name=str(row.get('Employee Name', '')).strip(),
                employment_type=str(row.get('Employment Type', '')).strip(),
                location_name=str(row.get('Location Name', '')).strip(),
                team_name=str(row.get('Team Name', '')).strip(),
                award_export_name=str(row.get('Award Export Name', '')).strip(),
                gl_code=str(row.get('GLCode', row.get('GL Code', ''))).strip(),
                date_shift_start=date_shift_start,
                shift_start_time=shift_start_time,
                date_shift_finish=date_shift_finish,
                shift_finish_time=shift_finish_time,
                shift_hours=shift_hours,
                shift_cost=shift_cost,
            )
            # Note: is_leave and leave_type are set automatically in model.save()
            
            records.append(record)
        
        # Bulk create for efficiency
        TandaTimesheet.objects.bulk_create(records, batch_size=500)
        
        return len(records)
    
    @staticmethod
    def _parse_date(date_value):
        """Parse date from various formats"""
        if pd.isna(date_value) or date_value == 'Unknown':
            return None
        
        try:
            if isinstance(date_value, str):
                # Try common formats
                for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y']:
                    try:
                        return datetime.strptime(date_value, fmt).date()
                    except:
                        continue
            elif isinstance(date_value, datetime):
                return date_value.date()
            elif hasattr(date_value, 'date'):
                return date_value.date()
        except:
            pass
        
        return None
    
    @staticmethod
    def _parse_time(time_value):
        """Parse time from various formats"""
        if pd.isna(time_value) or time_value == 'Unknown':
            return None
        
        try:
            if isinstance(time_value, str):
                # Try common formats
                for fmt in ['%H:%M', '%H:%M:%S', '%I:%M %p']:
                    try:
                        return datetime.strptime(time_value, fmt).time()
                    except:
                        continue
            elif isinstance(time_value, datetime):
                return time_value.time()
            elif hasattr(time_value, 'time'):
                return time_value.time()
        except:
            pass
        
        return None
    
    @staticmethod
    def _parse_decimal(value, default=0):
        """Parse decimal value safely"""
        if pd.isna(value):
            return Decimal(str(default))
        
        try:
            return Decimal(str(value))
        except:
            return Decimal(str(default))


class IQBParser:
    """Parse Micropay IQB files"""

    @staticmethod
    def parse(upload, df):
        """
        Parse Micropay IQB DataFrame and create database records
        Also populates IQBDetailV2 if the file contains the required columns

        Args:
            upload: Upload model instance
            df: pandas DataFrame with IQB data

        Returns:
            int: Number of records created
        """
        records = []
        records_v2 = []

        # Get period_end_date from first row for IQBDetailV2
        period_end_date = None
        if 'Period End Date' in df.columns and len(df) > 0:
            period_end_date = IQBParser._parse_date(df['Period End Date'].iloc[0])

        # Check if file has Leave Reason Description column (needed for V2)
        has_leave_reason = 'Leave Reason Description' in df.columns

        # Preload mapping data for IQBDetailV2
        if period_end_date:
            iqb_transaction_types = {
                tt.transaction_type: tt.include_in_costs
                for tt in IQBTransactionType.objects.filter(is_active=True)
            }
            sage_locations = {
                loc.location_id: loc.location_name
                for loc in SageLocation.objects.all()
            }
            sage_departments = {
                dept.department_id: dept.department_name
                for dept in SageDepartment.objects.all()
            }

            # Delete existing IQBDetailV2 records for this period
            deleted_count = IQBDetailV2.objects.filter(period_end_date=period_end_date).delete()[0]
            if deleted_count > 0:
                print(f"  Deleted {deleted_count} existing IQBDetailV2 records for {period_end_date}")

        for _, row in df.iterrows():
            # Skip rows with no employee code
            if pd.isna(row.get('Employee Code')):
                continue

            # Parse numeric values
            hours = IQBParser._parse_decimal(row.get('Hours'), 0)
            amount = IQBParser._parse_decimal(row.get('Amount'), 0)
            loading_amount = IQBParser._parse_decimal(row.get('Loading Amount'), 0)

            # Parse dates
            leave_start = IQBParser._parse_date(row.get('Leave Start Date'))
            leave_end = IQBParser._parse_date(row.get('Leave End Date'))

            # Create IQBDetail record
            record = IQBDetail(
                upload=upload,
                employee_code=str(row.get('Employee Code', '')).strip(),
                surname=str(row.get('Surname', '')).strip(),
                first_name=str(row.get('First Name', '')).strip(),
                full_name=str(row.get('Full Name', '')).strip(),
                employment_type=str(row.get('Employment Type', '')).strip(),
                location=str(row.get('Location', '')).strip(),
                cost_account_code=str(row.get('Cost Account Code', '')).strip(),
                cost_account_description=str(row.get('Cost Account Description', '')).strip(),
                pay_comp_code=str(row.get('Pay Comp/Add Ded Code', '')).strip(),
                pay_comp_desc=str(row.get('Pay Comp/Add Ded Desc', '')).strip(),
                transaction_type=str(row.get('Transaction Type', '')).strip(),
                hours=hours,
                amount=amount,
                leave_start_date=leave_start,
                leave_end_date=leave_end,
                loading_amount=loading_amount,
            )
            records.append(record)

            # Also create IQBDetailV2 record if period_end_date is available
            if period_end_date:
                # Get cost account and map to location/department
                cost_acc_code = str(row.get('Cost Account Code', '')).strip()
                default_cost_acc = str(row.get('Default Cost Account Code', '')).strip()

                # Map cost account to location and department
                location_id, location_name, dept_code, dept_name, mapped_cost_account = IQBParser._map_cost_account(
                    cost_acc_code, default_cost_acc, sage_locations, sage_departments
                )

                # Get transaction type and include_in_costs
                trans_type = str(row.get('Transaction Type', '')).strip()
                include_in_costs = iqb_transaction_types.get(trans_type, False)

                # Calculate period start (14 days before end)
                from datetime import timedelta
                period_start = period_end_date - timedelta(days=13)

                record_v2 = IQBDetailV2(
                    upload=upload,
                    file_name=upload.file_name,
                    period_end_date=period_end_date,
                    period_start_date=period_start,
                    employee_code=str(row.get('Employee Code', '')).strip(),
                    surname=str(row.get('Surname', '')).strip(),
                    first_name=str(row.get('First Name', '')).strip(),
                    given_names=str(row.get('Given Names', '')).strip(),
                    other_names=str(row.get('Other Names', '')).strip(),
                    full_name=str(row.get('Full Name', '')).strip(),
                    surname_with_initials=str(row.get('Surname with Initials', '')).strip(),
                    initials=str(row.get('Initials', '')).strip(),
                    date_of_birth=IQBParser._parse_date(row.get('Date Of Birth', '')),
                    age=IQBParser._parse_int(row.get('Age', '')),
                    hired_date=IQBParser._parse_date(row.get('Hired Date', '')),
                    years_of_service=IQBParser._parse_decimal(row.get('Years Of Service', ''), None),
                    employment_type=str(row.get('Employment Type', '')).strip(),
                    location=str(row.get('Location', '')).strip(),
                    pay_point=str(row.get('Pay Point', '')).strip(),
                    default_cost_account_code=default_cost_acc,
                    default_cost_account_description=str(row.get('Default Cost Account Description', '')).strip(),
                    pay_period_id=str(row.get('Pay Period ID', '')).strip(),
                    period_end_processed=str(row.get('Period End Processed', '')).strip(),
                    pay_comp_add_ded_code=str(row.get('Pay Comp/Add Ded Code', '')).strip(),
                    pay_comp_add_ded_desc=str(row.get('Pay Comp/Add Ded Desc', '')).strip(),
                    cost_account_code=mapped_cost_account,
                    cost_account_description=str(row.get('Cost Account Description', '')).strip(),
                    location_id=location_id,
                    location_name=location_name,
                    department_code=dept_code,
                    department_name=dept_name,
                    leave_start_date=leave_start,
                    leave_end_date=leave_end,
                    hours=hours or 0,
                    amount=amount or 0,
                    loading_amount=loading_amount or 0,
                    transaction_type=trans_type,
                    include_in_costs=include_in_costs,
                    leave_reason_code=str(row.get('Leave Reason Code', '')).strip(),
                    leave_reason_description=str(row.get('Leave Reason Description', '')).strip(),
                    rate=IQBParser._parse_decimal(row.get('Rate', ''), None),
                    transaction_location=str(row.get('Transaction Location', '')).strip(),
                )
                records_v2.append(record_v2)

        # Bulk create IQBDetail records
        IQBDetail.objects.bulk_create(records, batch_size=500)

        # Bulk create IQBDetailV2 records if any
        if records_v2:
            IQBDetailV2.objects.bulk_create(records_v2, batch_size=500)
            print(f"  Also created {len(records_v2)} IQBDetailV2 records for period {period_end_date}")

        return len(records)

    @staticmethod
    def _map_cost_account(cost_account_code, default_cost_account_code, sage_locations, sage_departments):
        """Map cost account code to location and department"""
        # If cost account is 100-1000, replace with default cost account
        if cost_account_code == '100-1000':
            cost_account_code = default_cost_account_code

        # Special case: If starts with SPL-, use full code for both location and department
        if cost_account_code and cost_account_code.startswith('SPL-'):
            return cost_account_code, cost_account_code, cost_account_code, cost_account_code, cost_account_code

        # Parse location and department from cost account code
        if cost_account_code and '-' in cost_account_code:
            parts = cost_account_code.split('-')
            location_id = parts[0].strip()
            dept_full = parts[1].strip() if len(parts) > 1 else ''

            # Department code is only the first 2 digits (e.g., "71" from "7100")
            dept_code = dept_full[:2] if len(dept_full) >= 2 else dept_full

            # Map to location name
            location_name = sage_locations.get(location_id, '')

            # Map to department name
            department_name = sage_departments.get(dept_code, '')

            return location_id, location_name, dept_code, department_name, cost_account_code
        else:
            return '', '', '', '', cost_account_code

    @staticmethod
    def _parse_int(value):
        """Parse integer value safely"""
        if pd.isna(value) or value == '':
            return None
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def _parse_date(date_value):
        """Parse date from various formats"""
        if pd.isna(date_value) or date_value in ['Unknown', '30/12/1899']:
            return None
        
        try:
            if isinstance(date_value, str):
                for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y']:
                    try:
                        return datetime.strptime(date_value, fmt).date()
                    except:
                        continue
            elif isinstance(date_value, datetime):
                return date_value.date()
            elif hasattr(date_value, 'date'):
                return date_value.date()
        except:
            pass
        
        return None
    
    @staticmethod
    def _parse_decimal(value, default=0):
        """Parse decimal value safely"""
        if pd.isna(value):
            return Decimal(str(default))
        
        try:
            return Decimal(str(value))
        except:
            return Decimal(str(default))


class JournalParser:
    """Parse Micropay Journal files"""
    
    @staticmethod
    def parse(upload, df):
        """
        Parse Micropay Journal DataFrame and create database records
        
        Args:
            upload: Upload model instance
            df: pandas DataFrame with Journal data
            
        Returns:
            int: Number of records created
        """
        records = []
        
        for _, row in df.iterrows():
            # Parse date
            date = JournalParser._parse_date(row.get('Date'))
            if not date:
                continue  # Skip if no valid date

            # Skip rows with no description (header rows, etc.)
            description = str(row.get('Description', '')).strip()
            if not description:
                continue
            
            # Parse numeric values
            debit = JournalParser._parse_decimal(row.get('Debit'), 0)
            credit = JournalParser._parse_decimal(row.get('Credit'), 0)
            hours = JournalParser._parse_decimal(row.get('Hours'), 0)
            
            record = JournalEntry(
                upload=upload,
                batch=str(row.get('Batch', '')).strip(),
                date=date,
                ledger_account=str(row.get('Ledger Account', '')).strip(),
                cost_account=str(row.get('Cost Account', '')).strip(),
                description=str(row.get('Description', '')).strip(),
                transaction=str(row.get('Transaction', '')).strip(),
                debit=debit,
                credit=credit,
                hours=hours,
            )
            
            records.append(record)
        
        # Bulk create for efficiency
        JournalEntry.objects.bulk_create(records, batch_size=500)
        
        return len(records)
    
    @staticmethod
    def _parse_date(date_value):
        """Parse date from various formats"""
        if pd.isna(date_value):
            return None
        
        try:
            if isinstance(date_value, str):
                for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y']:
                    try:
                        return datetime.strptime(date_value, fmt).date()
                    except:
                        continue
            elif isinstance(date_value, datetime):
                return date_value.date()
            elif hasattr(date_value, 'date'):
                return date_value.date()
        except:
            pass
        
        return None
    
    @staticmethod
    def _parse_decimal(value, default=0):
        """Parse decimal value safely"""
        if pd.isna(value):
            return Decimal(str(default))

        try:
            # Remove any currency symbols or commas
            if isinstance(value, str):
                value = value.replace('$', '').replace(',', '').strip()
            return Decimal(str(value))
        except:
            return Decimal(str(default))


class IQBLeaveBalanceParser:
    """Parse Micropay IQB Leave Balance files"""

    @staticmethod
    def parse(upload, df, as_of_date):
        """
        Parse Micropay IQB Leave Balance DataFrame and create database records

        Args:
            upload: Upload model instance
            df: pandas DataFrame with leave balance data
            as_of_date: Date this balance is as of (from pay period or user input)

        Returns:
            int: Number of records created
        """
        records = []

        for _, row in df.iterrows():
            # Skip rows with no employee code
            if pd.isna(row.get('Employee Code')):
                continue

            # Parse numeric values
            balance_hours = IQBLeaveBalanceParser._parse_decimal(row.get('Total Hours', 0), 0)
            balance_value = IQBLeaveBalanceParser._parse_decimal(row.get('Total Amount Liability Normal Rate', 0), 0)
            leave_loading = IQBLeaveBalanceParser._parse_decimal(row.get('Leave Loading Entitlement & Pro Rata Normal Rate', 0), 0)

            # Combine surname and first name for full name if Full Name column doesn't exist
            surname = str(row.get('Surname', '')).strip()
            first_name = str(row.get('First Name', '')).strip()
            full_name = f"{first_name} {surname}".strip() if first_name or surname else ''

            # Parse years of service
            years_of_service = IQBLeaveBalanceParser._parse_decimal(row.get('Years of Service', 0), 0)

            record = IQBLeaveBalance(
                upload=upload,
                employee_code=str(row.get('Employee Code', '')).strip(),
                surname=surname,
                first_name=first_name,
                full_name=full_name,
                employment_type=str(row.get('Employment Type', '')).strip(),
                location=str(row.get('Location', '')).strip(),
                years_of_service=years_of_service,
                leave_type=str(row.get('Leave Type', '')).strip(),
                leave_description=str(row.get('Leave Class Description', '')).strip(),
                balance_hours=balance_hours,
                balance_value=balance_value,
                leave_loading=leave_loading,
                as_of_date=as_of_date
            )

            records.append(record)

        # Bulk create for efficiency
        IQBLeaveBalance.objects.bulk_create(records, batch_size=500)

        return len(records)

    @staticmethod
    def _parse_decimal(value, default=0):
        """Parse decimal value safely"""
        if pd.isna(value):
            return Decimal(str(default))

        try:
            if isinstance(value, str):
                value = value.replace('$', '').replace(',', '').strip()
            return Decimal(str(value))
        except:
            return Decimal(str(default))