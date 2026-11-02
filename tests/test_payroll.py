import csv
import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "payroll.py"
spec = importlib.util.spec_from_file_location("payroll", MODULE_PATH)
payroll = importlib.util.module_from_spec(spec)
spec.loader.exec_module(payroll)


def write_csv(path, headers, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(payroll, "DB_NAME", tmp_path / "payroll.db")
    data_dir = tmp_path / "data"
    monkeypatch.setattr(payroll, "DATA_DIR", data_dir)
    payroll.create_database()
    write_csv(data_dir / "employees.csv",
              ["employee_id", "name", "site", "monthly_gross_inr", "join_date", "shift_start_ist"],
              [{"employee_id": "E1", "name": "Test User", "site": "Site A",
                "monthly_gross_inr": "31000", "join_date": "2026-10-01", "shift_start_ist": "09:00"}])
    write_csv(data_dir / "clock_events.csv",
              ["event_id", "employee_id", "type", "device_time", "uploaded_at"],
              [
                  {"event_id": "C1", "employee_id": "E1", "type": "IN", "device_time": "2026-10-01T09:00:00+05:30", "uploaded_at": ""},
                  {"event_id": "C2", "employee_id": "E1", "type": "OUT", "device_time": "2026-10-01T18:30:00+05:30", "uploaded_at": ""},
                  {"event_id": "C3", "employee_id": "E1", "type": "IN", "device_time": "2026-10-02T09:20:00+05:30", "uploaded_at": ""},
                  {"event_id": "C4", "employee_id": "E1", "type": "OUT", "device_time": "2026-10-02T12:00:00+05:30", "uploaded_at": ""},
              ])
    payroll.load_all_data()
    return tmp_path


def test_attendance_thresholds_weekly_off_late_and_overtime(project):
    result = payroll.calculate_attendance("2026-10")["E1"]
    assert result["full_days"] == 1
    assert result["half_days"] == 1
    assert result["late_days"] == 1
    assert result["overtime_minutes"] == 30
    assert result["sundays"] == 4
    assert result["paid_days"] == 5.5


def test_duplicate_payroll_and_lock_protection(project):
    payroll.run_payroll("2026-10")
    payroll.run_payroll("2026-10")
    with payroll.db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM payslips WHERE payroll_month='2026-10'").fetchone()[0] == 1
    payroll.lock_payroll("2026-10")
    with pytest.raises(ValueError, match="LOCKED"):
        payroll.run_payroll("2026-10")


def test_late_events_create_idempotent_arrears_without_changing_october(project):
    payroll.run_payroll("2026-10")
    payroll.lock_payroll("2026-10")
    with payroll.db_connection() as conn:
        original = conn.execute("SELECT net_pay_inr FROM payslips WHERE employee_id='E1' AND payroll_month='2026-10'").fetchone()[0]

    late_path = project / "data" / "late_test.csv"
    write_csv(late_path,
              ["event_id", "employee_id", "type", "device_time", "uploaded_at"],
              [
                  {"event_id": "L1", "employee_id": "E1", "type": "IN", "device_time": "2026-10-03T09:00:00+05:30", "uploaded_at": "2026-11-03T04:30:00Z"},
                  {"event_id": "L2", "employee_id": "E1", "type": "OUT", "device_time": "2026-10-03T18:00:00+05:30", "uploaded_at": "2026-11-03T04:30:00Z"},
              ])
    payroll.process_late_events(late_path)
    payroll.process_late_events(late_path)

    with payroll.db_connection() as conn:
        october_after = conn.execute("SELECT net_pay_inr FROM payslips WHERE employee_id='E1' AND payroll_month='2026-10'").fetchone()[0]
        november = conn.execute("SELECT arrears_paise, net_pay_inr FROM payslips WHERE employee_id='E1' AND payroll_month='2026-11'").fetchone()
        arrears_count = conn.execute("SELECT COUNT(*) FROM payroll_arrears").fetchone()[0]
    assert october_after == original
    assert november["arrears_paise"] == 100000
    assert november["net_pay_inr"] == 1000
    assert arrears_count == 1


def test_utc_timestamp_is_converted_to_ist_calendar_day():
    local = payroll.parse_device_time("2026-09-30T18:45:00Z")
    assert local.date().isoformat() == "2026-10-01"
    assert local.hour == 0 and local.minute == 15


def test_invalid_timestamp_is_rejected():
    with pytest.raises(ValueError, match="Invalid device_time"):
        payroll.parse_device_time("not-a-timestamp")
