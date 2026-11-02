import csv
import sqlite3

import csv

with open("data/employees.csv", "r") as file:

    reader = csv.DictReader(file)

    for row in reader:
        print(row)