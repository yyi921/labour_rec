"""
File type detection and period extraction for uploaded files
"""
import pandas as pd
from datetime import datetime, timedelta
import re


class FileDetector:
    """Detect file type and extract period from uploaded files"""
    
    # File signatures - columns that uniquely identify each file type
    FILE_SIGNATURES = {
        'Tanda_Timesheet': {
            'required_columns': [
                'Employee ID',
                'Employee Name',
                'Shift Hours by GL',
                'Shift Cost by GL',
                'Location Name'
            ],
            'optional_columns': ['Award Export Name', 'Team Name'],
        },
        'Micropay_IQB': {
            'required_columns': [
                'Employee Code',
                'Full Name',
                'Transaction Type',
                'Pay Comp/Add Ded Code',
                'Cost Account Code',
                'Amount'
            ],
            'optional_columns': ['Period End Date', 'Hours'],
        },
        'Micropay_Journal': {
            'required_columns': [
                'Ledger Account',
                'Cost Account',
                'Debit',
                'Date'
            ],
            'optional_columns': ['Credit', 'Hours', 'Transaction'],
        }
    }
    
    @staticmethod
    def detect_file_type(file_path):
        """
        Detect the type of uploaded file based on its structure
        
        Returns:
            tuple: (file_type, confidence, dataframe)
            - file_type: 'Tanda_Timesheet', 'Micropay_IQB', 'Micropay_Journal', or 'Unknown'
            - confidence: float between 0 and 1
            - dataframe: parsed pandas DataFrame
        """
        try:
            # Try to read the file (handles both CSV and Excel)
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path, low_memory=False)
            elif file_path.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(file_path)
            else:
                return ('Unknown', 0, None)
            
            # Score each file type based on column matches
            scores = {}
            for file_type, signature in FileDetector.FILE_SIGNATURES.items():
                score = 0
                total_possible = 0
                
                # Check required columns (weighted heavily)
                for col in signature['required_columns']:
                    total_possible += 10
                    if col in df.columns:
                        score += 10
                
                # Check optional columns (lighter weight)
                for col in signature['optional_columns']:
                    total_possible += 5
                    if col in df.columns:
                        score += 5
                
                # Calculate confidence as percentage
                confidence = score / total_possible if total_possible > 0 else 0
                scores[file_type] = confidence
            
            # Get the best match
            best_match = max(scores, key=scores.get)
            confidence = scores[best_match]
            
            # Only return confident matches (>70%)
            if confidence >= 0.7:
                return (best_match, confidence, df)
            else:
                return ('Unknown', confidence, df)
        
        except Exception as e:
            print(f"Error detecting file type: {e}")
            return ('Unknown', 0, None)
    
    @staticmethod
    def extract_period(file_type, df, filepath=None):
        """
        Extract pay period dates from the file

        Args:
            file_type: Type of file detected
            df: DataFrame containing the file data
            filepath: Optional path to the file (needed for Journal date extraction)

        Returns:
            dict: {
                'period_end': date,
                'period_start': date (optional, may be None),
                'period_id': str (YYYY-MM-DD format)
            }
        """
        try:
            if file_type == 'Tanda_Timesheet':
                return FileDetector._extract_tanda_period(df)
            elif file_type == 'Micropay_IQB':
                return FileDetector._extract_iqb_period(df)
            elif file_type == 'Micropay_Journal':
                return FileDetector._extract_journal_period(df, filepath)
            else:
                return None
        except Exception as e:
            print(f"Error extracting period: {e}")
            return None
    
    @staticmethod
    def _extract_tanda_period(df):
        """Extract period from Tanda timesheet"""
        # Get the latest shift start date (use start date, not finish date)
        date_columns = [col for col in df.columns if 'Date Shift Start' in col]

        if date_columns:
            # Parse dates (handle various formats)
            dates = pd.to_datetime(df[date_columns[0]], format='%d/%m/%Y', errors='coerce')
            period_end = dates.max()

            # Assume fortnight (14 days)
            period_start = period_end - timedelta(days=13)

            return {
                'period_end': period_end.date(),
                'period_start': period_start.date(),
                'period_id': period_end.date().isoformat()
            }

        return None
    
    @staticmethod
    def _extract_iqb_period(df):
        """Extract period from Micropay IQB"""
        if 'Period End Date' in df.columns:
            # Parse period end date
            period_end = pd.to_datetime(
                df['Period End Date'].iloc[0],
                format='%d/%m/%Y',
                errors='coerce'
            )
            
            if pd.notna(period_end):
                # Assume fortnight
                period_start = period_end - timedelta(days=13)
                
                return {
                    'period_end': period_end.date(),
                    'period_start': period_start.date(),
                    'period_id': period_end.date().isoformat()
                }
        
        return None
    
    @staticmethod
    def _extract_journal_period(df, filepath=None):
        """
        Extract period from Micropay Journal by reading date from filename

        Args:
            df: DataFrame (not used, kept for consistency)
            filepath: Path to the file (e.g., "Micropay_TSV GL Batch FNE 20250907 FN2.csv")

        Returns:
            dict with period_end only (no period_start for Journal files)
        """
        if not filepath:
            return None

        # Extract filename from full path
        import os
        filename = os.path.basename(filepath)

        # Look for 8-digit date pattern (YYYYMMDD) in filename
        pattern = r'(\d{8})'
        match = re.search(pattern, filename)

        if match:
            date_str = match.group(1)
            try:
                period_end = datetime.strptime(date_str, '%Y%m%d').date()

                return {
                    'period_end': period_end,
                    'period_start': None,  # No start date for Journal files
                    'period_id': period_end.isoformat()
                }
            except ValueError:
                pass

        return None
    
    @staticmethod
    def extract_from_filename(filename):
        """
        Try to extract period from filename as fallback
        
        Common patterns:
        - payroll_2025-10-05.csv
        - Tanda_20251005.xlsx
        - Week48_2025.csv
        """
        # Pattern 1: YYYY-MM-DD
        pattern1 = r'(\d{4})-(\d{2})-(\d{2})'
        match = re.search(pattern1, filename)
        if match:
            year, month, day = match.groups()
            try:
                period_end = datetime(int(year), int(month), int(day)).date()
                period_start = period_end - timedelta(days=13)
                return {
                    'period_end': period_end,
                    'period_start': period_start,
                    'period_id': period_end.isoformat()
                }
            except:
                pass
        
        # Pattern 2: YYYYMMDD
        pattern2 = r'(\d{8})'
        match = re.search(pattern2, filename)
        if match:
            date_str = match.group(1)
            try:
                period_end = datetime.strptime(date_str, '%Y%m%d').date()
                period_start = period_end - timedelta(days=13)
                return {
                    'period_end': period_end,
                    'period_start': period_start,
                    'period_id': period_end.isoformat()
                }
            except:
                pass
        
        return None