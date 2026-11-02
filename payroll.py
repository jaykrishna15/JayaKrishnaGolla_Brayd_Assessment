from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from calendar import monthrange
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable

DB_NAME = Path("payroll.db")
DATA_DIR = Path("data")
IST = timezone(timedelta(hours=5, minutes=30))
OCTOBER = "2026-10"
NOVEMBER = "2026-11"
CENT = Decimal("0.01")
RUPEE = Decimal("1")


@contextmanager
def db_connection():
    """Yield a SQLite connection with foreign keys and safe transaction handling."""
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _ensure_column(conn: sqlite3.Connection, table: str, name: str, definition: str) -> None:
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def create_database() -> None:
    """Create tables and safely upgrade databases from earlier script versions."""
    with db_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS employees (
                employee_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                site TEXT NOT NULL,
                monthly_gross_inr INTEGER NOT NULL CHECK(monthly_gross_inr >= 0),
                join_date TEXT NOT NULL,
                shift_start_ist TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clock_events (
                event_id TEXT PRIMARY KEY,
                employee_id TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('IN', 'OUT')),
                device_time TEXT NOT NULL,
                uploaded_at TEXT,
                FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
            );

            CREATE TABLE IF NOT EXISTS late_events (
                event_id TEXT PRIMARY KEY,
                employee_id TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('IN', 'OUT')),
                device_time TEXT NOT NULL,
                uploaded_at TEXT,
                FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
            );

            CREATE TABLE IF NOT EXISTS payroll_periods (
                payroll_month TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK(status IN ('OPEN', 'LOCKED')),
                locked_at TEXT
            );

            CREATE TABLE IF NOT EXISTS payslips (
                payslip_id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT NOT NULL,
                payroll_month TEXT NOT NULL,
                base_pay_paise INTEGER NOT NULL DEFAULT 0,
                overtime_pay_paise INTEGER NOT NULL DEFAULT 0,
                late_deduction_paise INTEGER NOT NULL DEFAULT 0,
                net_pay_inr INTEGER NOT NULL DEFAULT 0,
                site TEXT NOT NULL DEFAULT '',
                monthly_gross_inr INTEGER NOT NULL DEFAULT 0,
                paid_days REAL NOT NULL DEFAULT 0,
                arrears_paise INTEGER NOT NULL DEFAULT 0,
                full_days INTEGER NOT NULL DEFAULT 0,
                half_days INTEGER NOT NULL DEFAULT 0,
                absent_days INTEGER NOT NULL DEFAULT 0,
                sundays INTEGER NOT NULL DEFAULT 0,
                late_days INTEGER NOT NULL DEFAULT 0,
                overtime_minutes INTEGER NOT NULL DEFAULT 0,
                UNIQUE(employee_id, payroll_month),
                FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
            );

            CREATE TABLE IF NOT EXISTS payroll_arrears (
                employee_id TEXT NOT NULL,
                source_month TEXT NOT NULL,
                target_month TEXT NOT NULL,
                amount_paise INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(employee_id, source_month, target_month),
                FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
            );
        """)
        # Migration for databases created by the previous version of this project.
        additions = {
            "site": "TEXT NOT NULL DEFAULT ''",
            "monthly_gross_inr": "INTEGER NOT NULL DEFAULT 0",
            "paid_days": "REAL NOT NULL DEFAULT 0",
            "arrears_paise": "INTEGER NOT NULL DEFAULT 0",
            "full_days": "INTEGER NOT NULL DEFAULT 0",
            "half_days": "INTEGER NOT NULL DEFAULT 0",
            "absent_days": "INTEGER NOT NULL DEFAULT 0",
            "sundays": "INTEGER NOT NULL DEFAULT 0",
            "late_days": "INTEGER NOT NULL DEFAULT 0",
            "overtime_minutes": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, definition in additions.items():
            _ensure_column(conn, "payslips", column, definition)
    print("Database and tables are ready.")


def validate_month(month_text: str) -> tuple[int, int]:
    try:
        parsed = datetime.strptime(month_text, "%Y-%m")
    except (TypeError, ValueError) as exc:
        raise ValueError("Month must use YYYY-MM format, for example 2026-10.") from exc
    if parsed.strftime("%Y-%m") != month_text:
        raise ValueError("Month must use YYYY-MM format, for example 2026-10.")
    return parsed.year, parsed.month


def month_bounds(month_text: str) -> tuple[date, date, int]:
    year, month = validate_month(month_text)
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day), last_day


def parse_device_time(value: str) -> datetime:
    """Parse ISO-8601 timestamps; convert aware timestamps to IST."""
    value = (value or "").strip()
    if not value:
        raise ValueError("device_time cannot be empty.")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid device_time: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return parsed.astimezone(IST)


def _read_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"CSV file not found: {path}")
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        missing = required - headers
        if missing:
            raise ValueError(f"{path} is missing required columns: {', '.join(sorted(missing))}")
        return list(reader)


def load_employees(csv_path: Path | str = DATA_DIR / "employees.csv") -> int:
    path = Path(csv_path)
    rows = _read_csv(path, {
        "employee_id", "name", "site", "monthly_gross_inr", "join_date", "shift_start_ist"
    })
    prepared = []
    seen = set()
    for line_no, row in enumerate(rows, start=2):
        employee_id = (row.get("employee_id") or "").strip()
        name = (row.get("name") or "").strip()
        site = (row.get("site") or "").strip()
        if not employee_id or not name or not site:
            raise ValueError(f"{path}, row {line_no}: employee_id, name and site are required.")
        if employee_id in seen:
            raise ValueError(f"{path}, row {line_no}: duplicate employee_id {employee_id}.")
        seen.add(employee_id)
        try:
            gross = int((row.get("monthly_gross_inr") or "").strip())
            join_date = date.fromisoformat((row.get("join_date") or "").strip())
            shift_start = time.fromisoformat((row.get("shift_start_ist") or "").strip())
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{path}, row {line_no}: invalid gross, join_date or shift_start_ist.") from exc
        if gross < 0:
            raise ValueError(f"{path}, row {line_no}: monthly gross cannot be negative.")
        prepared.append((employee_id, name, site, gross, join_date.isoformat(), shift_start.isoformat(timespec="minutes")))

    with db_connection() as conn:
        for values in prepared:
            conn.execute("""
                INSERT OR IGNORE INTO employees
                    (employee_id, name, site, monthly_gross_inr, join_date, shift_start_ist)
                VALUES (?, ?, ?, ?, ?, ?)
            """, values)
    print(f"Employees loaded: {len(prepared)} row(s).")
    return len(prepared)


def _prepare_event_rows(rows: Iterable[dict[str, str]], path: Path) -> list[tuple]:
    prepared = []
    seen = set()
    for line_no, row in enumerate(rows, start=2):
        event_id = (row.get("event_id") or "").strip()
        employee_id = (row.get("employee_id") or "").strip()
        event_type = (row.get("type") or "").strip().upper()
        device_time = (row.get("device_time") or "").strip()
        uploaded_at = (row.get("uploaded_at") or "").strip() or None
        if not event_id or not employee_id:
            raise ValueError(f"{path}, row {line_no}: event_id and employee_id are required.")
        if event_id in seen:
            # Duplicate IDs inside one CSV are ignored after the first valid row.
            continue
        seen.add(event_id)
        if event_type not in {"IN", "OUT"}:
            raise ValueError(f"{path}, row {line_no}: type must be IN or OUT.")
        parse_device_time(device_time)
        if uploaded_at:
            parse_device_time(uploaded_at)
        prepared.append((event_id, employee_id, event_type, device_time, uploaded_at))
    return prepared


def _insert_events(conn: sqlite3.Connection, prepared: list[tuple], target_table: str) -> int:
    if target_table not in {"clock_events", "late_events"}:
        raise ValueError("Invalid event table.")
    inserted = 0
    for event_id, employee_id, event_type, device_time, uploaded_at in prepared:
        # Event IDs are globally unique across normal and late event files.
        exists = conn.execute("""
            SELECT 1 FROM clock_events WHERE event_id=?
            UNION ALL
            SELECT 1 FROM late_events WHERE event_id=? LIMIT 1
        """, (event_id, event_id)).fetchone()
        if exists:
            continue
        cursor = conn.execute(f"""
            INSERT OR IGNORE INTO {target_table}
                (event_id, employee_id, type, device_time, uploaded_at)
            VALUES (?, ?, ?, ?, ?)
        """, (event_id, employee_id, event_type, device_time, uploaded_at))
        inserted += max(cursor.rowcount, 0)
    return inserted


def load_clock_events(csv_path: Path | str = DATA_DIR / "clock_events.csv") -> int:
    path = Path(csv_path)
    rows = _read_csv(path, {"event_id", "employee_id", "type", "device_time"})
    prepared = _prepare_event_rows(rows, path)
    with db_connection() as conn:
        for event_id, employee_id, event_type, device_time, uploaded_at in prepared:
            duplicate = conn.execute(
                "SELECT 1 FROM clock_events WHERE event_id=? UNION ALL "
                "SELECT 1 FROM late_events WHERE event_id=? LIMIT 1",
                (event_id, event_id),
            ).fetchone()
            if duplicate:
                continue
            event_month = parse_device_time(device_time).strftime("%Y-%m")
            if _period_status(conn, event_month) == "LOCKED":
                raise ValueError(
                    f"Cannot add regular clock event {event_id}: payroll {event_month} is LOCKED. "
                    "Use the late-event workflow for approved late punches."
                )
        count = _insert_events(conn, prepared, "clock_events")
    print(f"Clock events loaded: {count} new event(s); duplicates ignored.")
    return count


def load_all_data() -> None:
    load_employees()
    load_clock_events()


def get_all_events(conn: sqlite3.Connection) -> dict[str, list[tuple[datetime, str]]]:
    grouped: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    rows = conn.execute("""
        SELECT employee_id, type, device_time FROM clock_events
        UNION ALL
        SELECT employee_id, type, device_time FROM late_events
    """).fetchall()
    for row in rows:
        grouped[row["employee_id"]].append((parse_device_time(row["device_time"]), row["type"]))
    return grouped


def calculate_attendance(month_text: str, conn: sqlite3.Connection | None = None) -> dict:
    month_start, month_end, _ = month_bounds(month_text)
    own_connection = conn is None
    if own_connection:
        conn = sqlite3.connect(DB_NAME, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
    assert conn is not None
    try:
        employees = conn.execute("SELECT * FROM employees ORDER BY employee_id").fetchall()
        events_by_employee = get_all_events(conn)
    finally:
        if own_connection:
            conn.close()

    results = {}
    for employee in employees:
        employee_id = employee["employee_id"]
        join_date = date.fromisoformat(employee["join_date"])
        shift_start = time.fromisoformat(employee["shift_start_ist"])
        first_eligible_day = max(month_start, join_date)
        counts = {"full_days": 0, "half_days": 0, "absent_days": 0,
                  "sundays": 0, "late_days": 0, "overtime_minutes": 0}
        flags = []
        daily_events: dict[date, list[tuple[datetime, str]]] = defaultdict(list)

        for stamp, kind in events_by_employee.get(employee_id, []):
            local_day = stamp.date()  # grouping is by IST calendar date, per brief
            if first_eligible_day <= local_day <= month_end:
                daily_events[local_day].append((stamp, kind))

        if first_eligible_day <= month_end:
            current_day = first_eligible_day
            while current_day <= month_end:
                if current_day.weekday() == 6:
                    counts["sundays"] += 1
                    current_day += timedelta(days=1)
                    continue  # work/events on Sunday are ignored

                day_events = daily_events.get(current_day, [])
                if not day_events:
                    counts["absent_days"] += 1
                else:
                    in_times = [stamp for stamp, kind in day_events if kind == "IN"]
                    out_times = [stamp for stamp, kind in day_events if kind == "OUT"]
                    if not in_times or not out_times:
                        counts["absent_days"] += 1
                        flags.append({"date": current_day.isoformat(), "flag": "MISSING_PUNCH"})
                    else:
                        first_in = min(in_times)
                        last_out = max(out_times)
                        elapsed = int((last_out - first_in).total_seconds() // 60)
                        # The brief defines any duration below 240 minutes as a half-day.
                        # A negative same-date interval therefore contributes zero worked
                        # minutes (half-day), rather than silently changing it to absence.
                        elapsed = max(0, elapsed)
                        if elapsed >= 240:
                            counts["full_days"] += 1
                        else:
                            counts["half_days"] += 1
                        shift_start_dt = datetime.combine(current_day, shift_start, tzinfo=IST)
                        if first_in > shift_start_dt + timedelta(minutes=10):
                            counts["late_days"] += 1
                        counts["overtime_minutes"] += max(0, elapsed - 540)
                current_day += timedelta(days=1)

        paid_days = counts["sundays"] + counts["full_days"] + counts["half_days"] * 0.5
        results[employee_id] = {
            "employee_id": employee_id,
            "name": employee["name"],
            "site": employee["site"],
            "monthly_gross": employee["monthly_gross_inr"],
            **counts,
            "paid_days": paid_days,
            "flags": flags,
        }
    return results


def _round_paise(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _to_paise(value: Decimal) -> int:
    return int((value * 100).quantize(RUPEE, rounding=ROUND_HALF_UP))


def calculate_payroll(month_text: str, conn: sqlite3.Connection | None = None) -> dict:
    _, _, days_in_month = month_bounds(month_text)
    own_connection = conn is None
    if own_connection:
        conn = sqlite3.connect(DB_NAME, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
    assert conn is not None
    try:
        attendance = calculate_attendance(month_text, conn)
    finally:
        if own_connection:
            conn.close()

    payslips = {}
    for employee_id, data in attendance.items():
        gross = Decimal(str(data["monthly_gross"]))
        daily_rate = gross / Decimal(days_in_month)
        paid_days = Decimal(str(data["paid_days"]))
        base_pay = _round_paise(daily_rate * paid_days)
        hourly_rate = daily_rate / Decimal("8")
        overtime_pay = _round_paise(
            Decimal(data["overtime_minutes"]) / Decimal("60") * hourly_rate * Decimal("1.5")
        )
        late_deduction = _round_paise(
            daily_rate * Decimal("0.5") * Decimal(data["late_days"] // 3)
        )
        net_pay = int((base_pay + overtime_pay - late_deduction).quantize(
            RUPEE, rounding=ROUND_HALF_UP
        ))
        payslips[employee_id] = {
            **data,
            "paid_days_decimal": paid_days,
            "base_pay": base_pay,
            "overtime_pay": overtime_pay,
            "late_deduction": late_deduction,
            "net_pay": net_pay,
        }
    return payslips


def _period_status(conn: sqlite3.Connection, month_text: str) -> str:
    row = conn.execute("SELECT status FROM payroll_periods WHERE payroll_month=?", (month_text,)).fetchone()
    return row["status"] if row else "OPEN"


def run_payroll(month_text: str) -> dict:
    validate_month(month_text)
    with db_connection() as conn:
        if _period_status(conn, month_text) == "LOCKED":
            raise ValueError(f"Payroll {month_text} is LOCKED; it cannot be recalculated.")
        employee_count = conn.execute("SELECT COUNT(*) AS n FROM employees").fetchone()["n"]
        if employee_count == 0:
            raise ValueError("No employees found. Run 'python payroll.py load' first.")
        slips = calculate_payroll(month_text, conn)
        conn.execute("""
            INSERT INTO payroll_periods(payroll_month, status)
            VALUES (?, 'OPEN') ON CONFLICT(payroll_month) DO NOTHING
        """, (month_text,))

        for employee_id, data in slips.items():
            previous = conn.execute("""
                SELECT arrears_paise FROM payslips
                WHERE employee_id=? AND payroll_month=?
            """, (employee_id, month_text)).fetchone()
            arrears_paise = previous["arrears_paise"] if previous else 0
            net_with_arrears = int((
                data["base_pay"] + data["overtime_pay"] - data["late_deduction"]
                + Decimal(arrears_paise) / Decimal(100)
            ).quantize(RUPEE, rounding=ROUND_HALF_UP))
            conn.execute("""
                INSERT INTO payslips (
                    employee_id, payroll_month, base_pay_paise, overtime_pay_paise,
                    late_deduction_paise, net_pay_inr, site, monthly_gross_inr,
                    paid_days, arrears_paise, full_days, half_days, absent_days,
                    sundays, late_days, overtime_minutes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(employee_id, payroll_month) DO UPDATE SET
                    base_pay_paise=excluded.base_pay_paise,
                    overtime_pay_paise=excluded.overtime_pay_paise,
                    late_deduction_paise=excluded.late_deduction_paise,
                    net_pay_inr=excluded.net_pay_inr,
                    site=excluded.site,
                    monthly_gross_inr=excluded.monthly_gross_inr,
                    paid_days=excluded.paid_days,
                    arrears_paise=excluded.arrears_paise,
                    full_days=excluded.full_days,
                    half_days=excluded.half_days,
                    absent_days=excluded.absent_days,
                    sundays=excluded.sundays,
                    late_days=excluded.late_days,
                    overtime_minutes=excluded.overtime_minutes
            """, (
                employee_id, month_text,
                _to_paise(data["base_pay"]), _to_paise(data["overtime_pay"]),
                _to_paise(data["late_deduction"]), net_with_arrears,
                data["site"], data["monthly_gross"], float(data["paid_days_decimal"]),
                arrears_paise, data["full_days"], data["half_days"],
                data["absent_days"], data["sundays"], data["late_days"],
                data["overtime_minutes"],
            ))
    print(f"Payroll {month_text} saved for {len(slips)} employee(s).")
    return slips


def lock_payroll(month_text: str) -> None:
    validate_month(month_text)
    with db_connection() as conn:
        if _period_status(conn, month_text) == "LOCKED":
            print(f"Payroll {month_text} is already LOCKED.")
            return
        employees = conn.execute("SELECT COUNT(*) AS n FROM employees").fetchone()["n"]
        payslips = conn.execute(
            "SELECT COUNT(*) AS n FROM payslips WHERE payroll_month=?", (month_text,)
        ).fetchone()["n"]
        if employees == 0 or payslips != employees:
            raise ValueError("Run payroll first; every employee must have exactly one payslip before locking.")
        conn.execute("""
            INSERT INTO payroll_periods(payroll_month, status, locked_at)
            VALUES (?, 'LOCKED', ?)
            ON CONFLICT(payroll_month) DO UPDATE SET
                status='LOCKED', locked_at=excluded.locked_at
        """, (month_text, datetime.now(IST).isoformat()))
    print(f"Payroll {month_text} is now LOCKED.")


def display_attendance(month_text: str) -> None:
    results = calculate_attendance(month_text)
    if not results:
        print("No employees found. Load employees first.")
        return
    for employee_id, data in results.items():
        print("\n" + "=" * 48)
        print(f"{employee_id} - {data['name']} ({data['site']})")
        print(f"Full days: {data['full_days']}")
        print(f"Half days: {data['half_days']}")
        print(f"Absent days: {data['absent_days']}")
        print(f"Sundays: {data['sundays']}")
        print(f"Paid days: {data['paid_days']}")
        print(f"Late days: {data['late_days']}")
        print(f"Overtime minutes: {data['overtime_minutes']}")
        if data["flags"]:
            print("Flags:", "; ".join(f"{f['date']}={f['flag']}" for f in data["flags"]))
        print("=" * 48)


def display_payslips(month_text: str, employee_id: str | None = None) -> None:
    validate_month(month_text)
    sql = """
        SELECT p.*, e.name FROM payslips p
        JOIN employees e ON e.employee_id=p.employee_id
        WHERE p.payroll_month=?
    """
    params: list = [month_text]
    if employee_id:
        sql += " AND p.employee_id=?"
        params.append(employee_id)
    sql += " ORDER BY p.employee_id"
    with db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    if not rows:
        print(f"No payslips found for {month_text}. Run 'python payroll.py run {month_text}' first.")
        return
    for row in rows:
        print("\n" + "=" * 48)
        print(f"Employee: {row['employee_id']} - {row['name']}")
        print(f"Site: {row['site']}")
        print(f"Payroll month: {row['payroll_month']}")
        print(f"Monthly gross: ₹{row['monthly_gross_inr']:,}")
        print(f"Paid days: {row['paid_days']}")
        print(f"Base pay: ₹{row['base_pay_paise'] / 100:,.2f}")
        print(f"Overtime pay: ₹{row['overtime_pay_paise'] / 100:,.2f}")
        print(f"Late deduction: ₹{row['late_deduction_paise'] / 100:,.2f}")
        print(f"Arrears: ₹{row['arrears_paise'] / 100:,.2f}")
        print(f"Net pay: ₹{row['net_pay_inr']:,}")
        print("=" * 48)


def process_late_events(csv_path: Path | str) -> None:
    """Import late punches and post net difference to November exactly once."""
    path = Path(csv_path)
    if not path.is_file() and (DATA_DIR / path.name).is_file():
        path = DATA_DIR / path.name
    rows = _read_csv(path, {"event_id", "employee_id", "type", "device_time"})
    prepared = _prepare_event_rows(rows, path)

    with db_connection() as conn:
        if _period_status(conn, OCTOBER) != "LOCKED":
            raise ValueError("Lock October payroll before processing late events.")
        if _period_status(conn, NOVEMBER) == "LOCKED":
            raise ValueError("November payroll is LOCKED; arrears cannot be posted to it.")
        # Validate referenced employees before inserting; all work is transactional.
        known_employees = {
            row["employee_id"] for row in conn.execute("SELECT employee_id FROM employees")
        }
        unknown = sorted({row[1] for row in prepared} - known_employees)
        if unknown:
            raise ValueError(f"Late events reference unknown employee(s): {', '.join(unknown)}")

        inserted_count = _insert_events(conn, prepared, "late_events")
        if inserted_count == 0:
            print("No new late events. Previously processed events will not create duplicate arrears.")
            return

        # Reconcile each employee represented in the file (including duplicates already stored).
        affected = sorted({row[1] for row in prepared})
        recalculated = calculate_payroll(OCTOBER, conn)
        now = datetime.now(IST).isoformat()

        for employee_id in affected:
            locked_october = conn.execute("""
                SELECT net_pay_inr FROM payslips
                WHERE employee_id=? AND payroll_month=?
            """, (employee_id, OCTOBER)).fetchone()
            if locked_october is None:
                raise ValueError(f"Locked October payslip is missing for {employee_id}.")

            revised_net = recalculated[employee_id]["net_pay"]
            # October net is stored in whole rupees; arrears are stored in paise.
            difference_paise = (revised_net - locked_october["net_pay_inr"]) * 100
            conn.execute("""
                INSERT INTO payroll_arrears
                    (employee_id, source_month, target_month, amount_paise, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(employee_id, source_month, target_month) DO UPDATE SET
                    amount_paise=excluded.amount_paise,
                    updated_at=excluded.updated_at
            """, (employee_id, OCTOBER, NOVEMBER, difference_paise, now))

            # Preserve November's normal salary components if November payroll was run.
            november = conn.execute("""
                SELECT base_pay_paise, overtime_pay_paise, late_deduction_paise
                FROM payslips WHERE employee_id=? AND payroll_month=?
            """, (employee_id, NOVEMBER)).fetchone()
            if november:
                base_paise = november["base_pay_paise"]
                overtime_paise = november["overtime_pay_paise"]
                deduction_paise = november["late_deduction_paise"]
            else:
                base_paise = overtime_paise = deduction_paise = 0

            net_total_paise = base_paise + overtime_paise - deduction_paise + difference_paise
            november_net = int((Decimal(net_total_paise) / Decimal(100)).quantize(
                RUPEE, rounding=ROUND_HALF_UP
            ))
            employee = conn.execute(
                "SELECT site, monthly_gross_inr FROM employees WHERE employee_id=?",
                (employee_id,),
            ).fetchone()
            conn.execute("""
                INSERT INTO payslips (
                    employee_id, payroll_month, base_pay_paise, overtime_pay_paise,
                    late_deduction_paise, net_pay_inr, site, monthly_gross_inr,
                    paid_days, arrears_paise
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(employee_id, payroll_month) DO UPDATE SET
                    net_pay_inr=excluded.net_pay_inr,
                    arrears_paise=excluded.arrears_paise
            """, (
                employee_id, NOVEMBER, base_paise, overtime_paise, deduction_paise,
                november_net, employee["site"], employee["monthly_gross_inr"], difference_paise,
            ))
            print(
                f"{employee_id}: October locked net ₹{locked_october['net_pay_inr']}; "
                f"revised October net ₹{revised_net}; "
                f"November arrears ₹{difference_paise / 100:,.2f}"
            )

    print(f"Late-event import complete: {inserted_count} new event(s). October payslips remain unchanged.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Brayd payroll assessment")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create or upgrade the SQLite database")
    sub.add_parser("load", help="Load employees and regular clock events")
    run = sub.add_parser("run", help="Calculate and save an unlocked payroll month")
    run.add_argument("month", help="Payroll month in YYYY-MM format")
    lock = sub.add_parser("lock", help="Lock a completed payroll month")
    lock.add_argument("month", help="Payroll month in YYYY-MM format")
    late = sub.add_parser("late", help="Import late punches and calculate arrears")
    late.add_argument("csv_file", help="Path to late_events.csv")
    slip = sub.add_parser("payslip", help="Display saved payslips")
    slip.add_argument("employee_id", help="Employee ID or ALL")
    slip.add_argument("month", help="Payroll month in YYYY-MM format")
    attendance = sub.add_parser("attendance", help="Display attendance summary")
    attendance.add_argument("month", help="Payroll month in YYYY-MM format")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        create_database()
        if args.command == "init":
            return 0
        if args.command == "load":
            load_all_data()
        elif args.command == "run":
            run_payroll(args.month)
            display_payslips(args.month)
        elif args.command == "lock":
            lock_payroll(args.month)
        elif args.command == "late":
            process_late_events(args.csv_file)
        elif args.command == "payslip":
            display_payslips(
                args.month,
                None if args.employee_id.upper() == "ALL" else args.employee_id,
            )
        elif args.command == "attendance":
            display_attendance(args.month)
        return 0
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
