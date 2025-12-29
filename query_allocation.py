import sqlite3

# Connect to the database
conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()

# Check has_cost_allocation flag
cursor.execute("""
    SELECT period_id, has_cost_allocation
    FROM reconciliation_payperiod
    WHERE period_id = '2025-11-30'
""")
result = cursor.fetchone()
print(f"Period: {result[0]}")
print(f"has_cost_allocation flag: {result[1]}")

# Check if cost allocation data exists
cursor.execute("""
    SELECT COUNT(*)
    FROM reconciliation_parseddata
    WHERE pay_period_id = '2025-11-30'
    AND (iqb_cost_allocation IS NOT NULL OR tanda_cost_allocation IS NOT NULL)
""")
count = cursor.fetchone()[0]
print(f"\nRecords with cost allocation data: {count}")

if count > 0 and result[1] == 0:
    print("\n⚠️  ISSUE FOUND:")
    print("Cost allocation data EXISTS but has_cost_allocation flag is FALSE!")
    print("This is why the dashboard shows different next steps.")
elif count == 0:
    print("\nNo cost allocation data found - needs to be run.")

conn.close()
