#!/usr/bin/env python3
"""
MK Job Board — Smart CFD Role Scraper
Tuned to Mohammad Kanaan's profile:
  - Trader at Equiti Group, Dubai
  - A/B-book risk, PrimeXM, MT4/MT5, CISI L3
  - 6+ years CFD brokerage experience
  - Target: Senior/Lead roles in Dubai/UAE

Sources: Indeed AE, Glassdoor (public search)
Outputs: docs/jobs.json
"""

import json, time, re, hashlib, os, urllib.request, urllib.error
from datetime import datetime, timezone
from urllib.parse import quote_plus

# ══════════════════════════════════════════════════════════════════════════════
#  PROFILE CONFIG  — edit this section to update Mohammad's profile
# ══════════════════════════════════════════════════════════════════════════════

PROFILE = {
    "name":             "Mohammad Kanaan",
    "title":            "Trader / CFD Desk Professional",
    "employer":         "Equiti Group",     # current — blacklisted from results
    "location":         "Dubai, UAE",
    "experience_years": 6,
    "min_match_score":  62,                 # drop anything below this
    "max_jobs_output":  30,                 # cap board at this many live roles
}

# Blacklisted companies — won't appear in results
COMPANY_BLACKLIST = [
    "equiti",
    "equiti group",
    # add more here e.g. "xm global", "bdswiss"
]

# Junior title signals — filtered out (below Mohammad's seniority)
JUNIOR_SIGNALS = [
    "junior", "entry level", "entry-level", "trainee", "graduate",
    "intern", "internship", "assistant trader", "junior dealer",
    "junior analyst", "0-1 year", "0-2 year", "fresh graduate",
]

# ══════════════════════════════════════════════════════════════════════════════
#  SEARCH QUERIES  — targeted to Mohammad's stack and seniority
# ══════════════════════════════════════════════════════════════════════════════

SEARCHES = [
    # Core role titles
    {"q": "senior CFD dealer Dubai",                    "loc": "Dubai, UAE"},
    {"q": "senior forex dealer dealing desk Dubai",     "loc": "Dubai, UAE"},
    {"q": "head of dealing desk Dubai",                 "loc": "Dubai, UAE"},
    {"q": "trading desk manager CFD forex Dubai",       "loc": "Dubai, UAE"},
    # Risk specialisation
    {"q": "CFD risk manager Dubai A-book B-book",       "loc": "Dubai, UAE"},
    {"q": "internal risk manager forex broker Dubai",   "loc": "Dubai, UAE"},
    {"q": "market risk analyst CFD broker UAE",         "loc": "Dubai, UAE"},
    # Tech stack
    {"q": "PrimeXM MT5 dealer risk Dubai",              "loc": "Dubai, UAE"},
    {"q": "MT5 bridge manager CFD forex Dubai",         "loc": "Dubai, UAE"},
    {"q": "Centroid OneZero dealer Dubai",              "loc": "Dubai, UAE"},
    # Liquidity / hybrid
    {"q": "liquidity manager CFD broker Dubai",         "loc": "Dubai, UAE"},
    {"q": "hybrid book risk trader Dubai UAE",          "loc": "Dubai, UAE"},
    # Broader UAE net
    {"q": "senior CFD dealer UAE",                      "loc": "United Arab Emirates"},
    {"q": "forex risk manager broker UAE",              "loc": "United Arab Emirates"},
    # Named brokers
    {"q": "Pepperstone trader dealer risk Dubai",       "loc": "Dubai, UAE"},
    {"q": "Saxo Bank dealer risk Dubai",                "loc": "Dubai, UAE"},
    {"q": "XTB dealer risk manager Dubai",              "loc": "Dubai, UAE"},
    {"q": "ThinkMarkets dealer trader Dubai",           "loc": "Dubai, UAE"},
    {"q": "Axi dealer risk Dubai",                      "loc": "Dubai, UAE"},
    {"q": "FXCM dealer risk Dubai",                     "loc": "Dubai, UAE"},
]

# ══════════════════════════════════════════════════════════════════════════════
#  RELEVANCE & SCORING
# ══════════════════════════════════════════════════════════════════════════════

MUST_HAVE = [
    "cfd", "forex", "fx", "dealer", "dealing desk", "market maker",
    "market making", "a-book", "b-book", "trading desk", "mt4", "mt5",
    "metatrader", "primexm", "centroid", "onezero", "liquidity provider",
    "prop desk", "internal risk", "nop", "toxic flow", "bridge manager",
]

NOISE_WORDS = [
    "supply chain", "logistics", "truck", "driver", "nurse", "doctor",
    "teacher", "accountant", "bookkeeper", "it support", "helpdesk",
    "software engineer", "backend developer", "frontend developer",
    "full stack", "data scientist", "hr manager", "recruiter",
    "marketing manager", "graphic designer", "civil engineer",
    "mechanical engineer", "data entry", "receptionist", "secretary",
    "telesales", "telecaller", "customer service agent", "call centre",
    "real estate", "property", "hospitality", "chef", "barista",
    "retail", "fashion", "beauty", "healthcare",
]

CV_SCORE_MAP = {
    "primexm": 20, "pxm": 20,
    "centroid": 18, "onezero": 18, "one zero": 18,
    "fxcubic": 15,
    "mt5": 14, "mt4": 12, "metatrader": 12,
    "fix api": 10, "fix protocol": 10,
    "a-book": 18, "b-book": 18, "a book": 18, "b book": 18,
    "hybrid book": 16, "hybrid risk": 16, "c book": 12, "ntp": 12,
    "nop": 15, "exposure monitoring": 15, "toxic flow": 18,
    "flow analytics": 14, "book segmentation": 14,
    "risk model": 14, "manual hedging": 14, "hedging": 10,
    "p&l": 12, "p&l reconciliation": 14,
    "swaps": 10, "dividends": 10, "futures expiry": 10,
    "dealing desk": 14, "liquidity": 10,
    "spread optimis": 12, "lp": 10, "liquidity provider": 12,
    "bridge": 12, "b2b": 10, "hnw": 10, "institutional": 8,
    "cisi": 14, "sca": 12, "dfsa": 10, "uae financial": 10,
    "cfd": 8, "forex": 6, "fx": 5,
    "market making": 12, "market maker": 12,
    "execution": 6, "dealer": 8, "trader": 6,
    "internal risk": 12, "risk manager": 10,
}

# ══════════════════════════════════════════════════════════════════════════════
#  HTTP & PARSING HELPERS
# ══════════════════════════════════════════════════════════════════════════════

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
                try:
                    import gzip
                    if r.info().get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                except Exception:
                    pass
                return raw.decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"    fetch error (attempt {attempt+1}): {e}")
            time.sleep(4 * (attempt + 1))
    return ""


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text)
    for ent, rep in [("&amp;","&"),("&nbsp;"," "),("&lt;","<"),("&gt;",">"),("&#39;","'"),("&quot;",'"')]:
        text = text.replace(ent, rep)
    text = re.sub(r"&#\d+;", "", text)
    return re.sub(r"\s+", " ", text).strip()


def job_id(title, company):
    raw = f"{title.lower().strip()}|{company.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


# ══════════════════════════════════════════════════════════════════════════════
#  PROFILE-AWARE FILTERS
# ══════════════════════════════════════════════════════════════════════════════

def is_blacklisted(company):
    c = company.lower()
    return any(b in c for b in COMPANY_BLACKLIST)


def is_junior(title, snippet):
    t = (title + " " + snippet).lower()
    return any(j in t for j in JUNIOR_SIGNALS)


def is_cfd_relevant(title, snippet):
    combined = (title + " " + snippet).lower()
    if not any(kw in combined for kw in MUST_HAVE):
        return False
    if any(kw in combined for kw in NOISE_WORDS):
        return False
    return True


def detect_role(title, snippet):
    t = (title + " " + snippet).lower()
    if any(k in t for k in ["risk manager","risk analyst","internal risk","market risk","nop","exposure monitor","flow analytic"]):
        return "risk", "Internal Risk"
    if any(k in t for k in ["market maker","market making"]):
        return "mm", "Market Making"
    if any(k in t for k in ["liquidity manager","liquidity provider","bridge manager","lp manager"]):
        return "liquidity", "Liquidity"
    if any(k in t for k in ["operations manager","mt5 manager","mt4 manager","trading operations"]):
        return "ops", "Operations"
    return "trader", "Trader / Dealer"


def score_job(title, snippet):
    t = (title + " " + snippet).lower()
    total = sum(pts for kw, pts in CV_SCORE_MAP.items() if kw in t)
    if any(w in t for w in ["senior","lead","head of","principal","manager"]):
        total += 15
    if any(w in t for w in ["dubai","uae","abu dhabi"]):
        total += 8
    s = min(99, int(total * 1.1))
    label = "high" if s >= 80 else "med" if s >= 60 else "low"
    return s, label


def extract_salary(text):
    patterns = [
        r"AED\s*([\d,]+)\s*[-\u2013to]+\s*([\d,]+)\s*(?:per\s*month|/\s*month|monthly|pm)?",
        r"([\d,]+)\s*[-\u2013]\s*([\d,]+)\s*AED\s*(?:per\s*month|/\s*month|monthly|pm)?",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            lo = int(m.group(1).replace(",", ""))
            hi = int(m.group(2).replace(",", ""))
            if lo == 0:
                continue
            if lo < 50000:
                lo, hi = lo * 12, hi * 12
            if lo > 5000000:
                continue
            return lo, hi, f"AED {lo//1000}k \u2013 {hi//1000}k"
    return 0, 0, "Not disclosed"


# ══════════════════════════════════════════════════════════════════════════════
#  AI MATCH REASON
# ══════════════════════════════════════════════════════════════════════════════

CV_SUMMARY = (
    "Mohammad Kanaan — Trader at Equiti Group, Dubai (Oct 2025-present). "
    "6+ years CFD brokerage. Expert: A/B/C/NTP book risk modeling, NOP & exposure monitoring, "
    "toxic flow identification, PrimeXM & bridge management, MT4/MT5 Manager, "
    "liquidity & spread optimisation, B2B/HNW liquidity solutions, P&L reconciliation. "
    "CISI Level 3, UAE SCA regulated. 18% trading volume growth, 22% HNW retention at Equiti."
)

_ai_cache = {}


def ai_match_reason(title, company, snippet, score_val):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return _rule_reason(title, snippet, score_val)

    ckey = job_id(title, company)
    if ckey in _ai_cache:
        return _ai_cache[ckey]

    prompt = (
        f"You are a CFD recruitment analyst. In ONE sentence (max 18 words), "
        f"explain why this job is a {score_val}% match for the candidate. "
        f"Be specific about which skills overlap.\n\n"
        f"CANDIDATE: {CV_SUMMARY}\n\n"
        f"JOB: {title} at {company}. {snippet[:400]}"
    )
    try:
        body = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 80,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            reason = data["content"][0]["text"].strip().strip('"')
            _ai_cache[ckey] = reason
            return reason
    except Exception as e:
        print(f"    AI reason failed: {e}")
        return _rule_reason(title, snippet, score_val)


def _rule_reason(title, snippet, score_val):
    t = (title + " " + snippet).lower()
    hits = [kw for kw in ["primexm","mt5","a-book","b-book","toxic flow","nop","cisi","centroid","onezero","hybrid"] if kw in t]
    if hits:
        return f"Matches on: {', '.join(hits[:3])} — core skills from Mohammad's Equiti Trader role."
    if score_val >= 80:
        return "Strong overlap with CFD dealing desk and risk management experience."
    return "Moderate CFD brokerage overlap — review carefully before applying."


# ══════════════════════════════════════════════════════════════════════════════
#  SCRAPERS
# ══════════════════════════════════════════════════════════════════════════════

def build_job(title, company, loc, snippet, jkey, sal_raw, source, base_url):
    s, label = score_job(title, snippet)
    if s < PROFILE["min_match_score"]:
        return None
    smin, smax, sdisp = extract_salary(sal_raw + " " + snippet)
    rtype, rtag = detect_role(title, snippet)
    apply_url = f"https://ae.indeed.com/viewjob?jk={jkey}" if (jkey and source == "Indeed") else base_url
    return {
        "id":       job_id(title, company),
        "live":     True,
        "status":   "none",
        "title":    title,
        "company":  company,
        "location": loc,
        "type":     rtype,
        "tag":      rtag,
        "sMin":     smin,
        "sMax":     smax,
        "sal":      sdisp,
        "gd":       None,
        "score":    s,
        "label":    label,
        "reason":   "",
        "url":      apply_url,
        "src":      source,
        "ts":       int(datetime.now(timezone.utc).timestamp() * 1000),
        "_snippet": snippet,
    }


def scrape_indeed(query, location):
    results = []
    base_url = (
        f"https://ae.indeed.com/jobs"
        f"?q={quote_plus(query)}&l={quote_plus(location)}&sort=date&fromage=30&limit=15"
    )
    print(f"  -> Indeed: {query[:60]}")
    html = fetch(base_url)
    if not html:
        return results

    m = re.search(
        r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});',
        html, re.DOTALL,
    )
    if m:
        try:
            data  = json.loads(m.group(1))
            cards = data.get("metaData",{}).get("mosaicProviderJobCardsModel",{}).get("results",[])
            for c in cards:
                title   = clean(c.get("title",""))
                company = clean(c.get("company",""))
                loc     = clean(c.get("formattedLocation", location))
                snippet = clean(c.get("snippet",""))
                jkey    = c.get("jobkey","")
                sal_raw = c.get("salarySnippet",{}).get("text","")
                if not title or not company: continue
                if is_blacklisted(company): continue
                if not is_cfd_relevant(title, snippet): continue
                if is_junior(title, snippet):
                    print(f"    x junior: {title}"); continue
                job = build_job(title, company, loc, snippet, jkey, sal_raw, "Indeed", base_url)
                if job:
                    results.append(job)
        except Exception as e:
            print(f"    JSON error: {e}")

    if not results:
        card_re = re.compile(
            r'<h2[^>]*jobTitle[^>]*>.*?<span[^>]*>(.*?)</span>.*?'
            r'class="[^"]*companyName[^"]*"[^>]*>(.*?)</(?:span|a)>.*?'
            r'class="[^"]*summary[^"]*"[^>]*>(.*?)</div>',
            re.DOTALL | re.IGNORECASE,
        )
        for hit in card_re.finditer(html):
            title   = clean(hit.group(1))
            company = clean(hit.group(2))
            snippet = clean(hit.group(3))
            if is_blacklisted(company) or not is_cfd_relevant(title,snippet): continue
            if is_junior(title, snippet): continue
            job = build_job(title, company, location, snippet, "", "", "Indeed", base_url)
            if job:
                results.append(job)

    return results


def scrape_glassdoor(query, location):
    results = []
    base_url = (
        f"https://www.glassdoor.com/Job/jobs.htm"
        f"?sc.keyword={quote_plus(query)}&locT=C&locId=1159&fromAge=30"
    )
    print(f"  -> Glassdoor: {query[:60]}")
    html = fetch(base_url)
    if not html:
        return results

    m = re.search(
        r'"jobListings"\s*:\s*(\[.*?\])\s*,\s*"(?:totalJobsCount|paginationCursors)"',
        html, re.DOTALL,
    )
    if not m:
        return results

    try:
        listings = json.loads(m.group(1))
        for item in listings:
            jd      = item.get("jobview", item)
            header  = jd.get("header", {})
            title   = clean(header.get("jobTitleText","") or jd.get("jobTitleText",""))
            company = clean(header.get("employerNameFromSearch","") or jd.get("employerName",""))
            loc     = clean(header.get("locationName", location))
            snippet = clean(jd.get("jobDescriptionText","")[:500])
            gd_rat  = header.get("rating") or jd.get("rating")
            jid_raw = jd.get("jobListingId","")
            job_url = f"https://www.glassdoor.com/job-listing/?jl={jid_raw}" if jid_raw else base_url

            if not title or not company: continue
            if is_blacklisted(company): continue
            if not is_cfd_relevant(title, snippet): continue
            if is_junior(title, snippet): continue

            job = build_job(title, company, loc, snippet, "", "", "Glassdoor", job_url)
            if job:
                if gd_rat:
                    try: job["gd"] = round(float(gd_rat), 1)
                    except Exception: pass
                results.append(job)
    except Exception as e:
        print(f"    Glassdoor parse error: {e}")

    return results


# ══════════════════════════════════════════════════════════════════════════════
#  DEDUP & MERGE
# ══════════════════════════════════════════════════════════════════════════════

def dedup(jobs):
    seen = {}
    for j in jobs:
        jid = j["id"]
        if jid not in seen or j["score"] > seen[jid]["score"]:
            seen[jid] = j
    return list(seen.values())


def merge(existing, fresh):
    now_ms        = int(datetime.now(timezone.utc).timestamp() * 1000)
    sixty_days_ms = 60 * 24 * 60 * 60 * 1000
    existing_map  = {j["id"]: j for j in existing}
    merged = {}

    for job in fresh:
        jid = job["id"]
        if jid in existing_map:
            job["status"] = existing_map[jid].get("status","none")
        merged[jid] = job

    for job in existing:
        if not job.get("live", True):
            merged[job["id"]] = job

    result = [
        j for j in merged.values()
        if not j.get("live",True) or (now_ms - j.get("ts",now_ms)) < sixty_days_ms
    ]
    result.sort(key=lambda j: j.get("score",0), reverse=True)
    return result[:PROFILE["max_jobs_output"]]


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    out_dir  = os.path.join(os.path.dirname(__file__), "..", "docs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "jobs.json")

    existing = []
    if os.path.exists(out_path):
        try:
            with open(out_path) as f:
                existing = json.load(f).get("jobs",[])
            print(f"Loaded {len(existing)} existing jobs.")
        except Exception as e:
            print(f"Warning: could not load existing jobs: {e}")

    fresh = []

    for s in SEARCHES:
        fresh.extend(scrape_indeed(s["q"], s["loc"]))
        time.sleep(2)

    for s in [
        {"q": "CFD dealer trader Dubai",   "loc": "Dubai"},
        {"q": "forex risk manager Dubai",  "loc": "Dubai"},
        {"q": "MT5 PrimeXM dealer Dubai",  "loc": "Dubai"},
    ]:
        fresh.extend(scrape_glassdoor(s["q"], s["loc"]))
        time.sleep(3)

    print(f"\nRaw scraped: {len(fresh)}")
    fresh = dedup(fresh)
    print(f"After dedup: {len(fresh)}")

    has_key = bool(os.environ.get("ANTHROPIC_API_KEY",""))
    print(f"AI reasons: {'enabled' if has_key else 'rule-based'}")
    for job in fresh:
        snippet = job.pop("_snippet","")
        if not job.get("reason"):
            job["reason"] = ai_match_reason(job["title"], job["company"], snippet, job["score"])
        if has_key:
            time.sleep(0.3)

    merged = merge(existing, fresh)
    print(f"Final board: {len(merged)} roles")

    payload = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "count":   len(merged),
        "jobs":    merged,
    }
    with open(out_path,"w") as f:
        json.dump(payload, f, indent=2)

    high = sum(1 for j in merged if j["label"]=="high")
    med  = sum(1 for j in merged if j["label"]=="med")
    print(f"Done. High: {high}  Med: {med}  Total: {len(merged)}")
    print(f"Written -> {out_path}")


if __name__ == "__main__":
    main()
