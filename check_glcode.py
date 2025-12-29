import sqlite3

conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()

# Check GLCode population
cursor.execute("""
    SELECT
        COUNT(*) as total,
        SUM(CASE WHEN gl_code != '' AND gl_code IS NOT NULL THEN 1 ELSE 0 END) as with_glcode,
        SUM(CASE WHEN gl_code = '' OR gl_code IS NULL THEN 1 ELSE 0 END) as without_glcode
    FROM reconciliation_tandatimesheet
    WHERE upload_id = '0db85c51b1a1467281ed2b1111db4c52'
""")
result = cursor.fetchone()
print(f'Total Tanda records: {result[0]}')
print(f'Records WITH GLCode: {result[1]}')
print(f'Records WITHOUT GLCode: {result[2]}')

# Show sample of locations without GLCode
cursor.execute("""
    SELECT DISTINCT location_name
    FROM reconciliation_tandatimesheet
    WHERE upload_id = '0db85c51b1a1467281ed2b1111db4c52'
    AND (gl_code IS NULL OR gl_code = '')
    ORDER BY location_name
    LIMIT 20
""")
blank_gl = cursor.fetchall()
print(f'\nLocations without GLCode:')
for loc in blank_gl:
    print(f'  {loc[0]}')

# Show sample with GLCode
cursor.execute("""
    SELECT DISTINCT location_name, gl_code
    FROM reconciliation_tandatimesheet
    WHERE upload_id = '0db85c51b1a1467281ed2b1111db4c52'
    AND gl_code IS NOT NULL AND gl_code != ''
    ORDER BY location_name
    LIMIT 10
""")
with_gl = cursor.fetchall()
print(f'\nSample locations WITH GLCode:')
for loc in with_gl:
    print(f'  {loc[0]:40} -> {loc[1]}')

conn.close()
