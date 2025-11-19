"""
Test script for file detection
Run with: python manage.py shell < reconciliation/test_detector.py
"""
from reconciliation.file_detector import FileDetector
import os

# Test with the uploaded files
test_files = [
    ('Tanda', r'C:\Users\yuany\OneDrive\Desktop\labour_reconciliation\media\test_data\Tanda_Timesheet Report by Hours, $, Export Name and Location (16).csv'),
    ('IQB', r'C:\Users\yuany\OneDrive\Desktop\labour_reconciliation\media\test_data\Micropay_TSV IQB-RET002 FNE 20251102 FN2.csv'),
    ('Journal', r'C:\Users\yuany\OneDrive\Desktop\labour_reconciliation\media\test_data\Micropay_TSV GL Batch FNE 20250907 FN2.csv'),
]

print("=" * 80)
print("FILE DETECTION TEST")
print("=" * 80)

for name, filepath in test_files:
    print(f"\nTesting: {name}")
    print(f"File: {os.path.basename(filepath)}")
    print("-" * 80)
    
    if os.path.exists(filepath):
        # Detect file type
        file_type, confidence, df = FileDetector.detect_file_type(filepath)
        
        print(f"Detected Type: {file_type}")
        print(f"Confidence: {confidence * 100:.1f}%")
        
        if df is not None:
            print(f"Rows: {len(df)}")
            print(f"Columns: {len(df.columns)}")
            print(f"Sample columns: {', '.join(df.columns[:5])}")
            
            # Extract period
            period_info = FileDetector.extract_period(file_type, df, filepath)
            if period_info:
                print(f"\nPeriod Detected:")
                print(f"  Period ID: {period_info['period_id']}")
                if period_info.get('period_start'):
                    print(f"  Start: {period_info['period_start']}")
                print(f"  End: {period_info['period_end']}")
            else:
                print("\nCould not extract period from file")
        else:
            print("Failed to parse file")
    else:
        print(f"File not found: {filepath}")
    
    print("=" * 80)