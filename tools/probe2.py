import json, re, time, requests
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
S = requests.Session(); S.headers["User-Agent"] = UA
out = {}
# Workday tenants whose guessed site name returned 422: find the real site by following the tenant root
for t, dc in [("bnymellon","wd5"),("smbcgroup","wd1"),("key","wd5"),("53","wd5"),("websteronline","wd5"),("valley","wd5"),
              ("pipersandler","wd1"),("bairdfinancial","wd1"),("oppenheimer","wd1"),("cantor","wd1"),("lazard","wd1"),
              ("nomura","wd3"),("tpicap","wd3"),("bgc","wd5"),("tradeweb","wd1"),("ice","wd1"),("alliancebernstein","wd1"),
              ("metlife","wd5"),("kkr","wd1"),("osv-cci","wd1"),("adm","wd5"),("pipersandler","wd501"),("ubs","wd3"),("hsbc","wd3"),("bnpparibas","wd3"),("natixis","wd3")]:
    time.sleep(2.5)
    try:
        r = S.get(f"https://{t}.{dc}.myworkdayjobs.com/", timeout=20, allow_redirects=True)
        sites = sorted(set(re.findall(rf"{re.escape(t)}\.{dc}\.myworkdayjobs\.com/(?:[a-z]{{2}}-[A-Z]{{2}}/)?([A-Za-z0-9_-]+)", r.text + " " + r.url)))
        out[f"{t}|{dc}"] = {"status": r.status_code, "final": r.url, "sites": sites[:8]}
    except Exception as e:
        out[f"{t}|{dc}"] = {"error": str(e)[:100]}
# Eightfold API checks
for host, dom in [("morganstanley.eightfold.ai","morganstanley.com"),("career.mlp.com","mlp.com")]:
    try:
        r = S.get(f"https://{host}/api/apply/v2/jobs", params={"domain": dom, "query": "analyst", "num": 5}, timeout=20)
        j = r.json() if r.status_code == 200 else {}
        out[host] = {"status": r.status_code, "count": j.get("count"), "sample": [p.get("name") for p in j.get("positions", [])[:3]]}
    except Exception as e:
        out[host] = {"error": str(e)[:100]}
# Goldman higher.gs.com: look for the API the page calls
try:
    r = S.get("https://higher.gs.com/results?LOCATION=New%20York", timeout=20)
    js = re.findall(r'src="([^"]+\.js)"', r.text)
    apis = set()
    for src in js[:8]:
        u = src if src.startswith("http") else "https://higher.gs.com" + src
        t = S.get(u, timeout=20).text
        apis |= set(re.findall(r'https://[a-z0-9.-]*gs\.com/[A-Za-z0-9/_.-]*(?:graphql|api)[A-Za-z0-9/_.-]*', t))
        apis |= set(re.findall(r'"(/[A-Za-z0-9/_.-]*graphql[A-Za-z0-9/_.-]*)"', t))
        ops = re.findall(r'(query\s+[A-Za-z]+\s*\([^)]{0,300}\))', t)
        if ops: out.setdefault("gs_ops", []).extend(ops[:5])
    out["gs_apis"] = sorted(apis)[:20]; out["gs_js"] = js[:8]
except Exception as e:
    out["gs"] = str(e)[:100]
# BofA / ING / SocGen / Optiver job page: does it carry schema.org JobPosting?
for name, sm, pat in [("bofa","https://careers.bankofamerica.com/sitemap.xml","job-detail"),("ing","https://careers.ing.com/en/sitemap.xml","/job/"),
                      ("socgen","https://careers.societegenerale.com/sitemap.xml","job"),("optiver","https://www.optiver.com/sitemap.xml","career-opportunities/"),
                      ("brevan","https://careers.brevanhoward.com/gb/en/sitemap.xml","job"),("baird","https://www.bairdcareers.com/sitemap.xml","job")]:
    try:
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", S.get(sm, timeout=20).text)
        u = next((l for l in locs if pat in l and "sitemap" not in l), None)
        h = S.get(u, timeout=20).text if u else ""
        out[name] = {"url": u, "jsonld": '"JobPosting"' in h, "len": len(h), "sub": [l for l in locs if "sitemap" in l][:3]}
    except Exception as e:
        out[name] = {"error": str(e)[:100]}
json.dump(out, open("data/probe2.json", "w"), indent=1)
