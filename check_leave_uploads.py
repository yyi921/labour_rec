import sqlite3

conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()

# Check recent leave balance uploads
cursor.execute("""
    SELECT upload_id, source_system, file_name, is_active, uploaded_at, record_count, status, error_message, pay_period_id
    FROM reconciliation_upload
    WHERE source_system = 'Micropay_IQB_Leave'
    ORDER BY uploaded_at DESC
    LIMIT 5
""")

uploads = cursor.fetchall()
print(f"Recent Leave Balance uploads ({len(uploads)} total):")
for u in uploads:
    print(f"\n  Upload ID: {u[0]}")
    print(f"  File: {u[2]}")
    print(f"  Active: {u[3]}")
    print(f"  Pay Period: {u[8]}")
    print(f"  Record Count: {u[5]}")
    print(f"  Status: {u[6]}")
    if u[7]:
        print(f"  Error: {u[7]}")

# Check if any IQB Leave Balance records exist
cursor.execute("""
    SELECT COUNT(*)
    FROM reconciliation_iqbleavebalance
""")
count = cursor.fetchone()[0]
print(f"\nTotal IQBLeaveBalance records in database: {count}")

if count > 0:
    cursor.execute("""
        SELECT employee_code, leave_type, balance_value, as_of_date
        FROM reconciliation_iqbleavebalance
        LIMIT 5
    """)
    records = cursor.fetchall()
    print("\nSample records:")
    for r in records:
        print(f"  {r[0]} - {r[1]}: ${r[2]} as of {r[3]}")

conn.close()
