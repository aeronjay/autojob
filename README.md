# autojob

Finds remote jobs you can actually apply to from the Philippines, scores them against your three tracks (Automation/AI VA, Specialized VA, Software Dev), and drafts a tailored application with Gemini when you ask. **You** review and click send, so your OnlineJobs.ph and Indeed accounts stay safe.

## Setup (once)

```bash
pip install -r requirements.txt
copy .env.example .env        # then paste your Gemini key into .env
```

Get a free key at https://aistudio.google.com/apikey. Then **fill in `profile.md`**, especially your VA experience, tools, and a sample application that got replies. The AI only uses facts from that file.

## Daily use

```bash
python autojob.py fetch    # ~1–2 min, pulls new jobs from every source
python autojob.py serve    # opens the dashboard at http://127.0.0.1:5000
```

Or double-click `run.bat` (dashboard) / run `run.bat fetch`. The dashboard also has a **Fetch new jobs** button.

In the dashboard:
1. Click a job to expand it, then read the post.
2. **Draft application** writes a subject, message and a CHECKLIST of special instructions found in the post (code words, Loom requests, "apply via this link"…). Always read the checklist.
3. Edit the draft (it autosaves), copy it, click **Open job ↗** and apply on the site.
4. **Mark applied**. The Applied tab is your tracker, and notes are saved per job.

## Sources

| Source | How | Notes |
|---|---|---|
| OnlineJobs.ph | one search per track `search` term, newest first, 3 s between requests; stops paging once it reaches jobs it already has | All PH-friendly. Full post is fetched only when you draft |
| Himalayas | API search per track `search` term, filtered to jobs open to the Philippines, 2 s between requests | Best non-OLJ source. Rate-limits fast requests; the tool backs off and keeps partial results |
| Jobicy | API (APAC, Philippines, all) | |
| Remotive, RemoteOK, We Work Remotely, Working Nomads | APIs / RSS | Mostly dev/global, so location filter matters |
| Indeed, LinkedIn, JobStreet, Upwork | **search links only** | They block bots (Indeed returns 403) and ban auto-appliers |

## Tuning

Everything is in `config.toml`. Each track has `search` terms (what gets searched on OnlineJobs.ph and Himalayas; adding one adds a search) and `keywords` (extra scoring words). Also there: location rules, words that demote (e.g. "senior") or hide (e.g. "cold caller") a job, and `min_score`. After editing, run `python autojob.py rescore`.

Fetch daily if you can. The first run (or one after a long break) pages deeper and takes ~5 min; jobs posted more than `max_age_days` (14) ago never show in the inbox.

Jobs marked **restricted** (US-only, EU-only, CET timezone…) are hidden by default. Tick "show low-score & restricted" to see everything.

## Gemini quota

The free tier is small and changes often (Flash-Lite usually allows the most requests per day). Drafts are only generated on click. If you hit the limit, wait for the daily reset or change `GEMINI_MODEL` in `.env`. `python autojob.py models` lists what your key can use.
