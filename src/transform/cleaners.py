"""Pure cleaning functions: no I/O, no database, easy to unit-test."""
from __future__ import annotations

import html as htmllib
import re
import unicodedata
from datetime import date

from bs4 import BeautifulSoup

from src.transform.counties import is_location_only


# ---------- generic text ----------
def norm_text(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    text = BeautifulSoup(htmllib.unescape(value), "html.parser").get_text(separator=" ")
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?254|0)[\s-]?[17]\d{2}[\s-]?\d{3}[\s-]?\d{3}(?!\d)")


def redact_contacts(text: str) -> str:
    return _PHONE.sub("[phone]", _EMAIL.sub("[email]", text))


def parse_date(value) -> date | None:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(value or ""))
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


# ---------- titles ----------
_NOISE_PREFIX = re.compile(
    r"^\s*(?:urgent(?:ly)?(?:\s+(?:required|hiring))?|hiring|vacancy|job(?:\s+vacancy)?"
    r"|we are hiring|wanted)\s*[:\-–—]\s*",
    re.I,
)
_NOISE_BRACKETS = re.compile(
    r"[\(\[\{][^)\]}]*\b(?:urgent|hiring|immediate|apply now|vacanc(?:y|ies)|new"
    r"|multiple positions?)\b[^)\]}]*[\)\]\}]",
    re.I,
)
_LOC_SUFFIX = re.compile(r"(?:\s*[-–—|,@]\s*|\s+(?:in|at)\s+)([A-Za-z' .]+)$", re.I)
_ACRONYMS = {
    "it", "ict", "hr", "qa", "qc", "erp", "bi", "sql", "api", "ceo", "cfo", "coo", "cto",
    "ui", "ux", "sap", "crm", "seo", "pr", "ngo", "gis", "hse", "sme", "aws", "kra", "m&e",
}
_SMALL = {"and", "or", "of", "the", "in", "for", "to", "a", "an", "at", "on", "&"}


def _smart_title(t: str) -> str:
    def cap(w: str) -> str:
        return w[:1].upper() + w[1:].lower()

    out = []
    for i, w in enumerate(t.split()):
        lw = w.lower()
        if lw in _ACRONYMS:
            out.append(lw.upper())
        elif i > 0 and lw in _SMALL:
            out.append(lw)
        else:
            out.append("-".join(cap(p) for p in w.split("-")))
    return " ".join(out)


def _fix_case(t: str) -> str:
    letters = [c for c in t if c.isalpha()]
    if not letters:
        return t
    ratio = sum(c.isupper() for c in letters) / len(letters)
    return _smart_title(t) if (ratio >= 0.6 or ratio == 0) else t  # SHOUTING or all-lowercase


def clean_title(raw: str | None) -> str:
    if not raw:
        return ""
    t = unicodedata.normalize("NFKC", htmllib.unescape(raw))
    t = re.sub(r"\s+", " ", t).strip()
    t = _NOISE_PREFIX.sub("", t)
    t = _NOISE_BRACKETS.sub(" ", t)
    for _ in range(3):  # strip trailing " - Nairobi", ", Kenya", " in Mombasa"
        m = _LOC_SUFFIX.search(t)
        if m and is_location_only(m.group(1)):
            t = t[: m.start()]
        else:
            break
    t = re.sub(r"\s+", " ", t).strip(" -–—|:,@")
    return _fix_case(t)


_LEVELS = [
    ("director", r"\b(director|vp|vice president|ceo|cfo|coo|cto|cio|chief (?:executive|financial|operating|technology|information|marketing|people|human resources?) officer)\b"),
    ("manager", r"\b(manager|head of|superintendent)\b"),
    ("senior", r"\b(senior|sr|lead|principal|chief|team leader)\b"),
    ("mid", r"\b(mid level|mid|intermediate)\b"),
    ("junior", r"\b(junior|jr|entry level|graduate)\b"),
    ("intern", r"\b(intern|interns|internship|attachment|attache|trainee|apprentice)\b"),
]


def seniority(title: str | None) -> str:
    t = norm_text(title)
    for level, pattern in _LEVELS:
        if re.search(pattern, t):
            return level
    return "unspecified"


# ---------- companies ----------
_LEGAL = re.compile(r"\b(?:limited|ltd|plc|inc|llc|llp|company|corp|corporation|gmbh)\b\.?", re.I)
_HIDDEN = {"confidential", "undisclosed", "anonymous", "our client", "client", "a leading company"}


def clean_company(name: str | None) -> str | None:
    if not name:
        return None
    name = re.sub(r"\s+", " ", htmllib.unescape(str(name))).strip()
    return name or None


def company_norm(name: str | None) -> str | None:
    n = norm_text(_LEGAL.sub(" ", name or ""))
    if not n or n in _HIDDEN or n.startswith("confidential"):
        return None
    return n


# ---------- salaries ----------
_UNIT = {"HOUR": "hour", "DAY": "day", "WEEK": "week", "MONTH": "month", "YEAR": "year", "ANNUM": "year"}
_TO_MONTH = {"month": 1, "year": 1 / 12, "week": 52 / 12, "day": 22, "hour": 176}
_CUR_MAP = {"kes": "KES", "ksh": "KES", "kshs": "KES", "sh": "KES", "shs": "KES",
            "usd": "USD", "us$": "USD", "$": "USD"}
_CUR = r"(?:kes|ksh|kshs|k\.sh|sh|shs|usd|us\$|\$)"
_AMT = r"\d[\d,]*(?:\.\d+)?"
_SAL_RE = re.compile(
    rf"(?<![A-Za-z])(?P<cur>{_CUR})\.?\s*(?P<lo>{_AMT})\s*(?P<lok>[km])?\b"
    rf"(?:\s*(?:-|–|—|to)\s*(?:{_CUR}\.?\s*)?(?P<hi>{_AMT})\s*(?P<hik>[km])?\b)?",
    re.I,
)

# "up to KES 100,000" / "from KES 50,000" state one bound, not a salary.
_OPEN_ENDED = re.compile(
    r"\b(?:up\s*to|as\s+(?:much|high)\s+as|maximum|max\.?|from|starting(?:\s+at|\s+from)?"
    r"|minimum|min\.?|over|above)\W*$",
    re.I,
)


def _num(x) -> float | None:
    if x is None or x == "":
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).replace(",", "").strip())
    except ValueError:
        return None


def finalize_salary(cur, lo, hi, period, source) -> dict | None:
    """Sanity-check and normalise. Implausible values are dropped, never guessed."""
    if lo is None or hi is None or hi <= 0:
        return None
    if lo > hi:
        lo, hi = hi, lo
    m_lo = m_hi = None
    if cur == "KES":
        if period is None and 5_000 <= lo <= 500_000:
            period = "month"  # typical monthly magnitude; otherwise too ambiguous
        factor = _TO_MONTH.get(period)
        if factor is None:
            return None
        m_lo, m_hi = lo * factor, hi * factor
        if not (5_000 <= m_lo <= 3_000_000 and m_hi <= 5_000_000):
            return None
    return {"currency": cur, "min": lo, "max": hi, "period": period,
            "min_monthly_kes": m_lo, "max_monthly_kes": m_hi, "source": source}


def parse_salary_structured(base_salary) -> dict | None:
    if not isinstance(base_salary, dict):
        return None
    cur = str(base_salary.get("currency") or "KES").upper()
    val = base_salary.get("value")
    if isinstance(val, dict):
        lo, hi = _num(val.get("minValue")), _num(val.get("maxValue"))
        single = _num(val.get("value"))
        unit = str(val.get("unitText") or "").upper()
    else:
        lo = hi = None
        single, unit = _num(val), ""
    if lo is None and hi is None:
        lo = hi = single
    lo = hi if lo is None else lo
    hi = lo if hi is None else hi
    return finalize_salary(cur, lo, hi, _UNIT.get(unit), "structured")


def _detect_period(window: str) -> str | None:
    w = window.lower()
    if re.search(r"per\s+(annum|year)|annual|\bp\.?a\b|/\s*(yr|year|annum)|yearly", w):
        return "year"
    if re.search(r"per\s+day|daily|/\s*day", w):
        return "day"
    if re.search(r"per\s+hour|hourly|/\s*(hr|hour)", w):
        return "hour"
    if re.search(r"per\s+week|weekly", w):
        return "week"
    if re.search(r"per\s+month|monthly|/\s*(mo|month)|a month", w):
        return "month"
    return None


def parse_salary_text(text: str | None) -> dict | None:
    """Fallback: find 'KES 80,000 - 120,000 per month' style amounts in free text."""
    if not text:
        return None
    mult = {"": 1, "k": 1_000, "m": 1_000_000}
    for m in _SAL_RE.finditer(text):
        cur = _CUR_MAP.get(re.sub(r"[^a-z$]", "", m["cur"].lower()))
        lo, hi = _num(m["lo"]), _num(m["hi"])
        if not cur or lo is None:
            continue
        before = text[max(0, m.start() - 25): m.start()]
        if m["hi"] is None and _OPEN_ENDED.search(before):
            continue  # a single bound is a ceiling/floor, not a salary
        lok, hik = (m["lok"] or "").lower(), (m["hik"] or "").lower()
        if hi is not None and not lok and hik and lo < 1000:  # "50 - 80k"
            lok = hik
        lo *= mult[lok]
        hi = hi * mult[hik] if hi is not None else lo
        result = finalize_salary(cur, lo, hi, _detect_period(text[m.end(): m.end() + 40]), "text")
        if result:
            return result
    return None