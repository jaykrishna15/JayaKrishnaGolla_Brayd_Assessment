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

The following payslips were generated using the CLI command:

```bash
python payroll.py payslip <employee_id> 2026-10
```

