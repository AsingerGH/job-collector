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
    out = []
    for c in base:
        if c.get("ats") in (None, "", "unknown") and c["name"] in disc:
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
def run_ats(companies, only, log) -> tuple[list[dict], dict]:
    targets = [c for c in companies if c.get("ats") in ats.FETCHERS and (not only or c["name"] in only)]
    health = {}
    rows: list[dict] = []
    log(f"ATS: fetching {len(targets)} company boards")

    def work(c):
        t0 = time.time()
        jobs = ats.FETCHERS[c["ats"]](c)
        return c, jobs, time.time() - t0

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(work, c): c for c in targets}
        for f in as_completed(futs):
            c = futs[f]
            try:
                c, jobs, dt = f.result()
            except Exception as e:
                health[c["name"]] = {"ok": False, "ats": c["ats"], "error": str(e)[:300]}
                log(f"  ! {c['name']} ({c['ats']}): {e}")
                continue
            health[c["name"]] = {"ok": True, "ats": c["ats"], "total": len(jobs), "secs": round(dt, 1)}
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
        if len(j.get("description") or "") > len(rec.get("description") or ""):
            rec["description"] = (j.get("description") or "")[:6000]
        rec["flags"] = sorted(set(rec["flags"]) | set(j.get("flags", [])))
        if "min_years" in j:
            rec["min_years"] = j["min_years"]

    ok_companies = {norm_company(n) for n, h in ats_health.items() if h.get("ok")}
    stale_days = int(cfg.get("board_stale_days", 7))
    max_age = int(cfg.get("max_posting_age_days", 45))
    for k, rec in jobs.items():
        if rec.get("status") != "live" or k in seen_today:
            if k in seen_today:
                _age_flags(rec, run_day, max_age, ok_companies, cidx)
            continue
        on_ats = any(s in ats.FETCHERS for s in rec["sources"])
        cn = norm_company(rec["company"])
        if on_ats and cn in ok_companies:
            # company feed loaded fine and the req is gone -> it closed
            rec["status"], rec["closed_on"], rec["closed_why"] = "closed", t, "removed from company job system"
        elif not on_ats and rec.get("last_seen", t) < (run_day - timedelta(days=stale_days)).isoformat():
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


# --------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runner", default="cloud")
    ap.add_argument("--skip-boards", action="store_true")
    ap.add_argument("--skip-ats", action="store_true")
    ap.add_argument("--only", nargs="*", help="limit ATS pass to these company names")
    args = ap.parse_args(argv)

    cfg = load_yaml(ROOT / "config/searches.yaml")
    runner = cfg["runners"][args.runner]
    companies = load_companies()
    cidx = company_index(companies)
    out_dir = ROOT / "data" / args.runner
    out_dir.mkdir(parents=True, exist_ok=True)
    state_p = out_dir / "state.json"
    state = json.loads(state_p.read_text()) if state_p.exists() else {}
    run_day = today()
    started = datetime.now(timezone.utc)

    raw: list[dict] = []
    ats_health, board_health = {}, {}
    if not args.skip_ats and runner.get("ats", True):
        rows, ats_health = run_ats(companies, args.only, log)
        raw += rows
    if not args.skip_boards and runner.get("sites"):
        from .boards import search_boards
        rows, board_health = search_boards(cfg, runner, log)
        raw += rows

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
    })
    log(f"Done: {len(live)} live, {sum(1 for r in live if r['first_seen']==run_day.isoformat())} new today")
    return 0


if __name__ == "__main__":
    sys.exit(main())
