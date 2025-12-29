import sqlite3

conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()

# Check actual values stored in the database
cursor.execute("""
    SELECT employee_code, leave_type, balance_hours, balance_value, leave_loading
    FROM reconciliation_iqbleavebalance
    WHERE as_of_date = '2025-11-16'
    LIMIT 10
""")

records = cursor.fetchall()
print("Leave balance data from database (2025-11-16):")
for r in records:
    print(f"  {r[0]} - {r[1]}")
    print(f"    Hours: {r[2]} (type: {type(r[2])})")
    print(f"    Value: {r[3]} (type: {type(r[3])})")
    print(f"    Loading: {r[4]} (type: {type(r[4])})")

conn.close()
