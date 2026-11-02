import sqlite3

conn = sqlite3.connect("payroll.db")

cursor = conn.cursor()

# Check employees
cursor.execute("SELECT * FROM employees")

print("EMPLOYEES:")
for row in cursor.fetchall():
    print(row)


# Check clock events
cursor.execute("SELECT * FROM clock_events")

print("\nCLOCK EVENTS:")
for row in cursor.fetchall():
    print(row)

conn.close()