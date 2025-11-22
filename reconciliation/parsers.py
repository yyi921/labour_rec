"""
File parsers for Tanda, Micropay IQB, and Micropay Journal
"""
import pandas as pd
from datetime import datetime
from decimal import Decimal
from reconciliation.models import (
    TandaTimesheet, IQBDetail, JournalEntry, Upload
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
        
        Args:
            upload: Upload model instance
            df: pandas DataFrame with IQB data
            
        Returns:
            int: Number of records created
        """
        records = []
        
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
        
        # Bulk create for efficiency
        IQBDetail.objects.bulk_create(records, batch_size=500)
        
        return len(records)
    
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