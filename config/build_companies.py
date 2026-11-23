"""Generates companies.yaml. Edit the table, then: python config/build_companies.py

Columns: name | tier | segment | ats spec | aliases
ats spec:
  "gh:<token>" / "gh-eu:<token>" Greenhouse     "lever:<token>"   "ashby:<token>"
  "sr:<id>" SmartRecruiters                     "wd:<tenant>/<dc>/<site>" Workday (confirmed)
  "hint-wd:<tenant>/<dc>/<site>"  unconfirmed Workday guess -> discover.py tests it
  "hint-eightfold:<host>/<domain>"  "hint-oracle:<host>/<site>"   unconfirmed guesses
  "" unknown -> discover.py probes common Greenhouse/Lever/Ashby/Workday patterns
Only specs marked confirmed came from live pages seen in earlier runs; every hint is
verified by discover.py before the collector uses it.
"""
from pathlib import Path

import yaml

T = """
# ---- Bulge bracket / large US banks
Goldman Sachs|1|Bulge bracket||GS,Goldman
Morgan Stanley|1|Bulge bracket|hint-eightfold:morganstanley.eightfold.ai/morganstanley.com|
J.P. Morgan|1|Bulge bracket|hint-oracle:jpmc.fa.oraclecloud.com/CX_1001|JPMorgan Chase,JPMorgan,JPMorganChase,JPMorgan Chase & Co.
Bank of America|1|Bulge bracket||BofA,BofA Securities,Bank of America Merrill Lynch
Citi|1|Bulge bracket|hint-wd:citi/wd5/2|Citigroup,Citibank
Wells Fargo|1|Bulge bracket|hint-wd:wf/wd1/WellsFargoJobs|Wells Fargo Securities
BNY|2|Custody / markets|hint-wd:bnymellon/wd5/Global|BNY Mellon,Bank of New York Mellon
State Street|2|Custody / markets|hint-wd:statestreet/wd1/Global|State Street Global Markets
# ---- Foreign banks with NYC markets desks
Barclays|1|Bulge bracket|hint-wd:barclays/wd3/External_Career_Site_Barclays|
Deutsche Bank|1|Foreign bank||DB
UBS|1|Foreign bank||
BNP Paribas|1|Foreign bank||BNP
Société Générale|1|Foreign bank||Societe Generale,SocGen,SG Americas
Natixis|2|Foreign bank||Natixis CIB,Groupe BPCE
Crédit Agricole CIB|2|Foreign bank||Credit Agricole,Credit Agricole CIB,CACIB
HSBC|2|Foreign bank||
Santander US Capital Markets|2|Foreign bank||Santander
BBVA|2|Foreign bank||
ING|2|Foreign bank||
Rabobank|2|Foreign bank||
Mizuho|1|Foreign bank|hint-wd:mizuho/wd1/mizuhoamericas|Mizuho Americas,Mizuho Securities,Mizuho Financial Group
MUFG|2|Foreign bank|hint-wd:mufgub/wd3/MUFG-Careers|MUFG Bank,MUFG Americas,MUFG Securities
SMBC Nikko|2|Foreign bank||SMBC,Sumitomo Mitsui
Nomura|1|Foreign bank||Nomura Securities
Daiwa Capital Markets|2|Foreign bank||Daiwa
RBC Capital Markets|1|Foreign bank|hint-wd:rbc/wd3/RBCGLOBAL1|RBC,Royal Bank of Canada
TD Securities|1|Foreign bank|hint-wd:td/wd3/TD_Bank_Careers|TD,TD Bank,TD Cowen,TD Bank Group
BMO Capital Markets|1|Foreign bank|hint-wd:bmo/wd3/External|BMO
Scotiabank|2|Foreign bank||Bank of Nova Scotia
CIBC Capital Markets|2|Foreign bank||CIBC
Macquarie|1|Commodities / IB||Macquarie Group
Standard Chartered|2|Foreign bank||
Itau BBA|2|Foreign bank||Itau
# ---- Middle market / boutique S&T and IB
Jefferies|1|Middle market / S&T||
Citizens JMP|2|Middle market||Citizens,Citizens Bank,JMP Securities
KeyBanc Capital Markets|2|Middle market||KeyBanc,KeyBank
Truist Securities|2|Middle market||Truist
PNC|1|Commercial / corporate banking|hint-wd:pnc/wd5/External|PNC Bank
U.S. Bank|2|Commercial / corporate banking||US Bank
Fifth Third|2|Commercial banking||Fifth Third Bank
Capital One|2|Commercial / corporate banking|hint-wd:capitalone/wd12/Capital_One|
M&T Bank|2|Commercial banking|wd:mtb/wd5/Campus|M&T
Webster Bank|2|Commercial banking||
Valley Bank|2|Commercial banking||
Provident Bank|2|Commercial banking||
Northern Trust|2|Asset manager / commercial bank|hint-wd:ntrs/wd1/northerntrust|
Piper Sandler|1|Middle market / S&T||
Raymond James|2|Middle market / S&T||
Stifel|2|Middle market / S&T||Stifel Nicolaus,KBW,Keefe Bruyette & Woods
Baird|2|Middle market / IB & equities||Robert W. Baird
William Blair|1|Middle market / IB & equities||
Oppenheimer|2|Broker-dealer / S&T||Oppenheimer & Co.
Needham & Company|2|Broker-dealer / S&T||Needham
BTIG|1|Broker-dealer / equity S&T|gh:btig27|
Cantor Fitzgerald|1|Broker-dealer / S&T||Cantor
B. Riley Securities|2|Broker-dealer / S&T|gh:brileysecurities|B. Riley
Guggenheim Securities|2|Boutique IB / S&T|hint-wd:guggenheim/wd1/Guggenheim_Careers|Guggenheim
Wolfe Research|1|Equity research / execution||
Evercore|1|Elite boutique IB||Evercore ISI
Lazard|1|Elite boutique IB||
Moelis & Company|1|Elite boutique IB||Moelis
PJT Partners|2|Elite boutique IB|wd:pjtpartners/wd1/Students|PJT
Perella Weinberg Partners|2|Elite boutique IB||Perella Weinberg,PWP
Centerview Partners|2|Elite boutique IB||Centerview
Houlihan Lokey|2|Middle market IB||
Canaccord Genuity|2|Broker-dealer / S&T||Canaccord
Janney Montgomery Scott|2|Broker-dealer / S&T||Janney
D.A. Davidson|2|Broker-dealer / S&T||DA Davidson
Wedbush Securities|2|Broker-dealer / S&T||Wedbush
Roth Capital Partners|2|Broker-dealer / S&T||Roth
Northland Capital Markets|2|Broker-dealer / S&T||Northland
Craig-Hallum|2|Broker-dealer / S&T||
Benchmark Company|2|Broker-dealer / S&T||Benchmark
Rosenblatt Securities|2|Agency execution||Rosenblatt
Seaport Global|2|Fixed income S&T||Seaport Global Securities
Academy Securities|2|Broker-dealer / S&T||
Mischler Financial|2|Broker-dealer / S&T||Mischler
Drexel Hamilton|2|Broker-dealer / S&T||
Loop Capital|2|Broker-dealer / S&T||Loop Capital Markets
Siebert Williams Shank|2|Broker-dealer / S&T||Siebert Williams Shank & Co
Brean Capital|2|Fixed income S&T||
Mesirow|2|Broker-dealer / S&T||Mesirow Financial
Odeon Capital|2|Fixed income S&T||Odeon Capital Group
Mizuho Greenhill|3|Boutique IB||Greenhill
Clear Street|1|Broker-dealer / equity S&T|gh:clearstreet|
StoneX|0|EXCLUDED per Andrew||StoneX Group
# ---- Agency / electronic execution, venues, IDBs
Virtu Financial|1|Electronic execution / market making|gh:virtu|Virtu
Instinet|1|Agency electronic execution||
Liquidnet (TP ICAP)|2|Agency electronic execution||Liquidnet,TP ICAP,Tullett Prebon
BGC Group|2|Interdealer broker||BGC Partners,BGC
Tradition|2|Interdealer broker||Tradition America
Marex|2|Broker-dealer / commodities & derivatives||Marex Group
MarketAxess|2|Fixed income electronic trading||
Tradeweb|2|Fixed income electronic trading||Tradeweb Markets
IEX Group|2|Exchange||IEX
Nasdaq|2|Exchange|hint-wd:nasdaq/wd1/Global_External_Site|
Intercontinental Exchange|2|Exchange||ICE,NYSE
Cboe Global Markets|2|Exchange||Cboe
CME Group|2|Exchange||CME
MIAX|2|Exchange||Miami International Holdings
Bloomberg|2|Markets data / analytics & sales||Bloomberg LP
Federal Reserve Bank of New York|2|Central bank markets group|wd:rb/wd5/FRS|New York Fed,Federal Reserve
# ---- Market makers / prop
Citadel Securities|1|Market maker||
Jane Street|1|Market maker||
Susquehanna (SIG)|1|Market maker||Susquehanna,SIG,Susquehanna International Group
Optiver|1|Market maker||
IMC Trading|2|Market maker|hint-gh-eu:imc|IMC
DRW|1|Prop trading|gh:drweng|
Hudson River Trading|2|Prop trading||HRT
Jump Trading|2|Prop trading||
Tower Research Capital|2|Prop trading||Tower Research
Five Rings|2|Prop trading||Five Rings Capital,Five Rings LLC
Akuna Capital|2|Market maker (options)||Akuna
Peak6|2|Prop trading||PEAK6
Belvedere Trading|2|Market maker (options)|lever:belvederetrading|Belvedere
Wolverine Trading|2|Market maker (options)||Wolverine
Group One Trading|2|Market maker (options)||Group One
Flow Traders|2|Market maker|gh:flowtraders|
XR Trading|2|Prop trading||
Old Mission Capital|2|Market maker||Old Mission
Headlands Technologies|2|Prop trading||Headlands
Vatic Labs|2|Prop trading||
GTS|2|Market maker||GTS Securities
Maven Securities|2|Market maker||Maven
Galaxy|2|Digital-asset trading||Galaxy Digital
FalconX|2|Digital-asset trading||
Cumberland|2|Digital-asset trading||Cumberland DRW
# ---- Hedge funds / buy-side trading desks
Citadel|2|Hedge fund||Citadel LLC
Point72|1|Hedge fund|gh:point72|Point72 Asset Management
Millennium|2|Hedge fund||Millennium Management
Balyasny|2|Hedge fund||Balyasny Asset Management,BAM
Schonfeld|2|Hedge fund|gh:schonfeld|Schonfeld Strategic Advisors
ExodusPoint|2|Hedge fund||ExodusPoint Capital
Verition|2|Hedge fund||Verition Fund Management
Hudson Bay Capital|2|Hedge fund||Hudson Bay
Jain Global|2|Hedge fund||
D. E. Shaw|2|Hedge fund||D.E. Shaw,DE Shaw
Two Sigma|2|Hedge fund||
Marshall Wace|2|Hedge fund||
Brevan Howard|2|Hedge fund||
Squarepoint Capital|2|Hedge fund||Squarepoint
Caxton Associates|2|Hedge fund||Caxton
Pharo Management|2|Hedge fund||Pharo
Tudor Investment|2|Hedge fund||Tudor
BlackRock|1|Asset manager (trading)||
AllianceBernstein|2|Asset manager (trading)||AB,Bernstein
Neuberger Berman|2|Asset manager (trading)||
Nuveen|2|Asset manager (trading)||TIAA
PGIM|2|Asset manager (trading)||Prudential,PGIM Fixed Income
MetLife Investment Management|2|Asset manager (trading)||MetLife
Goldman Sachs Asset Management|3|Asset manager (trading)||GSAM
Invesco|2|Asset manager (trading)||
Franklin Templeton|2|Asset manager (trading)||
Lord Abbett|2|Asset manager (trading)||
Jennison Associates|2|Asset manager (trading)||Jennison
Apollo|2|Alternative asset manager||Apollo Global Management
Blackstone|2|Alternative asset manager||
KKR|2|Alternative asset manager||
# ---- Commodities trading
Castleton Commodities|2|Commodities trading||Castleton Commodities International,CCI
Hartree Partners|2|Commodities trading||Hartree
Freepoint Commodities|2|Commodities trading||Freepoint
Mercuria|2|Commodities trading||
Vitol|2|Commodities trading||
Trafigura|2|Commodities trading||
ADM Investor Services|2|Commodities / FCM||ADMIS
"""


def parse_spec(spec: str) -> dict:
    if not spec:
        return {"ats": "unknown"}
    kind, _, val = spec.partition(":")
    hint = kind.startswith("hint-")
    kind = kind.removeprefix("hint-")
    if kind in ("gh", "gh-eu"):
        d = {"ats": "greenhouse", "token": val, **({"region": "eu"} if kind == "gh-eu" else {})}
    elif kind in ("lever", "ashby"):
        d = {"ats": kind, "token": val}
    elif kind == "sr":
        d = {"ats": "smartrecruiters", "token": val}
    elif kind == "wd":
        t, dc, site = val.split("/")
        d = {"ats": "workday", "tenant": t, "dc": dc, "site": site}
    elif kind == "eightfold":
        host, domain = val.split("/")
        d = {"ats": "eightfold", "host": host, "domain": domain}
    elif kind == "oracle":
        host, site = val.split("/")
        d = {"ats": "oracle", "host": host, "site": site}
    else:
        raise ValueError(spec)
    return {"ats": "unknown", "hint": d} if hint else d


def build():
    rows = []
    for line in T.strip().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, tier, seg, spec, aliases = (line.split("|") + [""] * 5)[:5]
        row = {"name": name.strip(), "tier": int(tier), "segment": seg.strip(), **parse_spec(spec.strip())}
        if aliases.strip():
            row["aliases"] = [a.strip() for a in aliases.split(",") if a.strip()]
        if row["tier"] == 0:
            row["exclude"] = True
        rows.append(row)
    names = [r["name"] for r in rows]
    assert len(names) == len(set(names)), "duplicate company"
    out = Path(__file__).with_name("companies.yaml")
    out.write_text("# GENERATED by build_companies.py - edit that file, not this one\n"
                   + yaml.safe_dump(rows, sort_keys=False, allow_unicode=True))
    print(f"{len(rows)} companies -> {out}")


if __name__ == "__main__":
    build()
