"""
Test override functionality
"""
import requests
import os

BASE_URL = 'http://127.0.0.1:8000'

# Get the first upload ID
response = requests.get(f'{BASE_URL}/api/uploads/')
uploads = response.json()['uploads']
tanda_upload = next((u for u in uploads if u['source_system'] == 'Tanda_Timesheet' and u['is_active']), None)

if not tanda_upload:
    print("No Tanda upload found to override")
    exit()

upload_id = tanda_upload['upload_id']
print(f"Testing override for upload: {upload_id}")
print(f"Current version: {tanda_upload['version']}")
print("-" * 80)

# Override with the same file
filepath = 'media/test_data/Tanda_Timesheet Report by Hours, $, Export Name and Location (16).csv'

with open(filepath, 'rb') as f:
    files = {'file': (os.path.basename(filepath), f)}
    data = {'reason': 'Testing override functionality'}
    response = requests.post(f'{BASE_URL}/api/uploads/{upload_id}/override/', files=files, data=data)

print(f"Status Code: {response.status_code}")

if response.status_code == 200:
    result = response.json()
    print("✓ Override successful!")
    print(f"  Old version: {result['old_upload']['version']} (status: {result['old_upload']['status']})")
    print(f"  New version: {result['new_upload']['version']} (status: {result['new_upload']['status']})")
    print(f"  Records: {result['new_upload']['records_imported']}")
else:
    print(f"✗ Error: {response.json()}")