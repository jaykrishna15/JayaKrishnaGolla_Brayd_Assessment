# Brayd Payroll Assessment

Python 3.10+ and SQLite. No external database server is required.

## Project layout

```text
brayd-payroll-complete/
├── payroll.py
├── report.sql
├── README.md
├── NOTES.md
├── .gitignore
├── data/
│   ├── employees.csv
│   ├── clock_events.csv
│   └── late_events.csv
└── tests/
    └── test_payroll.py
```

## Setup

```bash
python -m venv .venv

python -m pip install pytest
```

## Run in this order

```bash
python payroll.py init
python payroll.py load
python payroll.py attendance 2026-10
python payroll.py run 2026-10
python payroll.py payslip ALL 2026-10
python payroll.py lock 2026-10
python payroll.py late data/late_events.csv
python payroll.py payslip ALL 2026-11
```

`payslip ALL 2026-11` shows November payslips created for employees with late-event adjustments. If November payroll has already been calculated, the arrears are added to its existing net pay. October payslips remain unchanged.

## Tests

```bash
python -m pytest -q
```

## SQL reports

Open `report.sql` against `payroll.db` after October has been locked.

## Important

Do not commit `payroll.db`, `.venv/`, or Python cache files. The code groups punches by the IST calendar date exactly as specified in the brief; it does not pair an overnight IN with the following calendar day's OUT.

## Employee Payslip Outputs – October 2026
### 1. Employee E01 – Ravi Kumar

```text
================================================
Employee: E01 - Ravi Kumar
Site: Kokapet
Payroll month: 2026-10
Monthly gross: ₹24,000
Paid days: 28.5
Base pay: ₹22,064.52
Overtime pay: ₹70.16
Late deduction: ₹0.00
Arrears: ₹0.00
Net pay: ₹22,135
================================================
```

### 2. Employee E02 – Lakshmi Devi

```text
================================================
Employee: E02 - Lakshmi Devi
Site: Kokapet
Payroll month: 2026-10
Monthly gross: ₹21,500
Paid days: 29.0
Base pay: ₹20,112.90
Overtime pay: ₹0.00
Late deduction: ₹346.77
Arrears: ₹0.00
Net pay: ₹19,766
================================================
```

### 3. Employee E03 – Arjun Reddy

```text
================================================
Employee: E03 - Arjun Reddy
Site: Gachibowli
Payroll month: 2026-10
Monthly gross: ₹27,900
Paid days: 19.0
Base pay: ₹17,100.00
Overtime pay: ₹22.50
Late deduction: ₹0.00
Arrears: ₹0.00
Net pay: ₹17,123
================================================
```

### 4. Employee E04 – Fatima Begum

```text
================================================
Employee: E04 - Fatima Begum
Site: Gachibowli
Payroll month: 2026-10
Monthly gross: ₹18,600
Paid days: 15.5
Base pay: ₹9,300.00
Overtime pay: ₹0.00
Late deduction: ₹0.00
Arrears: ₹0.00
Net pay: ₹9,300
================================================
```

### 5. Employee E05 – Suresh Naidu

```text
================================================
Employee: E05 - Suresh Naidu
Site: Kokapet
Payroll month: 2026-10
Monthly gross: ₹31,000
Paid days: 31.0
Base pay: ₹31,000.00
Overtime pay: ₹3,809.38
Late deduction: ₹1,000.00
Arrears: ₹0.00
Net pay: ₹33,809
================================================
```

### Payroll Summary

| Employee ID | Employee Name | Site | Net Pay |
|---|---|---|---:|
| E01 | Ravi Kumar | Kokapet | ₹22,135 |
| E02 | Lakshmi Devi | Kokapet | ₹19,766 |
| E03 | Arjun Reddy | Gachibowli | ₹17,123 |
| E04 | Fatima Begum | Gachibowli | ₹9,300 |
| E05 | Suresh Naidu | Kokapet | ₹33,809 |
| | **Total** | | **₹1,02,133** |

All five payslips were successfully generated using the payroll CLI for October 2026.

The following payslips were generated using the CLI command:

```bash
python payroll.py payslip <employee_id> 2026-10
```

