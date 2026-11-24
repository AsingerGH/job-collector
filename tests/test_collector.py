import json
from datetime import date, timedelta

import pytest

from collector import ats, collect
from collector.classify import classify
from collector.util import parse_date, strip_html


# ------------------------------------------------------------ classification
@pytest.mark.parametrize("title,loc,desc,keep,track", [
    ("Global Markets Analyst - GM Platform and E-Trading", "New York, NY", "", True, "fulltime"),
    ("Analyst, Equity Trading", "New York, NY", "0-2 years of experience", True, "fulltime"),
    ("Trading Assistant", "Jersey City, NJ", "", True, "fulltime"),
    ("Sales Trader", "Chicago, IL", "", True, "fulltime"),
    ("2027 Sales & Trading Summer Analyst", "New York, NY", "Summer 2027 internship", True, "internship"),
    ("2028 Summer Analyst - Global Markets", "New York, NY", "for 2029 graduates, summer 2028", False, "internship"),
    ("Vice President, Rates Trading", "New York, NY", "", False, None),
    ("Software Engineer, Trading Platform", "New York, NY", "", False, None),
    ("Trade Operations Analyst", "New York, NY", "", False, None),
    ("Rates Sales Analyst", "Dallas, TX", "", False, None),
    ("Electronic Trading Analyst", "New York, NY", "5+ years of relevant experience", False, None),
    ("2026 Markets Program Analyst", "New York, NY", "class of 2026 graduates", False, None),
    ("2027 Early Talent Rotational Program - Equities & Fixed Income", "New York, NY", "", True, "fulltime"),
])
def test_classify(title, loc, desc, keep, track):
    c = classify({"title": title, "location": loc, "description": desc})
    assert c["keep"] is keep, c
    if keep:
        assert c["track"] == track


def test_flags():
    c = classify({"title": "Associate, Execution Services", "location": "New York, NY",
                  "description": "2+ years of experience preferred. PhD in physics a plus."})
    assert c["keep"] and "asks-2yrs" in c["flags"] and "associate-title" in c["flags"] and "quant-heavy?" in c["flags"]


def test_parse_date():
    assert parse_date("Posted 3 Days Ago") == (date.today() - timedelta(days=3)).isoformat()
    assert parse_date("Posted Today") == date.today().isoformat()
    assert parse_date("2026-11-20T12:00:00-05:00") == "2026-11-20"
    assert parse_date(1763600000000)[:4] == "2025"
    assert parse_date("Posted 30+ Days Ago") == (date.today() - timedelta(days=30)).isoformat()


def test_strip_html_double_escaped():
    assert strip_html("&lt;p&gt;Trade &amp;amp; sell&lt;/p&gt;") == "Trade & sell"


# --------------------------------------------------------------- ATS parsing
def test_greenhouse(monkeypatch):
    monkeypatch.setattr(ats, "get_json", lambda url, **k: {"jobs": [{
        "id": 1, "title": "Trading Analyst", "location": {"name": "New York"},
        "absolute_url": "https://job-boards.greenhouse.io/x/jobs/1", "first_published": "2026-11-20T00:00:00Z",
        "content": "&lt;p&gt;Desk role&lt;/p&gt;"}]})
    j = ats.greenhouse({"name": "X", "token": "x"})[0]
    assert j["title"] == "Trading Analyst" and j["date_posted"] == "2026-11-20" and j["description"] == "Desk role"


def test_workday_paging_and_detail(monkeypatch):
    calls = []

    def fake_post(url, payload, **k):
        calls.append(payload)
        if payload["searchText"] == "analyst" and payload["offset"] == 0:
            return {"jobPostings": [{"title": "Markets Analyst", "externalPath": "/job/New-York/Markets-Analyst_R1",
                                     "locationsText": "New York, NY", "postedOn": "Posted Yesterday",
                                     "bulletFields": ["R1"]}]}
        return {"jobPostings": []}
    monkeypatch.setattr(ats, "post_json", fake_post)
    jobs = ats.workday({"name": "Bank", "tenant": "bank", "dc": "wd1", "site": "Ext", "terms": ["analyst", "trading"]})
    assert len(jobs) == 1 and jobs[0]["req_id"] == "R1"
    assert jobs[0]["url"] == "https://bank.wd1.myworkdayjobs.com/en-US/Ext/job/New-York/Markets-Analyst_R1"
    monkeypatch.setattr(ats, "get_json", lambda url, **k: {"jobPostingInfo": {
        "jobDescription": "<p>Cash equities desk</p>", "location": "New York, NY", "timeType": "Full time"}})
    assert "Cash equities desk" in ats.workday_detail(jobs[0])


def test_lever(monkeypatch):
    monkeypatch.setattr(ats, "get_json", lambda url, **k: [{
        "id": "abc", "text": "Junior Trader", "categories": {"location": "Chicago", "commitment": "Full-time"},
        "hostedUrl": "https://jobs.lever.co/b/abc", "createdAt": 1763600000000, "descriptionPlain": "Options", "lists": []}])
    j = ats.lever({"name": "B", "token": "b"})[0]
    assert j["location"] == "Chicago" and j["commitment"] == "Full-time"


# ------------------------------------------------------- liveness / freshness
def _mk(source, company="Bank", title="Markets Analyst", loc="New York, NY", url=None):
    j = {"company": company, "title": title, "location": loc, "url": url or f"https://{source}/1",
         "source": source, "description": "", "date_posted": None}
    j.update({k: v for k, v in classify(j).items() if k not in ("keep", "reason")})
    return j


def test_merge_lifecycle():
    cidx = collect.company_index([{"name": "Bank", "aliases": ["Bank Corp"]}])
    cfg = {"board_stale_days": 7, "max_posting_age_days": 45}
    st = {}
    d0 = date(2026, 11, 1)
    # day 0: seen on Workday + LinkedIn -> one record, primary url = company site
    collect.merge(st, [_mk("workday", url="https://bank.wd1/x"), _mk("linkedin", company="Bank Corp")],
                  {"Bank": {"ok": True}}, cidx, cfg, d0)
    assert len(st["jobs"]) == 1
    rec = next(iter(st["jobs"].values()))
    assert rec["primary_url"] == "https://bank.wd1/x" and set(rec["sources"]) == {"workday", "linkedin"}
    # day 1: Workday feed FAILED -> must NOT close
    collect.merge(st, [], {"Bank": {"ok": False}}, cidx, cfg, d0 + timedelta(days=1))
    assert rec["status"] == "live"
    # day 2: feed OK and req missing -> closed
    collect.merge(st, [], {"Bank": {"ok": True}}, cidx, cfg, d0 + timedelta(days=2))
    assert rec["status"] == "closed"


def test_board_only_goes_stale_and_absent_flag():
    cidx = collect.company_index([{"name": "Bank"}])
    cfg = {"board_stale_days": 7, "max_posting_age_days": 45}
    st = {}
    d0 = date(2026, 11, 1)
    collect.merge(st, [_mk("indeed")], {"Bank": {"ok": True}}, cidx, cfg, d0)
    rec = next(iter(st["jobs"].values()))
    assert "absent-from-company-site" in rec["flags"]
    collect.merge(st, [], {}, cidx, cfg, d0 + timedelta(days=5))
    assert rec["status"] == "live"
    collect.merge(st, [], {}, cidx, cfg, d0 + timedelta(days=9))
    assert rec["status"] == "stale"


def test_end_to_end(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/companies.yaml").write_text(
        "- {name: Bank, tier: 1, ats: greenhouse, token: bank}\n- {name: StoneX, tier: 0, exclude: true, ats: unknown}\n")
    (tmp_path / "config/searches.yaml").write_text(
        "locations: []\nterms: []\nrunners: {cloud: {ats: true, sites: []}}\n")
    monkeypatch.setattr(collect, "ROOT", tmp_path)
    monkeypatch.setitem(ats.FETCHERS, "greenhouse", lambda c: [
        {"company": "Bank", "title": "Sales & Trading Analyst", "location": "New York, NY", "url": "https://b/1",
         "date_posted": "2026-11-22", "description": "Graduate role", "req_id": "1", "ats": "greenhouse"},
        {"company": "Bank", "title": "Senior Engineer", "location": "New York, NY", "url": "https://b/2",
         "date_posted": None, "description": "", "req_id": "2", "ats": "greenhouse"}])
    assert collect.main(["--runner", "cloud"]) == 0
    jobs = json.loads((tmp_path / "data/cloud/jobs.json").read_text())
    health = json.loads((tmp_path / "data/cloud/health.json").read_text())
    assert [j["title"] for j in jobs] == ["Sales & Trading Analyst"]
    assert health["ats_ok"] == 1 and health["new_today"] == 1


def test_boards_wrapper(monkeypatch):
    import pandas as pd
    import jobspy
    from collector import boards

    def fake(**kw):
        df = pd.DataFrame([{"site": kw["site_name"][0], "job_url": "https://www.linkedin.com/jobs/view/1",
                            "job_url_direct": None, "title": "Trading Analyst", "company": "Bank",
                            "location": {"city": "New York", "state": "NY", "country": None},
                            "date_posted": date(2026, 11, 22), "job_type": ["fulltime"], "description": "desk",
                            "min_amount": 100000.0, "max_amount": 120000.0, "interval": "yearly"}])
        df.attrs = {"errors": {}}
        return df
    monkeypatch.setattr(jobspy, "scrape_jobs", fake)
    cfg = {"locations": [{"name": "New York, NY"}], "terms": ["trading analyst"]}
    rows, health = boards.search_boards(cfg, {"sites": ["linkedin"], "sleep_between": 0}, print)
    assert rows[0]["location"] == "New York, NY" and rows[0]["date_posted"] == "2026-11-22"
    assert rows[0]["salary"].startswith("100,000-120,000") and health["linkedin"]["ok"] == 1
    assert classify(rows[0])["keep"]


@pytest.mark.parametrize("title,company,keep", [
    ("Sales Associate - Spirit", "Spirit Halloween", False),
    ("Client Sales Assistant - Wealth Management", "Fincadia", False),
    ("Electronic Trading Engineer", "Virtu Financial", False),
    ("Quantitative Researcher - Delta One", "DRW", False),
    ("PhD Graduate Quantitative Researcher", "Flow Traders", False),
    ("Investment Banking Associate - Tech & Services", "Baird", False),
    ("2027 Investment Banking Full-Time MBA Associate", "William Blair", False),
    ("Remote Financial Trading Specialist", "Turing", False),
    ("Field Execution Representative", "CELSIUS", False),
    ("Quantitative Trader - Entry Level 2027", "Belvedere Trading", True),
    ("Floor Trader- SOFR", "Akuna Capital", True),
    ("Repo Trading Analyst", "BBVA", True),
    ("Trading Assistant", "Robert Half", True),
])
def test_tightened_filter(title, company, keep):
    loc = "Chicago, IL" if company in ("Belvedere Trading", "Akuna Capital") else "New York, NY"
    c = classify({"title": title, "company": company, "location": loc, "description": ""})
    assert c["keep"] is keep, c
    if company == "Robert Half":
        assert "recruiter-or-gig-posting" in c["flags"]


def test_discover_lever_validation():
    from collector.discover import _looks_like
    assert _looks_like("Blue Owl Capital", "Blue Owl Capital is an asset management firm... trading, portfolio, markets")
    assert not _looks_like("Blue Owl Capital", "Blue is a design studio hiring designers")


def test_trading_associate_experience():
    keep = classify({"title": "Equity Trading Associate", "location": "New York, NY", "company": "x",
                     "description": "3+ years of relevant experience on a trading desk"})
    assert keep["keep"] and "asks-3yrs" in keep["flags"]
    drop = classify({"title": "Equity Research Associate", "location": "New York, NY", "company": "x",
                     "description": "3+ years of relevant experience"})
    assert not drop["keep"]
    ib = classify({"title": "Investment Banking Analyst, Capital Markets", "location": "New York, NY", "company": "x", "description": ""})
    assert ib["keep"]


def test_linkedin_empty_results_count_as_blocks(monkeypatch):
    import pandas as pd
    import jobspy
    from collector import boards
    calls = []

    def fake(**kw):
        calls.append(kw["search_term"])
        df = pd.DataFrame([])
        df.attrs = {"errors": {}}
        return df
    monkeypatch.setattr(jobspy, "scrape_jobs", fake)
    cfg = {"locations": [{"name": "New York, NY"}], "terms": [f"t{i}" for i in range(10)]}
    rows, health = boards.search_boards(cfg, {"sites": ["linkedin"], "sleep_between": 0, "sleep_after_error": 0}, print)
    assert len(calls) == 3 and health["linkedin"]["skipped"] == 7
