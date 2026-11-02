
import sqlite3

conn = sqlite3.connect("payroll.db")
cursor = conn.cursor()

with open("report.sql", "r", encoding="utf-8") as file:
    sql_content = file.read()

queries = [
    query.strip()
    for query in sql_content.split(";")
    if query.strip()
]

for index, query in enumerate(queries, start=1):
    print(f"\n========== REPORT {index} ==========")

    cursor.execute(query)

    columns = [col[0] for col in cursor.description]
    print(" | ".join(columns))

    for row in cursor.fetchall():
        print(" | ".join(str(value) for value in row))

conn.close()
