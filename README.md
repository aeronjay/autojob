# autojob

Finds remote jobs you can actually apply to from the Philippines, scores them against your three tracks (Automation/AI VA, Specialized VA, Software Dev), and has Claude write a tailored reply (plus a note on the job) when you ask. **You** review and click send, so your OnlineJobs.ph and Indeed accounts stay safe.

## Setup (once)

```bash
pip install -r requirements.txt
copy .env.example .env        # optional: pick CLAUDE_MODEL
```

Replies come from the [Claude Code](https://claude.com/claude-code) CLI (`claude -p`) using your Claude login, so install it and run `claude` once to sign in. No API key needed. Then **fill in `profile.md`**, especially your VA experience, tools, availability and rates. Claude only uses facts from that file.

The instructions Claude follows (structure, voice rules, what goes in the note) live in `prompt.md`. Edit it freely; `{profile}`, `{extra}` and `{job}` get filled in automatically.

## Daily use

```bash
python autojob.py fetch    # ~1–2 min, pulls new jobs from every source
python autojob.py serve    # opens the dashboard at http://127.0.0.1:5000
```

Or double-click `run.bat` (dashboard) / run `run.bat fetch`. The dashboard also has a **Fetch new jobs** button.

In the dashboard:
1. Click a job to expand it, then read the post.
2. **Ask Claude** (optionally with an instruction like "short version" or "mention Shopify") writes the reply and **Claude's note**: fit verdict, what the job really needs, which projects it used, and flags (missing skills, `[PLACEHOLDERS]` to fill in, hidden instructions, AI traps, red flags). Always read the note. Takes ~15–30 s.
3. Edit the reply (it autosaves), copy it, click **Open job ↗** and apply on the site.
4. **Mark applied**. The Applied tab is your tracker, and notes are saved per job.

## Sources

| Source | How | Notes |
|---|---|---|
| OnlineJobs.ph | one search per track `search` term, newest first, 3 s between requests; stops paging once it reaches jobs it already has | All PH-friendly. Full post is fetched only when you ask Claude |
| Himalayas | API search per track `search` term, filtered to jobs open to the Philippines, 2 s between requests | Best non-OLJ source. Rate-limits fast requests; the tool backs off and keeps partial results |
| Jobicy | API (APAC, Philippines, all) | |
| Remotive, RemoteOK, We Work Remotely, Working Nomads | APIs / RSS | Mostly dev/global, so location filter matters |
| Indeed, LinkedIn, JobStreet, Upwork | **search links only** | They block bots (Indeed returns 403) and ban auto-appliers |

## Tuning

Everything is in `config.toml`. Each track has `search` terms (what gets searched on OnlineJobs.ph and Himalayas; adding one adds a search) and `keywords` (extra scoring words). Also there: location rules, words that demote (e.g. "senior") or hide (e.g. "cold caller") a job, and `min_score`. After editing, run `python autojob.py rescore`.

Fetch daily if you can. The first run (or one after a long break) pages deeper and takes ~5 min; jobs posted more than `max_age_days` (14) ago never show in the inbox.

Jobs marked **restricted** (US-only, EU-only, CET timezone…) are hidden by default. Tick "show low-score & restricted" to see everything.

## Claude usage

Each reply is one `claude -p` call and counts toward your Claude plan's usage limits. Replies are only generated on click. `CLAUDE_MODEL` in `.env` picks the model (`sonnet` by default; `haiku` is lighter on limits, `opus` writes best).
