# Implementation Notes

## Assumptions and edge cases

- ISO-8601 timestamps with an explicit offset are converted to IST (UTC+05:30). A timestamp without an offset is assumed to already be IST.
- Events are grouped by their IST calendar date. For each non-Sunday date, the earliest IN and latest OUT are used. A missing IN or OUT means absent and raises `MISSING_PUNCH`.
- A valid event day with less than 240 worked minutes is a half-day. If the same-date latest OUT precedes the earliest IN, worked minutes are clamped to zero and the day follows the stated under-240-minute half-day rule.
- Sundays on or after the join date are paid weekly offs; Sunday clock events are ignored. Dates before joining are excluded.
- October daily pay uses 31 days. Other months use their actual calendar-day count.
- Late means earliest IN is strictly more than 10 minutes after shift start. Late deductions are half a daily rate for each complete group of three late days.
- Overtime is time beyond 540 worked minutes per valid day and is paid at 1.5 times the hourly rate.
- Money calculations use `Decimal`; line items are rounded to paise and net pay to the nearest rupee using half-up rounding.

## Low-pay interpretation

- A join date during October reduces the number of eligible paid working days; this explains a partial-month result such as E03.
- Half-days and missing punches reduce paid days. Late deductions apply only after each complete group of three late days.
- Overnight shifts can produce unusual attendance when their IN and OUT fall on different IST calendar dates. The implementation follows the assessment's explicit calendar-date grouping rule rather than silently pairing punches across dates. This should be confirmed with the assessor if overnight pairing was intended.
- High overtime totals should be checked against the source punches; Suresh's reported overtime is a data-validation point, not automatically a code error.

## Duplicate prevention and locking

- `event_id` is a primary key and is checked across both regular and late-event tables.
- A unique constraint on `(employee_id, payroll_month)` prevents duplicate payslips. Unlocked payroll runs update the existing payslip instead of inserting a second row.
- A locked payroll period refuses recalculation and rejects new regular punches for that month.
- Late punches are stored separately. Their net-pay difference is upserted into one arrears row per employee/source/target month, and repeated imports of the same event IDs do not add arrears again.
- Late-event processing writes the November adjustment only; it never updates the locked October payslip.

## Bug/validation note

During validation, a command was still running the old unconditional main block and printed October payroll even for a November payslip lookup. The CLI was changed so only the requested subcommand runs. A second validation issue involved the overnight shift: the code now follows the brief's explicit under-240-minute half-day rule for a same-date negative interval rather than reclassifying it as absence.

## If there were one more day

I would add stronger reconciliation reports for malformed/duplicate punch patterns, review overnight-shift policy with the business owner, add more integration tests for daylight/timezone offsets and employee join/exit dates, and document the approval workflow for late punches.
