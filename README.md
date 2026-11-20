# autojob

Finds jobs you can actually apply to from the Philippines (remote VA, e-commerce, executive assistant, research, dev… or teaching jobs **abroad with visa sponsorship**), ranks them by how well they match the job types *you* pick, has Claude write a tailored reply (plus a note on the job) when you ask, and tracks every application from sent to offer. **You** review and click send, so your OnlineJobs.ph and Indeed accounts stay safe.

## Setup (once)

```bash
pip install -r requirements.txt
copy .env.example .env        # optional: pick CLAUDE_MODEL
```

Replies come from the [Claude Code](https://claude.com/claude-code) CLI (`claude -p`) using your own Claude login, so install it and run `claude` once to sign in. No API key needed.

Then start the dashboard (`python autojob.py serve` or double-click `run.bat`). The first time, it asks **what jobs you're looking for**: switch on the job types you want (or add your own), click **Save and continue**, and pick what to fetch.

Then **fill in your profile** (⚙ Settings → My profile, or the yellow bar): your experience, tools, availability, links and rates. Claude only uses facts from it, so the better it is, the better your replies. It's saved as `profile.md` (created from `profile.example.md`) and is yours alone: it isn't committed to git.

### Sharing autojob with friends

Each person runs their own copy with their own Claude login. Their job types, sites and ranking choices are saved in their own `data/jobs.db`, and their profile in their own `profile.md`, so nothing of yours goes with the code. Send them the folder **without** `data/`, `profile.md` and `.env` (all three are git-ignored, so cloning the repo does this for you).

## Daily use

```bash
python autojob.py serve    # opens the dashboard at http://127.0.0.1:5000
python autojob.py fetch    # optional: fetch from the terminal with your saved choices
```

Click **Fetch new jobs** (or press `F`): tick the job types and sites you want this time. Fewer of each makes a faster fetch, and your picks are remembered.

The dashboard has four views: **Inbox**, **Saved**, **Applications** and **Skipped**. The list is on the left, the job you clicked is on the right.

### Applying (Inbox)

1. Click a job and read the post. The green pill is the pay converted to **USD per month** so jobs can be compared. Click **why?** next to the score to see exactly how it was ranked.
2. **Ask Claude** (optionally with an instruction like "short version" or "mention Shopify") writes the reply and **Claude's note**: fit verdict, what the job really needs, which experience it used, and flags (missing skills or licences, `[PLACEHOLDERS]` to fill in, hidden instructions, AI traps, red flags). Always read the note. Takes ~15–30 s, and you can keep browsing while it writes. For jobs abroad, Claude writes a short formal cover letter instead of a casual reply.
3. Edit the reply (it autosaves), click **Copy reply & open**, paste it on the site and send.
4. **Mark applied**. The job moves to Applications and the next job opens. Wrong click? The toast has **Undo**.

Filters: job type, source, **Min pay** (hides jobs whose stated pay is lower; jobs that don't state pay stay) and sort by best match, newest or highest pay. Keyboard: `J`/`K` next/previous, `O` open, `G` ask Claude, `C` copy, `A` applied, `S` save, `X` skip, `/` search, `F` fetch.

Found a job somewhere else (LinkedIn, Indeed, a referral)? **+ Add job** puts it in the same tracker; paste the post and Claude can write the reply for it too. **Search links** gives one-click searches for your job types on sites that block bots.

### Tracking (Applications)

Every application has a **stage**: Applied → Replied → Interview → Offer, or Rejected / No response. Click the stage when something happens.

- **Follow-ups.** An application with no reply is flagged after 5 days. Open it, click **Write a follow-up message** (Claude writes a short one from `followup.md`), send it, then **I followed up**. Or snooze it, or pick your own date.
- **Next steps.** For Replied / Interview, set the "Next step on" date (an interview, a test task) and it shows under **Needs action** that day.
- **Needs action** (the red number on the tab) lists everything due today or overdue.
- With no job open, the right side shows your numbers: applications per week, reply rate, and reply rate **by pay, job type and source**, so you can see which kind of job actually answers you. One click closes applications that got no reply after 21 days.
- Notes and a timeline are saved per job. **Export CSV** gives you the whole tracker for Excel.

## Job types and ranking

⚙ **Settings → Job types** lists ready-made job types: Automation / AI VA, Tech / Lead Gen VA, Executive Assistant, E-commerce Assistant, Product Researcher, Software Dev, General / Admin VA, Customer Support, Social Media / Content, Writing, Graphic Design / Video, Bookkeeping, and two **abroad** types (Math Teacher, Teacher any subject). Switch on the ones you want, **Edit** their search terms and keywords, or **+ Add your own**.

- **Search terms** are typed into OnlineJobs.ph and Himalayas (each one is a search) and count most for ranking.
- **Keywords** only affect ranking (tools, tasks).

How a job is scored (also shown per job under **why?**, and in Settings → Ranking):

1. Each job type checks the job: a search term or keyword in the **title** is worth 4 points, only in the **description** 1. The best-matching job type wins.
2. **+6** if you can apply: open to the Philippines / worldwide (remote), or offers **visa sponsorship / relocation** (abroad).
3. **+4** for stated pay of $1,200+/month, **−4** under $500/month. No pay stated: no change.
4. **−5** for senior titles (switch off in Settings → Ranking if you're experienced).
5. **+3** for posts from the last 2 days, while they're new.

Jobs restricted to other countries (remote) or that rule out sponsorship (abroad) are hidden; tick "show low-score & restricted" to see everything. Pay figures are estimates: hourly rates count as full-time (160 h/month), and foreign currencies (PHP, AED, SAR, THB, CNY, VND…) are converted at rough rates in `engine/pay.py`.

The built-in defaults live in `config.toml` (job types, scoring weights, location and visa phrases, site settings). Settings in the dashboard are stored per person and override it.

## Sources

| Source | Job types | How |
|---|---|---|
| OnlineJobs.ph | remote | one search per search term, newest first, 3 s between requests; stops paging at jobs it already has. Full post fetched when you ask Claude |
| Himalayas | remote | API search per search term, filtered to jobs open to the Philippines |
| Indeed PH | remote | [JobSpy](https://github.com/speedyapply/JobSpy) search per search term (it uses Indeed's app API, so it isn't blocked); work-from-home jobs only, with full posts and pay |
| LinkedIn | remote | JobSpy, **off by default**: LinkedIn blocks an IP for a while after a few dozen quick searches. Keeps posts listed as Philippines-wide (remote) rather than a city. Full post read when you ask Claude |
| Jobicy, Remotive, RemoteOK, We Work Remotely, Working Nomads | remote | APIs / RSS. Only jobs matching your job types are saved |
| Teach Away | abroad | international schools' teaching jobs by subject (`subjects` in `config.toml`); each new post is read in full to find visa/relocation details |
| Seek Teachers | abroad | international schools in China, the Middle East and Asia (secondary by default) |
| Indeed (abroad) | abroad | JobSpy search of Indeed in each country in `countries` (default Spain, Italy, France, Australia, New Zealand, Canada), first 4 search terms per country. Saves only posts mentioning visa sponsorship / relocation (`only_visa`), since most are local hires |
| JobStreet, Upwork, Freelancer, PeoplePerHour, Reddit (r/forhire, r/buhaydigital, r/Internationalteachers), TES (plus LinkedIn and Indeed with their own filters) | **search links only** | They block bots or ban auto-appliers. **Search links** builds one-click searches from your job types |

**Teaching abroad, a caution:** schools almost always need a teaching licence (PRC LPT) and often 2+ years of experience, and Claude's note flags when a post asks for something your profile doesn't have. Legitimate schools and DMW-licensed agencies don't charge teachers placement fees; check agencies on [DMW's approved job orders](https://dmw.gov.ph/approved-job-orders), and for the US J-1 route apply only through a [State Department-designated sponsor](https://j1visa.state.gov/programs/teacher).

## Claude usage

Each reply or follow-up is one `claude -p` call and counts toward your Claude plan's usage limits. Replies are only generated on click. `CLAUDE_MODEL` in `.env` picks the model (`sonnet` by default; `haiku` is lighter on limits, `opus` writes best). The instructions Claude follows live in `prompt.md` (follow-ups: `followup.md`); `{profile}`, `{track}`, `{extra}` and `{job}` get filled in automatically.

## Your data

Everything lives in `data/jobs.db` (SQLite), including your Settings. When an update changes the database format, the old file is first copied to `data/jobs.backup-v<N>.db`.
