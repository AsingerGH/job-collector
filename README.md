# Job collector

Code does the scraping and Claude does the judging. This repo gathers postings every day without a browser or login:

| Source | How | Freshness / liveness |
|---|---|---|
| Company job systems (Workday, Greenhouse, Lever, Ashby, SmartRecruiters, Eightfold, Oracle) | each system's public JSON feed: the full list of open roles | real posted date; when a req drops out of the feed, it's marked **closed** |
| LinkedIn, Indeed, Glassdoor, ZipRecruiter, Google Jobs | [JobSpy](https://github.com/speedyapply/JobSpy), last 72 hours only | stale after 7 days unseen; flagged if the firm's own site doesn't list it |
| Handshake, LinkedIn alerts, eFinancialCareers | saved-search alert emails, read by the Claude task via Gmail | the Claude task checks each one |

The daily Claude task reads `data/*/jobs.json`, scores roles against the profile in the tracker, and updates the board.

---

## One-time setup (~30 min)

### 1. GitHub (10 min)
1. Create a free account at github.com.
2. In **claude.ai → Settings → Connectors**, connect **GitHub**. Then tell Claude "push the job collector" and it creates a private repo named `job-collector` with this code.
   *(Manual alternative: create an empty private repo named `job-collector` and upload this folder's contents.)*
3. In the repo: **Settings → Actions → General → Workflow permissions → "Read and write permissions"**, then Save.
4. **Actions tab → collect-jobs → Run workflow**, and tick "Run feed discovery too" for the first run. It takes about 30–60 min. Then open `data/cloud/health.json` to see which sources worked.

### 2. Mac (5 min), for LinkedIn from your home internet
```bash
cd ~ && git clone https://github.com/<you>/job-collector.git && cd job-collector
bash mac/install.sh          # creates a Python env + a launchd job (7:05 AM / 7:05 PM)
./mac/run.sh && tail -30 ~/Library/Logs/job-collector.log   # test run
```
`git push` must work from the Mac. The easiest way is to install GitHub Desktop once and sign in, or run `gh auth login`.

### 3. Job-alerts Gmail (15 min)
1. Create a new Gmail address (e.g. `andrew.jobalerts@gmail.com`).
2. In **claude.ai → Settings → Connectors**, connect **Gmail** using *that* account.
3. Create saved searches with **daily email** alerts:
   - **Handshake** (UT Austin): open Jobs, apply the filters, then turn on the "Notify me about new jobs like this" toggle. Do one search per line below:
     - Job type Full-time · Industry Investment Banking/Financial Services · keywords `trading OR "sales and trading" OR markets` · locations New York, Jersey City, Chicago
     - Job type Internship · same industry · keywords `summer 2027 sales trading markets`
     - Also **follow** your target employers. Handshake emails you when they post.
   - **LinkedIn Jobs**: search, then "Set alert" → Daily. Searches: `trading analyst` (New York), `"sales and trading" analyst` (New York), `trading assistant` (New York), `junior trader` (Chicago), `"2027" analyst markets`. Set Experience level to Entry level and Internship.
   - **eFinancialCareers**: create an account with the new Gmail, then set alerts for `trading analyst` / `graduate trading` in New York and Chicago.
   - **Indeed**: alerts for the same terms, sent to the new Gmail.
4. Handshake and LinkedIn email the address on your account, so forward those alerts to the new Gmail:
   - In your **personal Gmail**: Settings → Forwarding → add the new address. Then create a filter with `from:(handshake OR linkedin.com OR jobalerts-noreply@linkedin.com OR efinancialcareers)` → *Forward to* the new address.
   - **UT email (Outlook)**: create a rule that forwards Handshake mail. If UT blocks forwarding outside UT, change Handshake's notification email in Handshake Settings, or forward those alerts by hand once a week.
5. In the **new Gmail**: create a filter for the same senders → *Apply label* `job-alerts`. The agent reads only that label.

---

## Day-to-day
- **Add a company**: add a line in `config/build_companies.py`, then run `python config/build_companies.py`. Discovery finds its job feed on Sunday, or run the workflow with discovery ticked.
- **Change searches**: edit `config/searches.yaml`.
- **Check the plumbing**: `data/cloud/health.json` and `data/mac/health.json` list every source that failed, with the error.
- `data/discovery_misses.json` lists firms with no public feed. They're covered by the job boards and email alerts instead.
- Tests: `python -m pytest -q`.

## Known limits
- LinkedIn throttles scraping and sometimes blocks cloud servers. That's why LinkedIn runs mainly from the Mac, with email alerts as backup.
- Goldman (higher.gs.com), Jefferies (tal.net), and iCIMS sites have no public feed. They're caught through LinkedIn/Indeed listings and email alerts.
- Some feed addresses in `companies.yaml` are marked `hint`. Those are unconfirmed guesses, and discovery tests each one before it's used.
