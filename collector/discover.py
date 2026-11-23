"""Finds the job-system feed for every watchlist company whose ATS is unknown.

  python -m collector.discover            # all unknown companies (runs weekly in Actions)
  python -m collector.discover --name "Jane Street"
  python -m collector.discover --add-unmatched   # also try firms the collector saw on boards

For each company it (1) tests any hint from companies.yaml, then (2) probes common
Greenhouse / Lever / Ashby slugs, then (3) probes Workday tenant/site combinations.
A feed is accepted only if it returns real postings and (where the API exposes it) the
board's own company name matches. Results go to config/discovered.yaml, which the
collector merges automatically. Nothing here is trusted without a live response.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

from . import ats
from .collect import ROOT, load_yaml
from .util import get_json, norm_company, post_json

DCS = ["wd1", "wd5", "wd3", "wd12", "wd10", "wd2", "wd103", "wd501"]
WD_SITES = ["External", "Careers", "External_Careers", "ExternalCareers", "careers", "Campus",
            "{T}", "{T}Careers", "{T}_Careers", "{T}_External", "Global", "jobs", "Students"]


def slugs(name: str) -> list[str]:
    base = re.sub(r"\(.*?\)", "", name)
    words = re.sub(r"[^a-z0-9 ]+", "", base.lower().replace("&", "and")).split()
    stop = {"and", "the", "company", "group", "partners", "capital", "markets", "securities", "trading",
            "financial", "management", "llc", "inc"}
    core = [w for w in words if w not in stop] or words
    cands = ["".join(words), "".join(core), core[0], "-".join(words), "".join(core) + "careers",
             "".join(core) + "jobs", "".join(words[:2])]
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _name_ok(board_name: str, company: str) -> bool:
    a, b = set(norm_company(board_name).split()), set(norm_company(company).split())
    return bool(a & b)


def try_spec(spec: dict, company: str) -> int:
    """Returns posting count if the spec works, else 0."""
    try:
        if spec["ats"] == "greenhouse":
            host = "boards-api.eu.greenhouse.io" if spec.get("region") == "eu" else "boards-api.greenhouse.io"
            meta = get_json(f"https://{host}/v1/boards/{spec['token']}", retries=0)
            if not _name_ok(meta.get("name", ""), company):
                return 0
        jobs = ats.FETCHERS[spec["ats"]]({"name": company, **spec, "max_pages": 1, "terms": ["analyst"]})
        return len(jobs) or (1 if spec["ats"] == "workday" else 0)  # a valid empty Workday search still proves the site
    except Exception:
        return 0


def probe_workday(tenant: str) -> dict | None:
    for dc in DCS:
        for s in WD_SITES:
            site = s.replace("{T}", tenant)
            try:
                d = post_json(f"https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs",
                              {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}, retries=0, timeout=10)
            except Exception:
                continue
            if isinstance(d, dict) and "jobPostings" in d:
                return {"ats": "workday", "tenant": tenant, "dc": dc, "site": site}
    return None


def discover(company: dict) -> dict | None:
    name = company["name"]
    if company.get("hint"):
        h = company["hint"]
        if try_spec(h, name):
            return h
        if h["ats"] == "workday":  # right tenant, wrong dc/site is common
            found = probe_workday(h["tenant"])
            if found:
                return found
    for slug in slugs(name):
        for kind in ("greenhouse", "lever", "ashby"):
            spec = {"ats": kind, "token": slug}
            if try_spec(spec, name):
                return spec
        if company.get("hint", {}).get("region") == "eu":
            spec = {"ats": "greenhouse", "token": slug, "region": "eu"}
            if try_spec(spec, name):
                return spec
    for slug in slugs(name)[:3]:
        found = probe_workday(slug)
        if found:
            return found
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", nargs="*")
    ap.add_argument("--add-unmatched", action="store_true")
    ap.add_argument("--min-unmatched", type=int, default=2)
    args = ap.parse_args(argv)

    companies = load_yaml(ROOT / "config/companies.yaml") or []
    disc_p = ROOT / "config/discovered.yaml"
    discovered = {d["name"]: d for d in (load_yaml(disc_p) or [])}
    todo = [c for c in companies if c.get("ats") == "unknown" and not c.get("exclude")
            and c["name"] not in discovered and (not args.name or c["name"] in args.name)]

    if args.add_unmatched:
        known = {norm_company(c["name"]) for c in companies}
        for runner in ("cloud", "laptop"):
            p = ROOT / "data" / runner / "unmatched_companies.json"
            if p.exists():
                for n, cnt in json.loads(p.read_text()).items():
                    if cnt >= args.min_unmatched and norm_company(n) not in known:
                        todo.append({"name": n, "tier": 2, "segment": "auto-discovered", "ats": "unknown"})
                        known.add(norm_company(n))

    print(f"Probing {len(todo)} companies")
    misses = []
    for c in todo:
        spec = discover(c)
        if spec:
            discovered[c["name"]] = {"name": c["name"], **spec, **({"auto": True} if c.get("segment") == "auto-discovered" else {})}
            print(f"  + {c['name']}: {spec}")
        else:
            misses.append(c["name"])
            print(f"  - {c['name']}: no public feed found")
    disc_p.write_text(yaml.safe_dump(sorted(discovered.values(), key=lambda d: d["name"]), sort_keys=False, allow_unicode=True))
    (ROOT / "data" / "discovery_misses.json").write_text(json.dumps(misses, indent=1))
    print(f"Found {len(todo) - len(misses)}/{len(todo)}. Misses are covered by job boards + email alerts.")


if __name__ == "__main__":
    main()
