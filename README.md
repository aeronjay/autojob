# autojob

Finds jobs you can actually apply to from the Philippines (remote VA, e-commerce, executive assistant, research, dev… or teaching jobs **abroad with visa sponsorship**). It ranks them by how well they match the job types *you* pick, has Claude write a tailored reply (plus a note on the job) when you ask, and tracks every application from sent to offer.

**You** review and click send. autojob never applies or logs in for you, so your OnlineJobs.ph, Indeed and LinkedIn accounts stay safe.

- Pulls jobs from OnlineJobs.ph, Indeed PH, Himalayas, LinkedIn, remote-job boards and teaching-abroad sites ([full list](#sources))
- Ranks them by your job types, whether you can apply from the Philippines (or get a visa), pay, and how fresh they are
- Writes replies and cover letters with Claude, using only facts from your profile
- Tracks applications with follow-up reminders and reply-rate stats
- Runs on your own computer; your data stays in a local file

---

## What you need

| | Windows | Mac |
|---|---|---|
| **Python 3.11 or newer** | [python.org/downloads](https://www.python.org/downloads/) | [python.org/downloads](https://www.python.org/downloads/) (or `brew install python`) |
| **Claude Code** (writes the replies) | see [step 3](#3-install-claude-code-and-sign-in) | see [step 3](#3-install-claude-code-and-sign-in) |
| **A Claude account** with Claude Code access (Pro or Max plan) | | |
| **Git** (optional, makes updating easy) | [git-scm.com](https://git-scm.com/download/win) | built in: run `git --version` once and accept the install prompt |

Finding and ranking jobs works without Claude. You only need it for **Ask Claude** (writing replies).

---

## Install

### 1. Install Python

<details open>
<summary><b>Windows</b></summary>

1. Download Python from [python.org/downloads](https://www.python.org/downloads/) and run the installer.
2. **Tick "Add python.exe to PATH"** on the first screen, then click **Install Now**.
3. Open **PowerShell** (Start menu → type "PowerShell") and check it worked:
   ```powershell
   python --version
   ```
   You should see `Python 3.11` or higher. If the Microsoft Store opens instead, reinstall Python with the PATH box ticked.

</details>

<details open>
<summary><b>Mac</b></summary>

1. Download Python from [python.org/downloads](https://www.python.org/downloads/) and run the installer (or `brew install python` if you use Homebrew).
2. Open **Terminal** (Spotlight → type "Terminal") and check it worked:
   ```bash
   python3 --version
   ```
   You should see `Python 3.11` or higher. On a Mac, always type `python3`, not `python`.

</details>

### 2. Download autojob and install its packages

**With Git:**

```bash
git clone https://github.com/<your-username>/autojob.git
cd autojob
```

**Without Git:** on the GitHub page click **Code → Download ZIP**, unzip it somewhere you'll find again (e.g. Documents), then open PowerShell / Terminal in that folder:
- Windows: open the folder in File Explorer, click the address bar, type `powershell` and press Enter.
- Mac: right-click the folder in Finder → **New Terminal at Folder** (or type `cd ` in Terminal and drag the folder onto the window).

Then create a private Python environment for autojob and install what it needs:

<details open>
<summary><b>Windows (PowerShell)</b></summary>

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
```

</details>

<details open>
<summary><b>Mac (Terminal)</b></summary>

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

</details>

The `.venv` folder keeps autojob's packages separate from the rest of your computer. The launchers in step 4 use it automatically.

### 3. Install Claude Code and sign in

autojob writes replies by running the [Claude Code](https://docs.claude.com/en/docs/claude-code/setup) command-line tool with **your own Claude login**. You don't need an API key.

<details open>
<summary><b>Windows (PowerShell)</b></summary>

```powershell
irm https://claude.ai/install.ps1 | iex
```

</details>

<details open>
<summary><b>Mac (Terminal)</b></summary>

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

</details>

Then **close and reopen** PowerShell / Terminal, run `claude`, and follow the sign-in steps in your browser. Once you see Claude's prompt you can exit it (type `/exit`). If an install command fails, use the current instructions in the [Claude Code setup docs](https://docs.claude.com/en/docs/claude-code/setup).

### 4. Start autojob

| | Double-click | Or from PowerShell / Terminal, in the autojob folder |
|---|---|---|
| **Windows** | `run.bat` | `.venv\Scripts\python autojob.py serve` |
| **Mac** | `run.command` | `.venv/bin/python autojob.py serve` |

Your browser opens the dashboard at **http://127.0.0.1:5000** (Windows) or **http://127.0.0.1:5050** (Mac). Leave the black window open while you use it, and close it to stop autojob. The dashboard is only reachable from your own computer.

> **Mac, first double-click:** if macOS says `run.command` "can't be opened because it is from an unidentified developer", right-click it → **Open** → **Open**. You only need to do this once. If it says you don't have permission, run `chmod +x run.command` in the autojob folder.

### 5. First-time setup in the dashboard

1. **Pick what jobs you want.** The first screen lists job types (Automation / AI VA, Executive Assistant, E-commerce, Software Dev, Math Teacher abroad, and more). Switch on the ones you want, edit their search terms, or add your own. Click **Save and continue**.
2. **Fetch jobs.** Tick the job types and sites, then click **Fetch**. The first fetch takes a few minutes; later ones are quicker because sites stop at jobs you already have.
3. **Fill in your profile** (⚙ Settings → My profile, or the yellow bar): your experience, tools, availability, links and rates. Claude only uses facts from it, so the better it is, the better your replies. It's saved as `profile.md` on your computer.

---

## Daily use

Start autojob (step 4), click **Fetch new jobs** (or press `F`), and work through the Inbox. Fewer job types and sites per fetch makes it faster, and your picks are remembered.

To fetch without opening the dashboard (for example from a scheduled task), run `run.bat fetch` on Windows, `./run.command fetch` on a Mac, or `python autojob.py fetch` inside the virtual environment.

The dashboard has four views: **Inbox**, **Saved**, **Applications** and **Skipped**. The list is on the left, the job you clicked is on the right.

### Applying (Inbox)

1. Click a job and read the post. The green pill is the pay converted to **USD per month** so jobs can be compared. Click **why?** next to the score to see exactly how it was ranked.
2. **Ask Claude** (optionally with an instruction like "short version" or "mention Shopify") writes the reply and **Claude's note**: fit verdict, what the job really needs, which experience it used, and flags (missing skills or licences, `[PLACEHOLDERS]` to fill in, hidden instructions, AI traps, red flags). Always read the note. It takes about 15–30 seconds, and you can keep browsing while it writes. For jobs abroad, Claude writes a short formal cover letter instead of a casual reply.
3. Edit the reply (it autosaves), click **Copy reply & open**, paste it on the site and send.
4. **Mark applied**. The job moves to Applications and the next job opens. Wrong click? The toast has **Undo**.

Filters: job type, source, **Min pay** (hides jobs whose stated pay is lower; jobs that don't state pay stay) and sort by best match, newest or highest pay.

Keyboard: `J`/`K` next/previous, `O` open, `G` ask Claude, `C` copy, `A` applied, `S` save, `X` skip, `/` search, `F` fetch.

Found a job somewhere else (Upwork, JobStreet, a referral)? **+ Add job** puts it in the same tracker; paste the post and Claude can write the reply for it too. **Search links** gives one-click searches for your job types on sites that block bots.

### Tracking (Applications)

Every application has a **stage**: Applied → Replied → Interview → Offer, or Rejected / No response. Click the stage when something happens.

- **Follow-ups.** An application with no reply is flagged after 5 days. Open it, click **Write a follow-up message** (Claude writes a short one from `followup.md`), send it, then **I followed up**. Or snooze it, or pick your own date.
- **Next steps.** For Replied / Interview, set the "Next step on" date (an interview, a test task) and it shows under **Needs action** that day.
- **Needs action** (the red number on the tab) lists everything due today or overdue.
- With no job open, the right side shows your numbers: applications per week, reply rate, and reply rate **by pay, job type and source**, so you can see which kind of job actually answers you. One click closes applications that got no reply after 21 days.
- Notes and a timeline are saved per job. **Export CSV** gives you the whole tracker for Excel or Numbers.

---

## Job types and ranking

⚙ **Settings → Job types** lists ready-made job types: Automation / AI VA, Tech / Lead Gen VA, Executive Assistant, E-commerce Assistant, Product Researcher, Software Dev, General / Admin VA, Customer Support, Social Media / Content, Writing, Graphic Design / Video, Bookkeeping, and two **abroad** types (Math Teacher, Teacher any subject). Switch on the ones you want, **Edit** their search terms and keywords, or **+ Add your own**.

- **Search terms** are typed into the sites' search boxes (each one is a search) and count most for ranking.
- **Keywords** only affect ranking (tools, tasks).

How a job is scored (also shown per job under **why?**, and in Settings → Ranking):

1. Each job type checks the job: a search term or keyword in the **title** is worth 4 points, only in the **description** 1. The best-matching job type wins.
2. **+6** if you can apply: open to the Philippines / worldwide (remote), or offers **visa sponsorship / relocation** (abroad).
3. **+4** for stated pay of $1,200+/month, **−4** under $500/month. No pay stated: no change.
4. **−5** for senior titles (switch off in Settings → Ranking if you're experienced).
5. **+3** for posts from the last 2 days, while they're new.

Jobs restricted to other countries (remote) or that rule out sponsorship (abroad) are hidden; tick "show low-score & restricted" to see everything. Pay figures are estimates: hourly rates count as full-time (160 h/month), and foreign currencies (PHP, EUR, AUD, CAD, AED, CNY…) are converted at rough rates in `engine/pay.py`.

The built-in defaults live in `config.toml` (job types, scoring weights, location and visa phrases, site settings). Settings in the dashboard are stored per person and override it.

---

## Sources

| Source | Job types | How |
|---|---|---|
| OnlineJobs.ph | remote | one search per search term, newest first, 3 s between requests; stops paging at jobs it already has. Full post fetched when you ask Claude |
| Indeed PH | remote | [JobSpy](https://github.com/speedyapply/JobSpy) search per search term (it uses Indeed's app API, so it isn't blocked); work-from-home jobs only, with full posts and pay |
| Himalayas | remote | API search per search term, filtered to jobs open to the Philippines |
| LinkedIn | remote | JobSpy, **off by default**: LinkedIn blocks an IP for a while after a few dozen quick searches. Keeps posts listed as Philippines-wide (remote) rather than a city. Full post read when you ask Claude |
| Jobicy, Remotive, RemoteOK, We Work Remotely, Working Nomads | remote | APIs / RSS. Only jobs matching your job types are saved |
| Teach Away | abroad | international schools' teaching jobs by subject (`subjects` in `config.toml`); each new post is read in full to find visa/relocation details |
| Seek Teachers | abroad | international schools in China, the Middle East and Asia (secondary by default) |
| Indeed (abroad) | abroad | JobSpy search of Indeed in each country in `countries` (default Spain, Italy, France, Australia, New Zealand, Canada), first 4 search terms per country. Saves only posts mentioning visa sponsorship / relocation (`only_visa`), since most are local hires |
| JobStreet, Upwork, Freelancer, PeoplePerHour, Reddit (r/forhire, r/buhaydigital, r/Internationalteachers), TES (plus LinkedIn and Indeed with their own filters) | **search links only** | They block bots or ban auto-appliers. **Search links** builds one-click searches from your job types |

Switch sites on or off in ⚙ Settings → Sites. To search Indeed in other countries for teaching jobs, edit `countries` under `[sources.indeed_abroad]` in `config.toml` (e.g. `"uk"`, `"ireland"`, `"united arab emirates"`, `"china"`).

**Teaching abroad, a caution:** schools almost always need a teaching licence (PRC LPT) and often 2+ years of experience, and Claude's note flags when a post asks for something your profile doesn't have. Legitimate schools and DMW-licensed agencies don't charge teachers placement fees; check agencies on [DMW's approved job orders](https://dmw.gov.ph/approved-job-orders), and for the US J-1 route apply only through a [State Department-designated sponsor](https://j1visa.state.gov/programs/teacher).

---

## Settings file (`.env`)

| Setting | What it does |
|---|---|
| `CLAUDE_MODEL` | Which Claude model writes replies: `sonnet` (default), `haiku` (lighter on usage limits), `opus` (writes best) |
| `PORT` | Dashboard port. Default 5000 on Windows, 5050 on a Mac |

Each reply or follow-up is one `claude -p` call and counts toward your Claude plan's usage limits. Replies are only written when you click. The instructions Claude follows live in `prompt.md` (follow-ups: `followup.md`); `{profile}`, `{track}`, `{extra}` and `{job}` get filled in automatically.

---

## Updating

With Git, in the autojob folder:

| Windows | Mac |
|---|---|
| `git pull`<br>`.venv\Scripts\python -m pip install -r requirements.txt` | `git pull`<br>`.venv/bin/python -m pip install -r requirements.txt` |

Without Git, download the new ZIP and copy your `data` folder, `profile.md` and `.env` into it. Those hold all your jobs, settings and profile. Then run the install command from step 2 again.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `python` opens the Microsoft Store, or "python is not recognized" (Windows) | Reinstall Python and tick **Add python.exe to PATH** |
| `command not found: python` (Mac) | Use `python3` |
| `externally-managed-environment` when installing (Mac) | You ran pip outside the virtual environment. Use the `.venv/bin/python -m pip ...` command from step 2 |
| `No module named ...` / "JobSpy isn't installed" | Run the install command from step 2 again |
| Ask Claude says "The `claude` CLI was not found" | Install Claude Code (step 3), then close and reopen the window you start autojob from. Check with `claude --version` |
| Ask Claude fails with a login or usage error | Run `claude` in PowerShell / Terminal and sign in again, or wait for your plan's usage limit to reset |
| "Address already in use" / the page shows a 403 error | Another app is using the port. Set a different one in `.env`, e.g. `PORT=5055` |
| Mac: "run.command can't be opened" | Right-click → **Open** → **Open** (once). Permission error: `chmod +x run.command` |
| A site shows a warning or "FAILED" after a fetch | That site changed or blocked the request for now. The others still work; try again later. LinkedIn blocks for a few hours after heavy use |
| A site shows "skipped (no abroad job types chosen)" | Turn on an abroad job type in ⚙ Settings → Job types |

---

## Your data and sharing

Everything lives in `data/jobs.db` (SQLite) on your computer, including your Settings. When an update changes the database format, the old file is first copied to `data/jobs.backup-v<N>.db`.

Each person runs their own copy with their own Claude login. Their job types, sites and ranking choices are saved in their own `data/jobs.db`, and their profile in their own `profile.md`. `data/`, `profile.md` and `.env` are git-ignored, so nothing of yours goes to GitHub or to a friend who clones the repo.

Scraping job sites is against some sites' terms. autojob keeps request rates low and only reads public job listings, but use it for your own job search, not at scale.
