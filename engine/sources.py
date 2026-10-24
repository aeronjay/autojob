"""Job source adapters. Each returns a list of dicts in one common shape:
source, url, title, company, location, salary, job_type, posted_at, description, tags
"""
import html
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
session = requests.Session()
session.headers["User-Agent"] = UA


def get(url, **kw):
    """GET with a polite back-off when the site says we're going too fast (HTTP 429)."""
    for wait in (20, 60, None):
        r = session.get(url, timeout=30, **kw)
        if r.status_code != 429 or wait is None:
            r.raise_for_status()
            return r
        time.sleep(int(r.headers.get("Retry-After", wait)) if r.headers.get("Retry-After", "").isdigit() else wait)


def clean(text):
    """HTML -> plain text."""
    if not text:
        return ""
    # OnlineJobs.ph injects hidden marker text into posts; drop it.
    text = re.sub(r"<ojfilter[^>]*>.*?</ojfilter>", "", str(text), flags=re.S)
    text = re.sub(r"<(br|/p|/li|/div|/h\d)[^>]*>", "\n", str(text), flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def listy(v):
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v or "")


def money(lo, hi, period="", currency="USD"):
    lo, hi = (int(float(x)) if x not in (None, "", 0, "0") else None for x in (lo, hi))
    if not lo and not hi:
        return ""
    rng = f"{lo:,}–{hi:,}" if lo and hi else f"{(lo or hi):,}"
    return f"{currency} {rng} {period}".strip()


# --- Paging ---------------------------------------------------------------------
# Sources get a ctx dict: search (terms from every track), seen(url) (already in
# the database) and cutoff ("YYYY-MM-DD", posts older than this are stale).

def keep_paging(page_jobs, full_page, ctx, by_date):
    """Fetch the next page only if this one was full and still had jobs we haven't seen.
    For date-sorted results, also stop once we're into posts older than the cutoff."""
    if len(page_jobs) < full_page or all(ctx["seen"](j["url"]) for j in page_jobs):
        return False
    return not (by_date and min(j["posted_at"] for j in page_jobs)[:10] < ctx["cutoff"])


def search_terms(cfg, ctx):
    return list(dict.fromkeys(ctx["search"] + cfg.get("extra_search", [])))


def run_searches(cfg, ctx, search_one):
    """Run search_one(term) for every term, keeping results even if some terms fail."""
    out = []
    for kw in search_terms(cfg, ctx):
        try:
            out += search_one(kw)
        except requests.RequestException as e:
            ctx["warn"](f"'{kw}': {e}")
            if getattr(e.response, "status_code", None) == 429:
                ctx["warn"]("still rate-limited after retries; skipping the remaining searches")
                break
    return out


# --- OnlineJobs.ph (scraped politely: delay between requests, stop early) -------

OLJ_BASE = "https://www.onlinejobs.ph"


def onlinejobs(cfg, ctx):
    def search_one(kw):
        out = []
        for page in range(cfg.get("max_pages", 3)):
            offset = f"/{page * 30}" if page else ""
            r = get(f"{OLJ_BASE}/jobseekers/jobsearch{offset}?jobkeyword={quote_plus(kw)}")
            jobs = parse_olj(r.text)
            out += jobs
            time.sleep(cfg.get("delay_seconds", 3))
            # OLJ lists newest first, so old or already-seen posts mean we're caught up.
            if not keep_paging(jobs, 30, ctx, by_date=True):
                break
        return out
    return run_searches(cfg, ctx, search_one)


def parse_olj(page):
    jobs = []
    for card in page.split("<!-- Start -->")[1:]:
        card = card.split("<!-- End -->")[0]
        href = re.search(r'href="(/jobseekers/job/[^"]+)"', card)
        title = re.search(r"<h4[^>]*>(.*?)</h4>", card, re.S)
        if not href or not title:
            continue
        badge = re.search(r'<span class="badge[^"]*">([^<]+)</span>', title.group(1))
        company = re.search(r'class="jobpost-cat-box-logo" alt="([^"]*)"', card)
        posted = re.search(r'data-temp="([^"]+)"', card)
        salary = re.search(r'icon-round-dollar.*?<dd class="col">(.*?)</dd>', card, re.S)
        desc = re.search(r'<div class="desc[^"]*">(.*?)<a href', card, re.S)
        jobs.append({
            "source": "onlinejobs",
            "url": OLJ_BASE + href.group(1),
            "title": clean(re.sub(r"<span.*?</span>", "", title.group(1), flags=re.S)),
            "company": clean(company.group(1)) if company else "",
            "location": "Philippines",
            "salary": clean(salary.group(1)) if salary else "",
            "job_type": clean(badge.group(1)) if badge else "",
            "posted_at": posted.group(1) if posted else "",
            "description": clean(desc.group(1)) if desc else "",
        })
    return jobs


def olj_details(url):
    """Full post text + hours from an OLJ job page (search results only show a snippet)."""
    page = get(url).text
    desc = re.search(r'<p id="job-description"[^>]*>(.*?)</p>', page, re.S)
    text = desc.group(1) if desc else ""
    hours = re.search(r"HOURS PER WEEK.*?<p[^>]*>(.*?)</p>", page, re.S)
    hours = clean(hours.group(1)) if hours else ""
    return clean(text) + (f"\n\nHours per week: {hours}" if hours else "")


# --- JSON APIs ----------------------------------------------------------------

def himalayas(cfg, ctx):
    def search_one(kw):
        out = []
        for page in range(1, cfg.get("max_pages", 2) + 1):
            data = get("https://himalayas.app/jobs/api/search",
                       params={"q": kw, "country": cfg.get("country", "Philippines"), "page": page}).json()
            jobs = [himalayas_job(j) for j in data.get("jobs", [])]
            out += jobs
            time.sleep(cfg.get("delay_seconds", 2))
            # Sorted by relevance, not date, so only "nothing new" stops paging.
            if not keep_paging(jobs, 20, ctx, by_date=False):
                break
        return out
    return run_searches(cfg, ctx, search_one)


def himalayas_job(j):
    return {
        "source": "himalayas",
        "url": j.get("applicationLink") or j.get("guid"),
        "title": j["title"],
        "company": j.get("companyName", ""),
        # Empty restriction list means open worldwide.
        "location": listy(j.get("locationRestrictions")) or "Worldwide",
        "salary": money(j.get("minSalary"), j.get("maxSalary"), j.get("salaryPeriod", ""), j.get("currency") or "USD"),
        "job_type": j.get("employmentType", ""),
        "posted_at": time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(j["pubDate"]))) if j.get("pubDate") else "",
        "description": clean(j.get("description") or j.get("excerpt")),
        "tags": listy(j.get("categories")),
    }


def jobicy(cfg, ctx):
    out = []
    for geo in cfg.get("geos", [""]):
        params = {"count": 50}
        if geo:
            params["geo"] = geo
        for j in get("https://jobicy.com/api/v2/remote-jobs", params=params).json().get("jobs", []):
            out.append({
                "source": "jobicy",
                "url": j["url"],
                "title": html.unescape(j["jobTitle"]),
                "company": j.get("companyName", ""),
                "location": j.get("jobGeo", ""),
                "salary": money(j.get("annualSalaryMin"), j.get("annualSalaryMax"), "annual", j.get("salaryCurrency") or "USD"),
                "job_type": listy(j.get("jobType")),
                "posted_at": j.get("pubDate", "")[:16].replace("T", " "),
                "description": clean(j.get("jobDescription") or j.get("jobExcerpt")),
                "tags": listy(j.get("jobIndustry")),
            })
        time.sleep(1)
    return out


def remotive(cfg, ctx):
    out = []
    for j in get("https://remotive.com/api/remote-jobs").json().get("jobs", []):
        out.append({
            "source": "remotive",
            "url": j["url"],
            "title": j["title"],
            "company": j.get("company_name", ""),
            "location": j.get("candidate_required_location", ""),
            "salary": j.get("salary", ""),
            "job_type": j.get("job_type", ""),
            "posted_at": j.get("publication_date", "")[:16].replace("T", " "),
            "description": clean(j.get("description")),
            "tags": f"{j.get('category', '')}, {listy(j.get('tags'))}",
        })
    return out


def remoteok(cfg, ctx):
    out = []
    for j in get("https://remoteok.com/api").json()[1:]:  # first item is a legal notice
        if not j.get("position"):
            continue
        out.append({
            "source": "remoteok",
            "url": j.get("url") or j.get("apply_url"),
            "title": j["position"],
            "company": j.get("company", ""),
            "location": j.get("location", ""),
            "salary": money(j.get("salary_min"), j.get("salary_max"), "annual"),
            "posted_at": j.get("date", "")[:16].replace("T", " "),
            "description": clean(j.get("description")),
            "tags": listy(j.get("tags")),
        })
    return out


def workingnomads(cfg, ctx):
    out = []
    for j in get("https://www.workingnomads.com/api/exposed_jobs/").json():
        out.append({
            "source": "workingnomads",
            "url": j["url"],
            "title": j["title"],
            "company": j.get("company_name", ""),
            "location": j.get("location", ""),
            "posted_at": j.get("pub_date", "")[:16].replace("T", " "),
            "description": clean(j.get("description")),
            "tags": f"{j.get('category_name', '')}, {j.get('tags', '')}",
        })
    return out


def weworkremotely(cfg, ctx):
    out = []
    root = ET.fromstring(get("https://weworkremotely.com/remote-jobs.rss").content)
    for item in root.iter("item"):
        f = lambda tag: (item.findtext(tag) or "").strip()
        company, _, title = f("title").partition(": ")
        out.append({
            "source": "weworkremotely",
            "url": f("link"),
            "title": title or company,
            "company": company if title else "",
            "location": f("region"),
            "job_type": f("type"),
            "posted_at": parsedate_to_datetime(f("pubDate")).strftime("%Y-%m-%d %H:%M") if f("pubDate") else "",
            "description": clean(f("description")),
            "tags": f"{f('category')}, {f('skills')}",
        })
    return out


SOURCES = {
    "onlinejobs": onlinejobs,
    "himalayas": himalayas,
    "jobicy": jobicy,
    "remotive": remotive,
    "remoteok": remoteok,
    "weworkremotely": weworkremotely,
    "workingnomads": workingnomads,
}


def search_links(keywords):
    """One-click searches for sites that block automated fetching."""
    links = []
    for kw in keywords:
        q = quote_plus(kw)
        links.append({
            "keyword": kw,
            "OnlineJobs.ph": f"{OLJ_BASE}/jobseekers/jobsearch?jobkeyword={q}",
            "Indeed PH": f"https://ph.indeed.com/jobs?q={q}&l=Remote&fromage=7",
            "Indeed (worldwide)": f"https://www.indeed.com/jobs?q={q}+philippines&l=Remote&fromage=7",
            "LinkedIn": f"https://www.linkedin.com/jobs/search/?keywords={q}&location=Philippines&f_WT=2&f_TPR=r604800",
            "JobStreet": f"https://ph.jobstreet.com/{quote_plus(kw.replace(' ', '-'))}-jobs/remote",
            "Upwork": f"https://www.upwork.com/nx/search/jobs/?q={q}&sort=recency",
        })
    return links
