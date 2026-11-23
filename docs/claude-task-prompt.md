# Daily Claude task — version 2 (switch to this once the collector repo + Gmail are live)

Changes from the current web-sweep task: the task stops doing the scraping and reads the collector's output (company job feeds + JobSpy) and the alert emails. Web search is used only to verify leads and fill gaps.

---

You are running Andrew Singer's DAILY JOB REVIEW. This is an unattended scheduled run: make reasonable calls and proceed. Never apply to jobs, never contact anyone, never send email. The Gmail connector is READ-ONLY for you: search and read only messages labelled `job-alerts`.

STATE: tracker https://claude.ai/artifact/MC378gukrN8XCMm6WMPU9m and its database (load ArtifactData via ToolSearch "select:ArtifactData"). Read meta/profile (source of truth for scope, locations, the full-time and Summer 2027 internship tracks, and scoring) and meta/feedback before anything else. Today's date: `TZ=America/Chicago date +%F`.

STEP 1 — Pull collector output
- `git clone --depth 1 https://github.com/<OWNER>/job-collector.git /tmp/jc`
- Read /tmp/jc/data/cloud/health.json and /tmp/jc/data/mac/health.json. If cloud run_at is more than 30 hours old, or ats_ok fell by more than a third against the companies with a known feed, add one warning line to the final message ("Collector issue: …").
- Load data/cloud/jobs.json + data/mac/jobs.json (merge on `id`) and data/*/closed.json.

STEP 2 — Pull email alerts
- Gmail search `label:job-alerts newer_than:2d`. Extract each posting (company, title, location, link) from Handshake, LinkedIn, eFinancialCareers and Indeed alert emails. Drop anything already in the collector output (same company + similar title) or already in the tracker.
- Handshake links need a login: treat them as leads. Look for the same role on the company's own site or a public board with WebSearch/WebFetch; if found, use that URL. If not found, add it only if the alert email itself shows the full details, set source="handshake", onCompanySite=false, and say in fitNote "Handshake-only, verify before applying".

STEP 3 — Judge
- Read every candidate's description and judge it against the profile exactly as the profile says (function, class year, 0–2 yrs, heavy-quant exclusion, Priority 3 bar). The collector's prefilter is deliberately loose.
- Liveness gate: a role whose `sources` include a company job system (greenhouse/lever/ashby/workday/eightfold/oracle/smartrecruiters) was seen live in that firm's own feed today: onCompanySite=true, no further check needed. Board-only roles flagged `absent-from-company-site` or `old-posting`: WebFetch the posting. Keep only if positively live, else skip. Other board-only roles: keep, but WebFetch to confirm when composite ≥ 3.8.
- `track` comes from the collector ("fulltime"/"internship"); correct it if the description says otherwise.

STEP 4 — Write to the tracker (same doc rules as before)
- New: set jobs/<collector id> with title, company, category, track, location, url (= primary_url), source, sources, postedDate, deadline, firstSeen, lastSeen, status "new", onCompanySite, scores, composite, fitNote, jdSummary, requiresHeavyCoding, myStatus "", myNote "".
- Existing + still live: update lastSeen, new→tracked, refresh scores.
- In collector closed.json, or not seen anywhere for 7+ days: status "expired". Never touch myStatus/myNote. Never delete a doc with a myStatus.
- set runs/<today>-review and update meta/state (lastCloudRun, lastCollectorRun = health run_at, lastSummary).

STEP 5 — Fill coverage gaps (≤ 15 searches)
- For up to 5 tier-1 companies whose feed is unknown (see /tmp/jc/data/discovery_misses.json), WebSearch `site:myworkdayjobs.com <company>`, `<company> greenhouse jobs`, etc. If you find a feed URL, record it on that company's tracker doc (careersUrl, ats) and list it in the final message under "Feeds found" so Andrew can add it.

STEP 6 — Final message (becomes Andrew's email + phone notification)
- Deadlines within 7 days first, then the best new full-time roles as "Company — Title (Location) · score · why", then "Internship:" lines, then any collector warning. Up to 10 lines. End with the tracker URL.
- Nothing new, nothing urgent, no warnings → exactly "No new matches today."
