#!/usr/bin/env python3
"""
MK Job Board — CFD Role Scraper
Searches Indeed for CFD/Dealer/Risk roles in Dubai & UAE.
Outputs: docs/jobs.json
"""

import json, time, re, hashlib, os
from datetime import datetime, timezone
from urllib.parse import quote_plus
import urllib.request, urllib.error

# ── CONFIG ────────────────────────────────────────────────────────────────────

SEARCHES = [
    {"q": "CFD trader dealer Dubai",            "location": "Dubai, UAE"},
    {"q": "forex dealer dealing desk Dubai",    "location": "Dubai, UAE"},
    {"q": "CFD risk manager Dubai",             "location": "Dubai, UAE"},
    {"q": "market risk forex CFD Dubai",        "location": "Dubai, UAE"},
    {"q": "MT5 dealer forex Dubai",             "location": "Dubai, UAE"},
    {"q": "liquidity manager CFD Dubai",        "location": "Dubai, UAE"},
    {"q": "A-book B-book risk trader UAE",      "location": "Dubai, UAE"},
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Keywords that mark a role as relevant to Mohammad's profile
CFD_KEYWORDS = [
    "cfd", "forex", "fx", "dealer", "dealing desk", "market maker", "market making",
    "a-book", "b-book", "a book", "b book", "hybrid book", "risk manager",
    "trading desk", "liquidity", "mt4", "mt5", "metatrader", "primexm",
    "centroid", "onezero", "bridge", "nop", "exposure", "toxic flow",
    "execution", "spread", "hedging", "prop desk", "internal risk",
]

# Keywords that mean it's NOT relevant (filter noise)
NOISE_KEYWORDS = [
    "supply chain", "logistics", "driver", "nurse", "teacher", "accountant",
    "it support", "software engineer", "developer", "hr ", "marketing",
    "sales executive", "telesales", "telecaller", "customer service",
    "graphic design", "civil engineer", "data entry",
]

ROLE_TYPE_MAP = {
    "trader":   ["trader", "trading", "prop desk"],
    "risk":     ["risk manager", "risk analyst", "internal risk", "market risk", "nop", "exposure"],
    "mm":       ["market maker", "market making"],
    "ops":      ["operations", "mt5 manager", "mt4 manager", "trading operations"],
    "liquidity":["liquidity", "bridge", "primexm", "onezero", "centroid"],
    "trader":   ["dealer", "dealing desk", "dealing"],  # dealer → trader bucket
}

# Mohammad's CV keywords for match scoring
CV_KEYWORDS = {
    "primexm": 15, "pxm": 15,
    "a-book": 12, "b-book": 12, "a book": 12, "b book": 12,
    "hybrid": 10, "hybrid risk": 12,
    "mt4": 8, "mt5": 8, "metatrader": 8,
    "nop": 10, "exposure monitoring": 10, "toxic flow": 12,
    "liquidity": 8, "spread optimization": 10,
    "p&l": 8, "dealing desk": 10, "dealer": 8,
    "cfd": 6, "forex": 5, "fx": 5,
    "risk model": 10, "risk manager": 8,
    "b2b": 6, "hnw": 6,
    "cisi": 8, "sca": 6,
    "bridge": 8, "centroid": 10, "onezero": 10,
    "market making": 10,
    "execution": 5, "hedging": 8,
}

# ── HELPERS ───────────────────────────────────────────────────────────────────

def fetch(url: str, retries=3) -> str:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"  Fetch error (attempt {attempt+1}): {e}")
            time.sleep(3 * (attempt + 1))
    return ""


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#\d+;", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def job_id(title: str, company: str) -> str:
    raw = f"{title.lower().strip()}{company.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def is_relevant(title: str, snippet: str) -> bool:
    combined = (title + " " + snippet).lower()
    if not any(kw in combined for kw in CFD_KEYWORDS):
        return False
    if any(kw in combined for kw in NOISE_KEYWORDS):
        return False
    return True


def detect_role_type(title: str, snippet: str) -> tuple[str, str]:
    t = (title + " " + snippet).lower()
    if any(k in t for k in ["risk manager", "risk analyst", "internal risk", "market risk", "nop"]):
        return "risk", "Internal Risk"
    if any(k in t for k in ["market maker", "market making"]):
        return "mm", "Market Making"
    if any(k in t for k in ["liquidity manager", "liquidity provider", "bridge manager"]):
        return "liquidity", "Liquidity"
    if any(k in t for k in ["operations manager", "mt5 manager", "mt4 manager", "trading operations"]):
        return "ops", "Operations"
    return "trader", "Trader / Dealer"


def score_match(title: str, snippet: str) -> tuple[int, str]:
    t = (title + " " + snippet).lower()
    total = 0
    for kw, pts in CV_KEYWORDS.items():
        if kw in t:
            total += pts
    # Normalise to 0–99
    score = min(99, int(total * 1.4))
    label = "high" if score >= 80 else "med" if score >= 60 else "low"
    return score, label


def extract_salary(text: str) -> tuple[int, int, str]:
    """Try to extract AED salary from text. Returns (min, max, display)."""
    # Pattern: AED 10,000 – 20,000 / month  or  15000 - 25000 AED
    patterns = [
        r"AED\s*([\d,]+)\s*[-–]\s*([\d,]+)\s*(?:per\s*month|/\s*month|monthly|pm)?",
        r"([\d,]+)\s*[-–]\s*([\d,]+)\s*AED\s*(?:per\s*month|/\s*month|monthly|pm)?",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            lo = int(m.group(1).replace(",", ""))
            hi = int(m.group(2).replace(",", ""))
            # Convert monthly → annual
            if lo < 50000:   # looks monthly
                lo, hi = lo * 12, hi * 12
            return lo, hi, f"AED {lo//1000}k – {hi//1000}k"
    return 0, 0, "Not disclosed"


# ── INDEED SCRAPER ────────────────────────────────────────────────────────────

def scrape_indeed(query: str, location: str) -> list[dict]:
    results = []
    q_enc  = quote_plus(query)
    l_enc  = quote_plus(location)
    url    = f"https://ae.indeed.com/jobs?q={q_enc}&l={l_enc}&sort=date&fromage=30"

    print(f"  → Indeed: {query}")
    html = fetch(url)
    if not html:
        return results

    # Extract job cards — Indeed embeds JSON in a script tag
    # Try JSON first, fallback to HTML parsing
    json_match = re.search(r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});', html, re.DOTALL)

    if json_match:
        try:
            data = json.loads(json_match.group(1))
            cards = data.get("metaData", {}).get("mosaicProviderJobCardsModel", {}).get("results", [])
            for c in cards[:8]:
                title   = clean(c.get("title", ""))
                company = clean(c.get("company", ""))
                loc     = clean(c.get("formattedLocation", location))
                snippet = clean(c.get("snippet", ""))
                job_key = c.get("jobkey", "")
                apply_url = f"https://ae.indeed.com/viewjob?jk={job_key}" if job_key else url
                sal_txt = c.get("salarySnippet", {}).get("text", "")
                s_min, s_max, s_disp = extract_salary(sal_txt + " " + snippet)

                if not title or not company:
                    continue
                if not is_relevant(title, snippet):
                    continue

                rtype, rtag = detect_role_type(title, snippet)
                score, label = score_match(title, snippet)

                results.append({
                    "id":      job_id(title, company),
                    "live":    True,
                    "status":  "none",
                    "title":   title,
                    "company": company,
                    "location": loc or location,
                    "type":    rtype,
                    "tag":     rtag,
                    "sMin":    s_min,
                    "sMax":    s_max,
                    "sal":     s_disp,
                    "gd":      None,
                    "score":   score,
                    "label":   label,
                    "reason":  "",
                    "url":     apply_url,
                    "src":     "Indeed",
                    "ts":      int(datetime.now(timezone.utc).timestamp() * 1000),
                })
        except (json.JSONDecodeError, KeyError) as e:
            print(f"    JSON parse error: {e}")

    # Fallback: regex parse HTML job cards
    if not results:
        card_pat = re.compile(
            r'<h2[^>]*class="[^"]*jobTitle[^"]*"[^>]*>.*?<span[^>]*>(.*?)</span>.*?'
            r'<span[^>]*class="[^"]*companyName[^"]*"[^>]*>(.*?)</span>.*?'
            r'<div[^>]*class="[^"]*summary[^"]*"[^>]*>(.*?)</div>',
            re.DOTALL | re.IGNORECASE,
        )
        for m in card_pat.finditer(html):
            title   = clean(m.group(1))
            company = clean(m.group(2))
            snippet = clean(m.group(3))
            if not is_relevant(title, snippet):
                continue
            rtype, rtag = detect_role_type(title, snippet)
            score, label = score_match(title, snippet)
            _, _, s_disp = extract_salary(snippet)
            results.append({
                "id":      job_id(title, company),
                "live":    True,
                "status":  "none",
                "title":   title,
                "company": company,
                "location": location,
                "type":    rtype,
                "tag":     rtag,
                "sMin":    0,
                "sMax":    0,
                "sal":     s_disp,
                "gd":      None,
                "score":   score,
                "label":   label,
                "reason":  "",
                "url":     url,
                "src":     "Indeed",
                "ts":      int(datetime.now(timezone.utc).timestamp() * 1000),
            })

    return results


# ── MERGE & DEDUPLICATE ───────────────────────────────────────────────────────

def merge(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """Keep user status/saves from existing; add new; remove stale (>60 days)."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    sixty_days_ms = 60 * 24 * 60 * 60 * 1000

    # Index existing by id, preserving user-set fields
    existing_map = {j["id"]: j for j in existing}

    merged_map: dict[str, dict] = {}

    # Add fresh jobs, inheriting status if already tracked
    for job in fresh:
        jid = job["id"]
        if jid in existing_map:
            old = existing_map[jid]
            job["status"] = old.get("status", "none")  # preserve bookmark/apply state
        merged_map[jid] = job

    # Keep manually-added jobs (live=False) regardless
    for job in existing:
        if not job.get("live", True):
            merged_map[job["id"]] = job

    # Remove stale live jobs older than 60 days
    result = [
        j for j in merged_map.values()
        if not j.get("live", True) or (now_ms - j.get("ts", now_ms)) < sixty_days_ms
    ]

    result.sort(key=lambda j: j.get("score", 0), reverse=True)
    return result


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    out_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "jobs.json")

    # Load existing jobs (to preserve user status)
    existing = []
    if os.path.exists(out_path):
        try:
            with open(out_path) as f:
                data = json.load(f)
                existing = data.get("jobs", [])
            print(f"Loaded {len(existing)} existing jobs.")
        except Exception as e:
            print(f"Could not load existing jobs: {e}")

    # Scrape fresh
    fresh: list[dict] = []
    seen_ids: set[str] = set()

    for search in SEARCHES:
        batch = scrape_indeed(search["q"], search["location"])
        for job in batch:
            if job["id"] not in seen_ids:
                seen_ids.add(job["id"])
                fresh.append(job)
        time.sleep(2)  # polite delay between searches

    print(f"Scraped {len(fresh)} fresh relevant roles.")

    # Merge with existing
    merged = merge(existing, fresh)
    print(f"Total after merge: {len(merged)} roles.")

    # Write output
    payload = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "count":   len(merged),
        "jobs":    merged,
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"✓ Written to {out_path}")


if __name__ == "__main__":
    main()
