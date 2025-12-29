import sqlite3

conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()

# Check the failed upload with more details
cursor.execute("""
    SELECT upload_id, file_name, status, error_message, record_count
    FROM reconciliation_upload
    WHERE upload_id = '7afb0fa8c0c04e8a9df8267c23c956f3'
""")

upload = cursor.fetchone()
if upload:
    print(f"Upload ID: {upload[0]}")
    print(f"File: {upload[1]}")
    print(f"Status: {upload[2]}")
    print(f"Record Count: {upload[4]}")
    print(f"\nError Message:")
    print(upload[3] if upload[3] else "(No error message)")

# Also check all leave balance uploads with errors
cursor.execute("""
    SELECT upload_id, file_name, status, error_message
    FROM reconciliation_upload
    WHERE source_system = 'Micropay_IQB_Leave'
    AND (status = 'failed' OR error_message IS NOT NULL OR error_message != '')
    ORDER BY uploaded_at DESC
""")

error_uploads = cursor.fetchall()
if error_uploads:
    print(f"\n\nAll leave balance uploads with errors:")
    for u in error_uploads:
        print(f"\n  {u[1]}")
        print(f"  Status: {u[2]}")
        print(f"  Error: {u[3]}")

conn.close()
