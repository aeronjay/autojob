# autojob

Finds remote jobs you can actually apply to from the Philippines, scores them against your three tracks (Automation/AI VA, Specialized VA, Software Dev), ranks them by fit, pay and freshness, has Claude write a tailored reply (plus a note on the job) when you ask, and tracks every application from sent to offer. **You** review and click send, so your OnlineJobs.ph and Indeed accounts stay safe.

## Setup (once)

```bash
pip install -r requirements.txt
copy .env.example .env        # optional: pick CLAUDE_MODEL
```

Replies come from the [Claude Code](https://claude.com/claude-code) CLI (`claude -p`) using your Claude login, so install it and run `claude` once to sign in. No API key needed. Then **fill in `profile.md`**, especially your VA experience, tools, availability and rates. Claude only uses facts from that file.

The instructions Claude follows (structure, voice rules, what goes in the note) live in `prompt.md` (follow-up messages: `followup.md`). Edit it freely; `{profile}`, `{extra}` and `{job}` get filled in automatically.

## Daily use

```bash
python autojob.py fetch    # ~1–2 min, pulls new jobs from every source
python autojob.py serve    # opens the dashboard at http://127.0.0.1:5000
```

Or double-click `run.bat` (dashboard) / run `run.bat fetch`. The dashboard also has a **Fetch new jobs** button.

The dashboard has four views: **Inbox**, **Saved**, **Applications** and **Skipped**. The list is on the left, the job you clicked is on the right.

### Applying (Inbox)

1. Click a job and read the post. The green pill is the pay converted to **USD per month** so jobs can be compared.
2. **Ask Claude** (optionally with an instruction like "short version" or "mention Shopify") writes the reply and **Claude's note**: fit verdict, what the job really needs, which projects it used, and flags (missing skills, `[PLACEHOLDERS]` to fill in, hidden instructions, AI traps, red flags). Always read the note. Takes ~15–30 s, and you can keep browsing while it writes.
3. Edit the reply (it autosaves), click **Copy reply & open**, paste it on the site and send.
4. **Mark applied**. The job moves to Applications and the next job opens. Wrong click? The toast has **Undo**.

Filters: track, source, **Min pay** (hides jobs whose stated pay is lower; jobs that don't state pay stay) and sort by best match, newest or highest pay. Keyboard: `J`/`K` next/previous, `O` open, `G` ask Claude, `C` copy, `A` applied, `S` save, `X` skip, `/` search.

Found a job somewhere else (LinkedIn, Indeed, a referral)? **+ Add job** puts it in the same tracker; paste the post and Claude can write the reply for it too.

### Tracking (Applications)

Every application has a **stage**: Applied → Replied → Interview → Offer, or Rejected / No response. Click the stage when something happens.

- **Follow-ups.** An application with no reply is flagged after 5 days. Open it, click **Write a follow-up message** (Claude writes a short one from `followup.md`), send it, then **I followed up**. Or snooze it, or pick your own date.
- **Next steps.** For Replied / Interview, set the "Next step on" date (an interview, a test task) and it shows under **Needs action** that day.
- **Needs action** (the red number on the tab) lists everything due today or overdue.
- With no job open, the right side shows your numbers: applications per week, reply rate, and reply rate **by pay, track and source**, so you can see which kind of job actually answers you. One click closes applications that got no reply after 21 days.
- Notes and a timeline are saved per job. **Export CSV** gives you the whole tracker for Excel.

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

Ranking = keyword match + location + **pay** + **freshness**. `[pay]` sets what counts as good pay (default $1,200+/month: +4 points) and low pay (under $500/month: -4); posts from the last 2 days get +3 because early applicants get read. `[tracking]` sets the follow-up (5 days) and no-response (21 days) timings. Pay figures are estimates: hourly rates are counted as full-time (160 h/month), pesos are converted at the rate in `[pay.rates]`, and vague or per-piece pay is treated as not stated.

Fetch daily if you can. The first run (or one after a long break) pages deeper and takes ~5 min; jobs posted more than `max_age_days` (14) ago never show in the inbox.

Jobs marked **restricted** (US-only, EU-only, CET timezone…) are hidden by default. Tick "show low-score & restricted" to see everything.

## Claude usage

Each reply or follow-up is one `claude -p` call and counts toward your Claude plan's usage limits. Replies are only generated on click. `CLAUDE_MODEL` in `.env` picks the model (`sonnet` by default; `haiku` is lighter on limits, `opus` writes best).

## Your data

Everything lives in `data/jobs.db` (SQLite). When an update changes the database format, the old file is first copied to `data/jobs.backup-v<N>.db`.
