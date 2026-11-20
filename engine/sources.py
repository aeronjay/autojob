"""Job source adapters. Each returns a list of dicts in one common shape:
source, url, title, company, location, salary, job_type, posted_at, description, tags
"""
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import date
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


# --- Indeed / LinkedIn via JobSpy (github.com/speedyapply/JobSpy) --------------------
# JobSpy reads Indeed through the API its mobile app uses, so it isn't blocked like page scraping.
# LinkedIn's public search is stricter: it blocks an IP after a few hundred quick requests.

def jobspy_search(site, cfg, ctx, keep=lambda r: True, source=None, terms=None, label="", **kw):
    try:
        from jobspy import scrape_jobs
    except ImportError:
        raise RuntimeError("JobSpy isn't installed. Run: pip install -r requirements.txt") from None
    hours_old = max(24, (date.today() - date.fromisoformat(ctx["cutoff"])).days * 24)
    out = []
    for term in terms or search_terms(cfg, ctx):
        df = scrape_jobs(site_name=[site], search_term=term, hours_old=hours_old, description_format="html",
                         results_wanted=cfg.get("results_wanted", 30), verbose=0, **kw)
        err = df.attrs.get("errors", {}).get(site)
        if err:
            ctx["warn"](f"{label}'{term}': {err}")
            if any(x in str(err).lower() for x in ("429", "blocked", "403")):
                ctx["warn"]("blocked for now; skipping the remaining searches")
                break
        out += [jobspy_job(source or site, r) for r in df.to_dict("records") if keep(r)]
        time.sleep(cfg.get("delay_seconds", 2))
    return out


def jobspy_job(site, r):
    def val(k):
        v = r.get(k)
        return None if v is None or v != v else v  # pandas uses NaN for missing numbers
    loc = val("location") or ""
    if isinstance(loc, dict):
        loc = ", ".join(str(x) for x in (loc.get("city"), loc.get("state"), loc.get("country")) if x)
    jt = val("job_type") or ""
    interval = val("interval")
    return {
        "source": site,
        "url": r["job_url"],
        "title": r["title"],
        "company": val("company") or "",
        "location": str(loc),
        "salary": money(val("min_amount"), val("max_amount"), str(getattr(interval, "value", interval) or ""),
                        val("currency") or "USD"),
        "job_type": listy([getattr(x, "name", x) for x in jt]) if isinstance(jt, list) else str(jt),
        "posted_at": str(val("date_posted") or "")[:10],
        "description": clean(val("description")),
        "tags": listy(val("skills")),
    }


def indeed(cfg, ctx):
    return jobspy_search("indeed", cfg, ctx, country_indeed=cfg.get("country", "philippines"), is_remote=True)


def indeed_abroad(cfg, ctx):
    """Indeed's sites in other countries, for abroad job types. Each country runs the first few search
    terms (the subject phrases), since single words like "math" bring back tutoring and everything else."""
    terms = search_terms(cfg, ctx)[:cfg.get("max_terms", 4)]
    out = []
    for country in cfg.get("countries", []):
        try:
            jobs = jobspy_search("indeed", cfg, ctx, source="indeed_abroad", terms=terms,
                                 label=f"{country}: ", country_indeed=country)
        except ValueError as e:  # a country name Indeed doesn't have
            ctx["warn"](f"{country}: {e}")
            continue
        for j in jobs:
            j["location"] = j["location"] or country.title()
        out += jobs
    return out


def linkedin(cfg, ctx):
    # JobSpy can't apply LinkedIn's remote filter. LinkedIn shows remote jobs with just the country as
    # their location and on-site / hybrid ones with a city, so keep country-only posts and ones that say remote.
    where = cfg.get("location", "Philippines")
    def remote(r):
        loc = r.get("location")
        loc = loc if isinstance(loc, str) else ""
        return bool(r.get("is_remote")) or loc.strip().lower() == where.lower()
    return jobspy_search("linkedin", cfg, ctx, keep=remote, location=where)


def linkedin_details(url):
    page = get(url).text
    # The post can contain its own divs, so read up to the "Show more" button that follows it.
    m = re.search(r'<div class="show-more-less-html__markup[^"]*"[^>]*>(.*?)<button', page, re.S)
    if not m:
        raise RuntimeError("LinkedIn didn't show the post (it may want a login). Open the job link instead.")
    return clean(m.group(1))


# --- Teaching abroad ---------------------------------------------------------------

TA_BASE = "https://www.teachaway.com"
COUNTRIES = {"AE": "United Arab Emirates", "SA": "Saudi Arabia", "QA": "Qatar", "KW": "Kuwait", "OM": "Oman", "BH": "Bahrain",
             "CN": "China", "HK": "Hong Kong", "TW": "Taiwan", "JP": "Japan", "KR": "South Korea", "VN": "Vietnam",
             "TH": "Thailand", "MY": "Malaysia", "SG": "Singapore", "ID": "Indonesia", "KH": "Cambodia", "MN": "Mongolia",
             "US": "United States", "CA": "Canada", "GB": "United Kingdom", "IE": "Ireland", "AU": "Australia",
             "NZ": "New Zealand", "EG": "Egypt", "MA": "Morocco", "TR": "Turkey", "KZ": "Kazakhstan", "UZ": "Uzbekistan",
             "MX": "Mexico", "BR": "Brazil", "CO": "Colombia", "ES": "Spain", "IT": "Italy", "DE": "Germany", "PH": "Philippines"}


def teachaway(cfg, ctx):
    """Teach Away: international-school and government teaching jobs, most hiring from overseas."""
    out = []
    for subject in cfg.get("subjects", ["math"]):
        for page in range(1, cfg.get("max_pages", 3) + 1):
            url = f"{TA_BASE}/teaching-jobs-abroad/all-countries/all-positions/{subject}/any-level"
            try:
                jobs = parse_teachaway(get(url, params={"page": page} if page > 1 else None).text)
            except requests.RequestException as e:
                ctx["warn"](f"{subject} page {page}: {e}")
                break
            out += jobs
            time.sleep(cfg.get("delay_seconds", 2))
            if not keep_paging(jobs, 20, ctx, by_date=False):
                break
    return out


def parse_teachaway(page):
    # Each listing is a rendered card; its country code only appears in the page's embedded data,
    # in the same order as the cards.
    parts = re.split(r'<a class="text-xl font-bold[^"]*" href="(/teaching-jobs-abroad/[^"]+)">', page)
    cards = [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
    places = re.findall(r'"countryCode":"([A-Z]{2})","countryName":[^,]*,"locality":"([^"]*)"', page.replace('\\"', '"'))
    jobs = []
    for n, (href, card) in enumerate(cards):
        card = re.sub(r"<(svg|script)[^>]*>.*?</\1>", "", card, flags=re.S)
        texts = [t for t in (html.unescape(x).strip() for x in re.split(r"<[^>]+>", card)) if t]
        if "View Details" in texts:
            texts = texts[:texts.index("View Details")]
        if not texts:
            continue
        title, school = texts[0], texts[1] if len(texts) > 1 else ""
        locality = texts[2] if len(texts) > 2 else ""
        country = ""
        if len(places) == len(cards):
            code, locality = places[n][0], places[n][1] or locality
            country = COUNTRIES.get(code, code)
        location = ", ".join(x for x in (locality, country) if x)
        details = texts[3:]
        jobs.append({
            "source": "teachaway",
            "url": TA_BASE + href,
            "title": title,
            "company": school,
            "location": location,
            "description": "\n".join([f"School: {school}", f"Location: {location}", *details]),
            "posted_at": "",
        })
    return jobs


SEEK_BASE = "https://www.seekteachers.com"


def seekteachers(cfg, ctx):
    """Seek Teachers: international schools (China, Middle East, Asia), newest first."""
    out = []
    for cat in cfg.get("categories", [919]):
        for page in range(1, cfg.get("max_pages", 4) + 1):
            params = {"category_id": cat, **({"page": page} if page > 1 else {})}
            try:
                jobs = parse_seek(get(f"{SEEK_BASE}/jobs.asp", params=params).text)
            except requests.RequestException as e:
                ctx["warn"](f"category {cat} page {page}: {e}")
                break
            out += jobs
            time.sleep(cfg.get("delay_seconds", 2))
            if not keep_paging(jobs, 20, ctx, by_date=False):
                break
    return out


def parse_seek(page):
    jobs = []
    for card in page.split('<div class="titlebar-listing clearfix"')[1:]:
        link = re.search(r'href="(https://www\.seekteachers\.com/job-detail\.asp\?job_id=\d+)">\s*<span[^>]*>(.*?)</span>(.*?)</a>', card, re.S)
        if not link:
            continue
        where = clean(link.group(3))
        location = where.split(" in ", 1)[1] if " in " in where else where
        blurb = re.search(r'<div class="margin-top">(.*?)</div>', card, re.S)
        start = re.search(r"Start Date:</span>\s*<b>(.*?)</b>", card, re.S)
        salary = re.search(r"<span><b>(.*?)</b>\s*</span>", card, re.S)
        salary = clean(salary.group(1)) if salary else ""
        jobs.append({
            "source": "seekteachers",
            "url": link.group(1),
            "title": clean(link.group(2)),
            "company": "",
            "location": location,
            "job_type": where.split(" in ", 1)[0] if " in " in where else "",
            "salary": "" if "negotiable" in salary.lower() else salary,
            "description": "\n".join(x for x in (clean(blurb.group(1)) if blurb else "",
                                                 f"Start date: {clean(start.group(1))}" if start else "",
                                                 f"Salary: {salary}" if salary else "") if x),
            "posted_at": "",
        })
    return jobs


def jobposting_details(url):
    """Full post from a page's schema.org JobPosting data (Teach Away and many school sites)."""
    page = get(url).text
    for raw in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "JobPosting":
            extra = []
            addr = (d.get("jobLocation") or {}).get("address") or {}
            if isinstance(addr, dict) and addr.get("addressCountry"):
                extra.append(f"Location: {', '.join(x for x in (addr.get('addressLocality'), addr.get('addressCountry')) if x)}")
            edu = (d.get("educationRequirements") or {})
            if isinstance(edu, dict) and edu.get("credentialCategory"):
                extra.append(f"Education required: {edu['credentialCategory']}")
            exp = (d.get("experienceRequirements") or {})
            if isinstance(exp, dict) and exp.get("monthsOfExperience"):
                extra.append(f"Experience required: {exp['monthsOfExperience']} months")
            return clean(d.get("description")) + ("\n\n" + "\n".join(extra) if extra else "")
    raise RuntimeError("Couldn't read the full job post from that page. Open the job link instead.")


def seek_details(url):
    page = get(url).text
    i = page.find("Job Description")
    if i < 0:
        raise RuntimeError("Couldn't read the full job post from that page. Open the job link instead.")
    text = clean(re.sub(r"<!--|-->", " ", page[i:i + 40000]))
    for end in ("Apply Now", "Apply for this job", "Similar Jobs", "Share this job", "Country Info"):
        if end in text:
            text = text[:text.index(end)]
    text = re.sub(r"\n\s*(Save|Print)\s*(?=\n|$)", "", text.replace("Job Description", "", 2))
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:12000]


SOURCES = {
    "onlinejobs": onlinejobs,
    "himalayas": himalayas,
    "indeed": indeed,
    "linkedin": linkedin,
    "jobicy": jobicy,
    "remotive": remotive,
    "remoteok": remoteok,
    "weworkremotely": weworkremotely,
    "workingnomads": workingnomads,
    "teachaway": teachaway,
    "seekteachers": seekteachers,
    "indeed_abroad": indeed_abroad,
}

# What each site is, for the dashboard. kind: which job types it serves.
INFO = {
    "onlinejobs": {"label": "OnlineJobs.ph", "kind": "remote", "note": "The biggest board for Filipino VAs. Searches your job types' terms."},
    "himalayas": {"label": "Himalayas", "kind": "remote", "note": "Remote jobs open to the Philippines. Searches your job types' terms."},
    "indeed": {"label": "Indeed PH", "kind": "remote", "note": "Work-from-home jobs on Indeed Philippines, via JobSpy. Searches your job types' terms."},
    "linkedin": {"label": "LinkedIn", "kind": "remote", "note": "Remote jobs in the Philippines, via JobSpy. LinkedIn blocks heavy use for a while, so it's off by default."},
    "jobicy": {"label": "Jobicy", "kind": "remote", "note": "Remote jobs, APAC and worldwide."},
    "remotive": {"label": "Remotive", "kind": "remote", "note": "Remote jobs, mostly tech and support."},
    "remoteok": {"label": "RemoteOK", "kind": "remote", "note": "Remote jobs, mostly tech."},
    "weworkremotely": {"label": "We Work Remotely", "kind": "remote", "note": "Remote jobs, many US-only."},
    "workingnomads": {"label": "Working Nomads", "kind": "remote", "note": "Remote jobs, mixed."},
    "teachaway": {"label": "Teach Away", "kind": "abroad", "note": "International schools hiring teachers from overseas (Middle East, Asia, US J-1)."},
    "seekteachers": {"label": "Seek Teachers", "kind": "abroad", "note": "International schools in China, the Middle East and Asia."},
    "indeed_abroad": {"label": "Indeed (abroad)", "kind": "abroad", "note": "Indeed in the countries listed in config.toml (Spain, Italy, France, Australia, New Zealand, Canada), via JobSpy."},
}

# Sites whose search results are only a preview; the full post is read when you ask Claude.
DETAILS = {"onlinejobs": olj_details, "teachaway": jobposting_details, "seekteachers": seek_details,
           "linkedin": linkedin_details}
# For these, new posts are read in full while fetching: visa / relocation details only appear there.
DETAILS_ON_FETCH = {"teachaway", "seekteachers"}


# --- One-click searches for sites that block automated fetching ----------------------

def remote_links(kw):
    q = quote_plus(kw)
    return {
        "OnlineJobs.ph": f"{OLJ_BASE}/jobseekers/jobsearch?jobkeyword={q}",
        "LinkedIn": f"https://www.linkedin.com/jobs/search/?keywords={q}&location=Philippines&f_WT=2&f_TPR=r604800",
        "Indeed PH": f"https://ph.indeed.com/jobs?q={q}&l=Remote&fromage=7",
        "JobStreet": f"https://ph.jobstreet.com/{quote_plus(kw.replace(' ', '-'))}-jobs/remote",
        "Upwork": f"https://www.upwork.com/nx/search/jobs/?q={q}&sort=recency",
        "Freelancer": f"https://www.freelancer.com/jobs/?keyword={q}",
        "PeoplePerHour": f"https://www.peopleperhour.com/freelance-jobs?q={q}",
        "Reddit r/forhire": f"https://www.reddit.com/r/forhire/search/?q=%5BHiring%5D+{q}&restrict_sr=1&sort=new",
        "Reddit r/buhaydigital": f"https://www.reddit.com/r/buhaydigital/search/?q={q}&restrict_sr=1&sort=new",
    }


def abroad_links(kw):
    q = quote_plus(kw)
    return {
        "TES": f"https://www.tes.com/jobs/search?keywords={q}",
        "LinkedIn": f"https://www.linkedin.com/jobs/search/?keywords={q}+visa+sponsorship&f_TPR=r2592000",
        "Indeed": f"https://www.indeed.com/jobs?q={q}+visa+sponsorship&fromage=30",
        "Reddit r/Internationalteachers": f"https://www.reddit.com/r/Internationalteachers/search/?q={q}&restrict_sr=1&sort=new",
    }


# Places to look that have no keyword search, or where a human has to check details.
RESOURCES = {
    "remote": [
        ("VirtualStaff.ph", "https://www.virtualstaff.ph/en-ph/find-jobs", "Filipino VA marketplace, no middleman fees"),
        ("Kalibrr (work from home)", "https://www.kalibrr.com/home/work_from_home/y/1", "Philippine job site, work-from-home roles"),
        ("Reddit r/buhaydigital", "https://www.reddit.com/r/buhaydigital/", "Filipino freelancers' community: hiring posts, agency reviews, which sites are legit"),
    ],
    "abroad": [
        ("Teach Away (math)", f"{TA_BASE}/teaching-jobs-abroad/all-countries/all-positions/math/any-level", "Fetched automatically too; check here for filters by country"),
        ("Seek Teachers", f"{SEEK_BASE}/jobs.asp?category_id=919", "Fetched automatically too; secondary school jobs"),
        ("Schrole", "https://www.schrole.com/", "International school jobs"),
        ("Search Associates", "https://www.searchassociates.com/", "International school recruitment (paid membership, job fairs)"),
        ("US J-1 teacher program", "https://j1visa.state.gov/programs/teacher", "Official US State Dept page: apply through a designated sponsor, never pay a random agent"),
        ("DMW approved job orders", "https://dmw.gov.ph/approved-job-orders", "Philippine government list of legitimate overseas job orders and licensed agencies"),
    ],
}


def search_links(tracks):
    """Per job type: one-click searches for its first few search terms on the sites that block bots."""
    out = []
    for name, t in tracks.items():
        build = abroad_links if t["kind"] == "abroad" else remote_links
        out.append({"track": name, "label": t["label"], "kind": t["kind"],
                    # A list of pairs, not a dict: JSON would sort the keys and lose the priority order.
                    "searches": [{"keyword": kw, "links": list(build(kw).items())} for kw in t["search"][:4]]})
    kinds = {t["kind"] for t in tracks.values()}
    resources = [{"name": n, "url": u, "note": note} for k in ("remote", "abroad") if k in kinds for n, u, note in RESOURCES[k]]
    return {"tracks": out, "resources": resources}
