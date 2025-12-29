import sqlite3

conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()

# Check schema of upload table
cursor.execute("PRAGMA table_info(reconciliation_upload)")
columns = cursor.fetchall()
print("Upload table columns:")
for col in columns:
    print(f"  {col[1]}")

print("\n" + "="*50 + "\n")

# Check uploads for pay period 2025-11-16
cursor.execute("""
    SELECT source_system, filename, is_active, created_at
    FROM reconciliation_upload
    WHERE pay_period_id = '2025-11-16'
    ORDER BY created_at
""")

uploads = cursor.fetchall()
print(f"Uploads for pay period 2025-11-16 ({len(uploads)} total):")
for u in uploads:
    print(f"  - {u[0]} (active={u[2]}): {u[1]}")

# Also check what source systems we have
cursor.execute("""
    SELECT DISTINCT source_system
    FROM reconciliation_upload
    WHERE pay_period_id = '2025-11-16'
""")
systems = cursor.fetchall()
print(f"\nUnique source systems in this pay period:")
for s in systems:
    print(f"  - {s[0]}")

conn.close()
