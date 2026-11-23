"""Cheap rule-based prefilter. It is deliberately loose: its job is to throw away the
obvious junk (software engineers, VPs, Dallas) so Claude only reads plausible roles.
Claude makes the real fit/score call against the profile."""
from __future__ import annotations

import re

LOCATIONS = {
    "NYC": re.compile(r"\b(new york|nyc|manhattan|brooklyn|ny,? ny|new york,? ny)\b", re.I),
    "NJ-Hudson": re.compile(r"\b(jersey city|hoboken|weehawken)\b", re.I),
    "Chicago": re.compile(r"\bchicago\b", re.I),
}

INTERN = re.compile(r"\b(intern|internship|summer analyst|summer associate|summer program|co-?op|off-?cycle|placement year|insight (week|program)|sneak peek|spring week)\b", re.I)
SUMMER = re.compile(r"\bsummer\b", re.I)

SENIOR = re.compile(
    r"\b(vice president|\bvp\b|svp|avp|director|managing director|\bmd\b|executive director|"
    r"senior|sr\.?|principal|head of|lead|manager|chief|partner|experienced|lateral)\b", re.I)

RELEVANT = re.compile(
    r"(trad(e|er|ing)|sales|markets?\b|desk|execution|equit|fixed income|rates\b|credit|"
    r"derivativ|options?\b|commodit|\bfx\b|foreign exchange|futures|structur|research|"
    r"analyst program|graduate|new analyst|campus|capital markets|investment bank|"
    r"corporate bank|commercial bank|relationship analyst|securiti|prime\b|financing|delta one|"
    r"\betf\b|municipal|syndicate|portfolio|market structure|liquidity|global markets|s&t|"
    r"sales & trading|sales and trading|ficc|treasury)", re.I)

IRRELEVANT_TITLE = re.compile(
    r"(software|engineer|developer|devops|sre\b|technolog|\bit\b|cyber|security architect|"
    r"data scien|machine learning|\bml\b|\bai\b engineer|infrastructure|network|"
    r"compliance|audit|legal|counsel|paralegal|\bhr\b|human resources|recruit|talent acquisition|"
    r"marketing|communications|graphic|designer|accountant|accounting|\btax\b|payroll|"
    r"administrative|receptionist|office assistant|executive assistant|facilities|"
    r"operations|settlement|middle office|back office|reconcil|onboarding|kyc|aml|"
    r"customer service|call center|teller|branch|mortgage|loan officer|underwriter|"
    r"insurance|claims|nurse|driver|warehouse|retail|financial advisor|wealth advisor|"
    r"product manager|project manager|business analyst|\bqa\b|\btest)", re.I)

# phrases that override an IRRELEVANT_TITLE hit (e.g. "Trading Assistant")
KEEP_ANYWAY = re.compile(r"(trading assistant|sales trader|trading analyst|electronic trading|"
                         r"execution services|sales & trading|sales and trading)", re.I)

HEAVY_QUANT = re.compile(r"\b(ph\.?d|master'?s (degree )?in (math|physics|computer science|statistics)|"
                         r"quantitative researcher|quant researcher|c\+\+|strong programming)\b", re.I)

EXP = re.compile(r"(\d+)\s*\+?\s*(?:-|–|to)?\s*(\d+)?\s*\+?\s*years?(?:'|’)?\s*(?:of\s+)?(?:relevant\s+|professional\s+|related\s+|work\s+|full[- ]time\s+)*experience", re.I)
CLASS_YEAR = re.compile(r"\b(20(2[5-9]))\b")


def loc_bucket(location: str) -> str | None:
    for name, rx in LOCATIONS.items():
        if rx.search(location or ""):
            return name
    return None


def min_years(desc: str) -> int | None:
    vals = []
    for m in EXP.finditer(desc or ""):
        lo = int(m.group(1))
        if lo <= 15:
            vals.append(lo)
    return min(vals) if vals else None


def classify(job: dict) -> dict:
    """Returns {'keep': bool, 'reason': str, plus derived fields}."""
    title = job.get("title", "") or ""
    desc = job.get("description", "") or ""
    commitment = job.get("commitment", "") or job.get("job_type", "") or ""
    text = f"{title}\n{commitment}"

    out = {"loc_bucket": loc_bucket(job.get("location", "")), "flags": []}

    if not out["loc_bucket"]:
        return {**out, "keep": False, "reason": "location"}

    is_intern = bool(INTERN.search(text) or re.search(r"\bintern", commitment, re.I))
    out["track"] = "internship" if is_intern else "fulltime"

    if IRRELEVANT_TITLE.search(title) and not KEEP_ANYWAY.search(title):
        return {**out, "keep": False, "reason": "function"}
    if not RELEVANT.search(title) and not RELEVANT.search(desc[:1500]):
        return {**out, "keep": False, "reason": "function"}
    if SENIOR.search(title):
        return {**out, "keep": False, "reason": "seniority"}

    years = set(int(y) for y, _ in CLASS_YEAR.findall(f"{title} {desc[:3000]}"))
    if is_intern:
        # only Summer 2027 internships (2028 grads' programs are excluded; Andrew graduates May 2027)
        if not (SUMMER.search(title) or SUMMER.search(desc[:2000])):
            out["flags"].append("internship-not-summer")
        if years and 2027 not in years:
            return {**out, "keep": False, "reason": "internship-wrong-year"}
    else:
        if years and max(years) < 2027 and "program" in title.lower():
            return {**out, "keep": False, "reason": "program-wrong-class-year"}

    y = min_years(desc)
    if y is not None:
        out["min_years"] = y
        if y >= 3 and not is_intern:
            return {**out, "keep": False, "reason": "experience"}
        if y == 2:
            out["flags"].append("asks-2yrs")
    if re.search(r"\bassociate\b", title, re.I):
        out["flags"].append("associate-title")
    if HEAVY_QUANT.search(desc):
        out["flags"].append("quant-heavy?")
    return {**out, "keep": True, "reason": "ok"}
