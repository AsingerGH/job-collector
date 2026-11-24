set -x
timeout 8m python -u -m collector.collect --runner cloud --skip-boards --only "Stifel" "Susquehanna (SIG)" "Intercontinental Exchange" "Optiver" > data/trial2.log 2>&1
python - <<'PY'
import json
j=json.load(open('data/cloud/jobs.json'))
keep=[{k:r.get(k) for k in ('company','title','location','sources','primary_url','date_posted','deadline')} for r in j if r['company'] in ("Stifel","Susquehanna (SIG)","Intercontinental Exchange","Optiver") and set(r['sources'])-{'indeed','linkedin'}]
json.dump(keep,open('data/trial2_jobs.json','w'),indent=1)
h=json.load(open('data/cloud/health.json')); json.dump({k:h.get(k) for k in ('ats_ok','ats_failed','minutes')},open('data/trial2_health.json','w'),indent=1)
import requests
for t in []:
    r=requests.get(f'https://boards-api.greenhouse.io/v1/boards/{t}/jobs'); print('GH',t,r.status_code, len(r.json().get('jobs',[])) if r.ok else '')
import re
x=""
for h in ['careers-sig.icims.com','sig.icims.com','careers-ice.icims.com','careers-stifel.icims.com']:
    try:
        r=requests.get(f'https://{h}/jobs/search?ss=1&in_iframe=1',headers={'User-Agent':'Mozilla/5.0'},timeout=20); print('ICIMS',h,r.status_code,len(r.text),re.findall(r'icims\.com/jobs/\d+/[a-z0-9-]+/job',r.text)[:3])
    except Exception as e: print('ICIMS',h,e)
print('OPT', re.findall(r'<loc>([^<]+)</loc>',x)[:5], [l for l in re.findall(r'<loc>([^<]+)</loc>',x) if 'job' in l][:5])
PY
