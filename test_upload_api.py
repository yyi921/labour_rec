"""
Test script for upload API
Run with: python test_upload_api.py
"""
import requests
import os

BASE_URL = 'http://127.0.0.1:8000'

# Test files
test_files = [
    ('Tanda', r'C:\Users\yuany\OneDrive\Desktop\labour_reconciliation\media\test_data\Tanda_Timesheet Report by Hours, $, Export Name and Location (16).csv'),
    ('IQB', r'C:\Users\yuany\OneDrive\Desktop\labour_reconciliation\media\test_data\Micropay_TSV IQB-RET002 FNE 20251102 FN2.csv'),
    ('Journal', r'C:\Users\yuany\OneDrive\Desktop\labour_reconciliation\media\test_data\Micropay_TSV GL Batch FNE 20250907 FN2.csv'),
]

print("=" * 80)
print("UPLOAD API TEST")
print("=" * 80)

for name, filepath in test_files:
    print(f"\n{name} Upload Test")
    print("-" * 80)
    
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        continue
    
    # Upload file
    with open(filepath, 'rb') as f:
        files = {'file': (os.path.basename(filepath), f)}
        response = requests.post(f'{BASE_URL}/api/uploads/smart/', files=files)
    
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Upload successful!")
        print(f"  File Type: {data['upload']['file_type']}")
        print(f"  Records: {data['upload']['records_imported']}")
        print(f"  Period: {data['period']['period_id']}")
        print(f"  Upload ID: {data['upload']['upload_id']}")
        
    elif response.status_code == 409:
        data = response.json()
        print(f"⚠ Duplicate detected")
        print(f"  Existing file: {data['existing_upload']['file_name']}")
        print(f"  Version: {data['existing_upload']['version']}")
        print(f"  Uploaded: {data['existing_upload']['uploaded_at']}")
        print(f"  Override URL: {BASE_URL}{data['actions']['override']}")
        
    else:
        print(f"✗ Error: {response.json()}")
    
    print("=" * 80)

# Test list uploads
print("\nListing all uploads:")
print("-" * 80)
response = requests.get(f'{BASE_URL}/api/uploads/')
if response.status_code == 200:
    data = response.json()
    print(f"Total uploads: {data['count']}")
    for upload in data['uploads'][:5]:
        print(f"  - {upload['source_system']} | v{upload['version']} | {upload['status']}")

print("\nTest complete!")