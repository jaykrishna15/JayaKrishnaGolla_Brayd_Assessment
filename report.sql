-- Query 1: Total net pay per site for locked October 2026 payroll.
SELECT
    site,
    SUM(net_pay_inr) AS total_net_pay_inr
FROM payslips
WHERE payroll_month = '2026-10'
GROUP BY site
ORDER BY total_net_pay_inr DESC;

-- Query 2: Employees whose net pay is below 75% of monthly gross.
SELECT
    employee_id,
    site,
    monthly_gross_inr,
    net_pay_inr,
    ROUND(net_pay_inr * 100.0 / NULLIF(monthly_gross_inr, 0), 2) AS net_pay_percentage
FROM payslips
WHERE payroll_month = '2026-10'
  AND monthly_gross_inr > 0
  AND net_pay_inr < monthly_gross_inr * 0.75
ORDER BY net_pay_percentage ASC;
