from src.transform.cleaners import (
    clean_title, company_norm, parse_salary_structured, parse_salary_text,
    redact_contacts, seniority,
)
from src.transform.counties import COUNTIES, map_location
from src.transform.skills import extract_skills


def test_47_counties():
    assert len(COUNTIES) == 47
    assert [c for c, _ in COUNTIES] == list(range(1, 48))


def test_location_mapping():
    assert map_location("Westlands, Nairobi")["county"] == "Nairobi"
    assert map_location("Ruiru")["county"] == "Kiambu"
    assert map_location("Taita-Taveta County")["county_code"] == 6
    assert map_location("Murang'a")["county_code"] == 21
    assert map_location("Kisumu City, Kenya")["county"] == "Kisumu"
    remote = map_location("Remote")
    assert remote["is_remote"] and remote["county"] is None
    assert map_location("Kenya")["county"] is None


def test_clean_title():
    assert clean_title("URGENT: SENIOR DATA ANALYST - Nairobi") == "Senior Data Analyst"
    assert clean_title("Data Engineer (Urgent) – Mombasa, Kenya") == "Data Engineer"
    assert clean_title("Driver - Kisumu Cement") == "Driver - Kisumu Cement"
    assert clean_title("hr and ict manager") == "HR and ICT Manager"


def test_seniority():
    assert seniority("Senior Data Engineer") == "senior"
    assert seniority("Fleet Manager") == "manager"
    assert seniority("Trainee Dealer") == "intern"
    assert seniority("Sales Field Agent") == "unspecified"
    assert seniority("Chief Accountant") == "senior"
    assert seniority("Chief Executive Officer") == "director"


def test_company_norm():
    assert company_norm("Safaricom PLC") == "safaricom"
    assert company_norm("Acme Kenya Ltd.") == "acme kenya"
    assert company_norm("Confidential") is None


def test_salary_text():
    s = parse_salary_text("Salary: KES 80,000 - 120,000 per month")
    assert (s["min_monthly_kes"], s["max_monthly_kes"]) == (80000, 120000)
    s = parse_salary_text("Ksh 50k - 70k monthly")
    assert (s["min_monthly_kes"], s["max_monthly_kes"]) == (50000, 70000)
    assert parse_salary_text("KES 1,200,000 per annum")["min_monthly_kes"] == 100000
    assert parse_salary_text("Salary: Negotiable") is None
    assert parse_salary_text("turnover of KES 200 million") is None


def test_salary_structured():
    s = parse_salary_structured(
        {"currency": "KES", "value": {"minValue": 60000, "maxValue": 90000, "unitText": "MONTH"}}
    )
    assert (s["min_monthly_kes"], s["max_monthly_kes"]) == (60000, 90000)
    zero = {"currency": "KES", "value": {"minValue": 0, "maxValue": 0, "unitText": "MONTH"}}
    assert parse_salary_structured(zero) is None


def test_skills():
    names = {n for n, _ in extract_skills("Python, SQL, Power-BI, PySpark and AWS Glue required")}
    assert {"Python", "SQL", "Power BI", "Spark", "AWS"} <= names
    names = {n for n, _ in extract_skills("Experience with MySQL")}
    assert "MySQL" in names and "SQL" not in names
    assert "Excel" not in {n for n, _ in extract_skills("someone who can excel at sales")}


def test_redact():
    out = redact_contacts("Email hr@company.co.ke or call 0712 345 678")
    assert "@" not in out and "678" not in out


def test_open_ended_text_salary_is_ignored():
    assert parse_salary_text("Monthly salary: up to KES 100,000 paid monthly") is None
    s = parse_salary_text("Salary from KES 50,000 to 70,000 per month")
    assert (s["min_monthly_kes"], s["max_monthly_kes"]) == (50000, 70000)