import sqlite3

conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()

# Check uploads for pay period 2025-11-16
cursor.execute("""
    SELECT source_system, file_name, is_active, uploaded_at
    FROM reconciliation_upload
    WHERE pay_period_id = '2025-11-16'
    ORDER BY uploaded_at
""")

uploads = cursor.fetchall()
print(f"Uploads for pay period 2025-11-16 ({len(uploads)} total):")
for u in uploads:
    print(f"  - {u[0]} (active={u[2]}): {u[1]}")

# Check what source systems we have
cursor.execute("""
    SELECT DISTINCT source_system
    FROM reconciliation_upload
    WHERE pay_period_id = '2025-11-16'
""")
systems = cursor.fetchall()
print(f"\nUnique source systems in this pay period:")
for s in systems:
    print(f"  - {s[0]}")

# Check if any IQB Leave Balance records exist at all
cursor.execute("""
    SELECT COUNT(*)
    FROM reconciliation_iqbleavebalance
""")
count = cursor.fetchone()[0]
print(f"\nTotal IQBLeaveBalance records in database: {count}")

conn.close()
