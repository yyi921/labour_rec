import pandas as pd

file_path = 'media/uploads/Micropay_IQB_Leave_2025-11-16_v4_70ece963.csv'

try:
    df = pd.read_csv(file_path, low_memory=False)
    print(f"File loaded successfully!")
    print(f"Rows: {len(df)}")
    print(f"\nColumns ({len(df.columns)} total):")
    for i, col in enumerate(df.columns, 1):
        print(f"  {i}. '{col}'")

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
        print(f"  {col}: {'OK' if exists else 'MISSING'}")

    # Check first few rows
    print(f"\nFirst 3 rows:")
    print(df.head(3))

    # Check for Employee Code nulls
    null_count = df['Employee Code'].isna().sum() if 'Employee Code' in df.columns else 0
    print(f"\nRows with null Employee Code: {null_count}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
