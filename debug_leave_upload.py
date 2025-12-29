import sqlite3
import os

conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()

# Get the failed upload
cursor.execute("""
    SELECT upload_id, file_path, pay_period_id
    FROM reconciliation_upload
    WHERE upload_id = '7afb0fa8c0c04e8a9df8267c23c956f3'
""")

upload = cursor.fetchone()
if upload:
    upload_id, file_path, pay_period_id = upload
    print(f"Upload ID: {upload_id}")
    print(f"File path: {file_path}")
    print(f"Pay period: {pay_period_id}")
    print(f"File exists: {os.path.exists(file_path)}")

    if os.path.exists(file_path):
        # Try to read the file
        import pandas as pd
        try:
            df = pd.read_csv(file_path, low_memory=False)
            print(f"\nFile loaded successfully!")
            print(f"Rows: {len(df)}")
            print(f"Columns: {list(df.columns)}")
            print(f"\nFirst few rows:")
            print(df.head())

            # Check for required columns
            required_cols = [
                'Employee Code',
                'Leave Type',
                'Total Amount Liability Normal Rate',
                'Leave Loading Entitlement & Pro Rata Normal Rate'
            ]

            print(f"\nRequired column check:")
            for col in required_cols:
                exists = col in df.columns
                print(f"  {col}: {'✓' if exists else '✗ MISSING'}")

        except Exception as e:
            print(f"\nError reading file: {e}")
else:
    print("Upload not found")

conn.close()
