"""Main entry point.

  python -m collector.collect --runner cloud      # GitHub Actions
  python -m collector.collect --runner laptop     # Andrew's Windows laptop (LinkedIn-heavy)
  python -m collector.collect --runner cloud --skip-boards --only "Point72"

Writes to data/<runner>/:
  jobs.json      live, prefiltered roles (what the Claude task reads)
  closed.json    roles that disappeared in the last 21 days (so the tracker can expire them)
  health.json    which sources worked this run
  state.json     full history (first/last seen), used for freshness + liveness
  unmatched_companies.json  firms with relevant board postings that aren't on the watchlist
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import ats
from .classify import classify
from .util import canon_url, norm_company, norm_title, sha, today

ROOT = Path(__file__).resolve().parent.parent


def log(msg: str) -> None:
    print(msg, flush=True)


def load_yaml(p: Path):
    return yaml.safe_load(p.read_text()) if p.exists() else None


def load_companies() -> list[dict]:
    base = load_yaml(ROOT / "config/companies.yaml") or []
    disc = {d["name"]: d for d in (load_yaml(ROOT / "config/discovered.yaml") or [])}
    # hand-verified readers (config/readers.yaml) win over auto-discovery
    readers = {d["name"]: d for d in (load_yaml(ROOT / "config/readers.yaml") or [])}
    out = []
    for c in base:
        if c["name"] in readers:
            c = {**c, **{k: v for k, v in readers[c["name"]].items() if k != "name"}}
        elif c.get("ats") in (None, "", "unknown") and c["name"] in disc:
            c = {**c, **{k: v for k, v in disc[c["name"]].items() if k != "name"}}
        out.append(c)
    names = {c["name"] for c in base}
    out += [{"tier": 2, "segment": "auto-discovered", **d} for n, d in disc.items() if n not in names]
    return out


def company_index(companies: list[dict]) -> dict[str, dict]:
    idx = {}
    for c in companies:
        for n in [c["name"], *(c.get("aliases") or [])]:
            idx[norm_company(n)] = c
    return idx


def job_key(company: str, title: str, bucket: str | None, cidx: dict) -> str:
    c = cidx.get(norm_company(company))
    cname = norm_company(c["name"]) if c else norm_company(company)
    return sha(f"{cname}|{norm_title(title)}|{bucket}")


# ------------------------------------------------------------------ ATS pass
def run_ats(companies, only, log, types=None, skip=()) -> tuple[list[dict], dict]:
    targets = [c for c in companies if c.get("ats") in ats.FETCHERS and (not only or c["name"] in only)
               and (not types or c.get("ats") in types) and c["name"] not in skip]
    health = {}
    rows: list[dict] = []
    log(f"ATS: fetching {len(targets)} company boards")

    def work(c):
        t0 = time.time()
        jobs = ats.FETCHERS[c["ats"]](c)
        return c, jobs, time.time() - t0

    # Workday calls are paced through one lock, so give them their own small pool and let
    # every other job system run in parallel alongside.
    wd = sorted((c for c in targets if c.get("ats") == "workday"), key=lambda c: c.get("tier", 2))
    other = [c for c in targets if c.get("ats") != "workday"]
    with ThreadPoolExecutor(max_workers=6) as ex, ThreadPoolExecutor(max_workers=2) as wx:
        futs = {ex.submit(work, c): c for c in other}
        futs.update({wx.submit(work, c): c for c in wd})
        for f in as_completed(futs):
            c = futs[f]
            try:
                c, jobs, dt = f.result()
            except Exception as e:
                health[c["name"]] = {"ok": False, "ats": c["ats"], "error": str(e)[:300]}
                log(f"  ! {c['name']} ({c['ats']}): {e}")
                continue
            health[c["name"]] = {"ok": True, "ats": c["ats"], "total": len(jobs), "secs": round(dt, 1)}
            if c["ats"] in ("sitemap", "icims"):
                health[c["name"]]["live_urls"] = getattr(jobs, "live_urls", [])
                health[c["name"]]["total"] = len(getattr(jobs, "live_urls", []))
            for j in jobs:
                j["source"] = c["ats"]
                j["tier"] = c.get("tier", 2)
            rows.extend(jobs)
            log(f"  {c['name']}: {len(jobs)} open roles")
    return rows, health


def fetch_details(jobs: list[dict]) -> None:
    need = [j for j in jobs if j.get("_detail") and not j.get("description") and j["ats"] in ats.DETAIL]
    log(f"Fetching full descriptions for {len(need)} prefiltered roles")

    def work(j):
        try:
            j["description"] = ats.DETAIL[j["ats"]](j)
        except Exception as e:
            j["description"] = ""
            j.setdefault("flags", []).append(f"detail-failed: {str(e)[:80]}")

    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(work, need))


# -------------------------------------------------------------------- state
def merge(state: dict, kept: list[dict], ats_health: dict, cidx: dict, cfg: dict, run_day: date) -> None:
    jobs = state.setdefault("jobs", {})
    t = run_day.isoformat()
    seen_today = set()

    for j in kept:
        k = job_key(j["company"], j["title"], j["loc_bucket"], cidx)
        seen_today.add(k)
        rec = jobs.get(k)
        cfgc = cidx.get(norm_company(j["company"]))
        if rec is None or rec.get("status") in ("closed", "stale"):
            reopened = rec is not None
            rec = {
                "id": k,
                "company": cfgc["name"] if cfgc else j["company"],
                "title": j["title"],
                "first_seen": t if not reopened else rec["first_seen"],
                "urls": {}, "sources": [], "flags": [],
            }
            if reopened:
                rec["flags"].append(f"reappeared {t}")
            jobs[k] = rec
        rec.update({
            "title": j["title"] if j["source"] in ats.FETCHERS else rec.get("title", j["title"]),
            "location": j.get("location", ""),
            "loc_bucket": j["loc_bucket"],
            "track": j["track"],
            "last_seen": t,
            "status": "live",
            "tier": (cfgc or {}).get("tier"),
            "on_watchlist": bool(cfgc),
        })
        # prefer company-owned URL as the primary link
        rec["urls"][j["source"]] = j.get("url_direct") or j["url"]
        if j["source"] in ats.FETCHERS:
            rec["primary_url"] = j["url"]
            rec["ats_req_id"] = j.get("req_id")
            rec.setdefault("ats_first_seen", t)
        elif not rec.get("primary_url"):
            rec["primary_url"] = j.get("url_direct") or j["url"]
        if j["source"] not in rec["sources"]:
            rec["sources"].append(j["source"])
        dp = j.get("date_posted")
        if dp and (not rec.get("date_posted") or j["source"] in ats.FETCHERS):
            rec["date_posted"] = dp
        if j.get("salary"):
            rec["salary"] = j["salary"]
        if j.get("deadline"):
            rec["deadline"] = j["deadline"]
        if len(j.get("description") or "") > len(rec.get("description") or ""):
            rec["description"] = (j.get("description") or "")[:6000]
        rec["flags"] = sorted(set(rec["flags"]) | set(j.get("flags", [])))
        if "min_years" in j:
            rec["min_years"] = j["min_years"]

    ok_companies = {norm_company(n) for n, h in ats_health.items() if h.get("ok")}
    # Only these readers return a firm's COMPLETE list of open jobs; a job missing from them
    # really closed. Search-based readers (Workday/Eightfold/Oracle keyword searches) and
    # capped sitemap reads can miss a live job, so for those we check the sitemap's full URL
    # list when we have it, and otherwise wait 7 days unseen before calling a job stale.
    complete = {norm_company(n) for n, h in ats_health.items()
                if h.get("ok") and h.get("ats") in ("greenhouse", "lever", "ashby", "smartrecruiters")}
    sitemap_live = {norm_company(n): set(h.get("live_urls") or []) for n, h in ats_health.items()
                    if h.get("ok") and h.get("ats") in ("sitemap", "icims")}
    stale_days = int(cfg.get("board_stale_days", 7))
    max_age = int(cfg.get("max_posting_age_days", 45))
    for k, rec in jobs.items():
        if rec.get("status") != "live" or k in seen_today:
            if k in seen_today:
                _age_flags(rec, run_day, max_age, ok_companies, cidx)
            continue
        on_ats = any(s in ats.FETCHERS for s in rec["sources"])
        cn = norm_company(rec["company"])
        if on_ats and cn in complete:
            # company feed loaded fine and the req is gone -> it closed
            rec["status"], rec["closed_on"], rec["closed_why"] = "closed", t, "removed from company job system"
        elif on_ats and cn in sitemap_live and sitemap_live[cn] and any(
                u and u not in sitemap_live[cn] for src, u in (rec.get("urls") or {}).items() if src in ("sitemap", "icims")):
            rec["status"], rec["closed_on"], rec["closed_why"] = "closed", t, "removed from company careers site"
        elif rec.get("last_seen", t) < (run_day - timedelta(days=stale_days)).isoformat():
            rec["status"], rec["closed_on"], rec["closed_why"] = "stale", t, f"not seen on any board for {stale_days}+ days"

    # prune
    cutoff = (run_day - timedelta(days=60)).isoformat()
    for k in [k for k, r in jobs.items() if r.get("status") != "live" and r.get("closed_on", t) < cutoff]:
        del jobs[k]


def _age_flags(rec, run_day, max_age, ok_companies, cidx):
    flags = set(f for f in rec.get("flags", []) if not f.startswith(("old-posting", "absent-from-company-site")))
    dp = rec.get("date_posted")
    if dp:
        age = (run_day - date.fromisoformat(dp)).days
        rec["age_days"] = age
        if age > max_age:
            flags.add(f"old-posting ({age}d)")
    on_ats = any(s in ats.FETCHERS for s in rec["sources"])
    if not on_ats and norm_company(rec["company"]) in ok_companies:
        # firm's own job system loaded fine but this board posting isn't on it -> likely a stale mirror
        flags.add("absent-from-company-site")
    rec["flags"] = sorted(flags)


def coverage(companies, ats_health, live, cidx) -> dict:
    """Per watchlist firm: how we read it, whether that worked this run, and live roles in the pool."""
    live_by = {}
    for r in live:
        c = cidx.get(norm_company(r.get("company", "")))
        if c:
            live_by[c["name"]] = live_by.get(c["name"], 0) + 1
    out = {}
    for c in companies:
        if c.get("exclude"):
            continue
        h = ats_health.get(c["name"])
        method = c.get("ats") if c.get("ats") in ats.FETCHERS else "boards-only"
        out[c["name"]] = {"tier": c.get("tier", 2), "method": method,
                          "ok": (h or {}).get("ok") if h else None,
                          "open_roles_read": (h or {}).get("total"),
                          "error": ((h or {}).get("error") or "")[:120],
                          "live_in_pool": live_by.get(c["name"], 0)}
    return out


# --------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runner", default="cloud")
    ap.add_argument("--skip-boards", action="store_true")
    ap.add_argument("--skip-ats", action="store_true")
    ap.add_argument("--only", nargs="*", help="limit ATS pass to these company names")
    ap.add_argument("--hours-old", type=int, default=0, help="one-off override of the job-board look-back window (e.g. 720 = 30 days)")
    ap.add_argument("--results", type=int, default=0, help="one-off override of results per board search")
    args = ap.parse_args(argv)

    cfg = load_yaml(ROOT / "config/searches.yaml")
    runner = dict(cfg["runners"][args.runner])
    if args.hours_old:
        runner["hours_old"] = args.hours_old
    if args.results:
        runner["results_per_search"] = args.results
    # Self-reverting deep look-back: while today <= backfill.until, scheduled runs search
    # the boards back `backfill.hours_old` hours (e.g. 30 days) instead of the usual window.
    bf = cfg.get("backfill") or {}
    if not args.hours_old and bf.get("until") and today().isoformat() <= str(bf["until"]):
        runner["hours_old"] = int(bf.get("hours_old", 720))
        if bf.get("results_per_search"):
            runner["results_per_search"] = max(int(runner.get("results_per_search", 40)), int(bf["results_per_search"]))
    companies = load_companies()
    cidx = company_index(companies)
    out_dir = ROOT / "data" / args.runner
    out_dir.mkdir(parents=True, exist_ok=True)
    state_p = out_dir / "state.json"
    state = json.loads(state_p.read_text()) if state_p.exists() else {}
    run_day = today()
    started = datetime.now(timezone.utc)
    # re-screen what's already stored, so filter improvements also clean up earlier runs
    for k in [k for k, r in state.get("jobs", {}).items() if r.get("status") == "live"
              and not classify({"title": r["title"], "location": r.get("location", ""),
                                "description": r.get("description", ""), "company": r["company"],
                                "job_type": "internship" if r.get("track") == "internship" else ""})["keep"]]:
        del state["jobs"][k]

    raw: list[dict] = []
    ats_health, board_health = {}, {}
    ats.WD_SPACING = float(runner.get("workday_spacing", ats.WD_SPACING))
    if runner.get("workday_budget_min"):
        ats.WD_DEADLINE[0] = time.time() + 60 * float(runner["workday_budget_min"])
    if not args.skip_ats and runner.get("ats", True):
        rows, ats_health = run_ats(companies, args.only, log, runner.get("ats_types"), runner.get("ats_skip") or ())
        raw += rows
    if not args.skip_boards and runner.get("sites"):
        from .boards import search_boards
        if runner.get("company_searches"):
            # firms we still can't read directly get searched on the boards by name
            runner["company_list"] = [(c["name"], c.get("aliases") or []) for c in companies
                                      if c.get("tier", 2) <= int(runner.get("company_search_max_tier", 2))
                                      and c.get("ats") not in ats.FETCHERS and not c.get("exclude")]
            log(f"Company-targeted board searches for {len(runner['company_list'])} firms with no readable job system")
        rows, board_health = search_boards(cfg, runner, log)
        raw += rows

    programs = {}
    pp = load_yaml(ROOT / "config/program_pages.yaml") or []
    if pp and runner.get("program_pages", True):
        from .programs import check as check_programs
        programs = check_programs(pp, state.get("programs", {}))
        state["programs"] = programs
        log(f"Program pages: {sum(1 for p in programs.values() if p.get('ok'))}/{len(pp)} read, "
            f"{sum(1 for p in programs.values() if p.get('status') == 'open')} look open")

    kept, reasons = [], {}
    excluded = {norm_company(n) for c in companies if c.get("exclude")
                for n in [c["name"], *(c.get("aliases") or [])]}
    raw = [j for j in raw if norm_company(j.get("company", "")) not in excluded]
    for j in raw:
        c = classify(j)
        reasons[c["reason"]] = reasons.get(c["reason"], 0) + 1
        if c["keep"]:
            j.update({k: v for k, v in c.items() if k not in ("keep", "reason")})
            kept.append(j)
    log(f"Prefilter: {len(raw)} raw -> {len(kept)} kept  {reasons}")

    fetch_details(kept)
    # re-run classification now that descriptions are present (experience/class-year checks)
    final = []
    for j in kept:
        c = classify(j)
        if c["keep"]:
            j.update({k: v for k, v in c.items() if k not in ("keep", "reason")})
            final.append(j)
    log(f"After full descriptions: {len(final)} kept")

    merge(state, final, ats_health, cidx, cfg, run_day)

    # unmatched companies (discovery queue)
    unmatched: dict[str, int] = {}
    for j in final:
        if j["source"] not in ats.FETCHERS and norm_company(j["company"]) not in cidx and j["company"]:
            unmatched[j["company"]] = unmatched.get(j["company"], 0) + 1

    live = sorted((r for r in state["jobs"].values() if r["status"] == "live"),
                  key=lambda r: (r["first_seen"], r.get("date_posted") or ""), reverse=True)
    recent_closed = [r for r in state["jobs"].values() if r["status"] != "live"
                     and r.get("closed_on", "") >= (run_day - timedelta(days=21)).isoformat()]
    state["last_run"] = started.isoformat()

    def dump(name, obj):
        (out_dir / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str))

    dump("state.json", state)
    dump("jobs.json", [{**r, "description": (r.get("description") or "")[:4000]} for r in live])
    dump("closed.json", recent_closed)
    dump("unmatched_companies.json", dict(sorted(unmatched.items(), key=lambda x: -x[1])))
    dump("health.json", {
        "runner": args.runner, "run_at": started.isoformat(),
        "minutes": round((datetime.now(timezone.utc) - started).total_seconds() / 60, 1),
        "raw": len(raw), "kept": len(final), "live": len(live),
        "new_today": sum(1 for r in live if r["first_seen"] == run_day.isoformat()),
        "filter_reasons": reasons, "boards": board_health,
        "ats_ok": sum(1 for h in ats_health.values() if h["ok"]),
        "ats_failed": {n: h["error"] for n, h in ats_health.items() if not h["ok"]},
        "coverage": coverage(companies, ats_health, live, cidx),
        "program_pages": programs,
    })
    log(f"Done: {len(live)} live, {sum(1 for r in live if r['first_seen']==run_day.isoformat())} new today")
    return 0


if __name__ == "__main__":
    sys.exit(main())
