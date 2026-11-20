"""SQLite storage: one row per job, deduped by URL. Doubles as the application tracker."""
import hashlib
import shutil
import sqlite3
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "jobs.db"
VERSION = 2  # bump when the schema changes; connect() upgrades older databases

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    url         TEXT NOT NULL,
    title       TEXT NOT NULL,
    company     TEXT,
    location    TEXT,
    salary      TEXT,
    job_type    TEXT,
    posted_at   TEXT,
    description TEXT,
    tags        TEXT,
    track       TEXT,
    score       INTEGER DEFAULT 0,
    eligible    TEXT DEFAULT 'unknown',   -- yes / no / unknown
    hidden      INTEGER DEFAULT 0,        -- excluded by title rules
    status      TEXT DEFAULT 'new',       -- new / saved / applied / skipped
    draft       TEXT,                     -- Claude's reply (editable)
    detailed    INTEGER DEFAULT 0,        -- 1 once the full post has been fetched
    notes       TEXT,
    first_seen  TEXT NOT NULL,
    applied_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS events (       -- per-job timeline: applied, stage changes, follow-ups
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id  TEXT NOT NULL,
    at      TEXT NOT NULL,
    text    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id);
"""

# Columns added after v1, applied to old databases with ALTER TABLE.
ADDED_COLUMNS = {
    "note": "TEXT",                 # Claude's note about the job and its reply
    "stage": "TEXT",                # applied / replied / interview / offer / rejected / ghosted
    "due_on": "TEXT",               # YYYY-MM-DD of the next action (follow-up, interview...)
    "followups": "INTEGER DEFAULT 0",
    "followup_draft": "TEXT",       # Claude's follow-up message (editable)
    "pay_min": "INTEGER",           # estimated USD per month, see pay.py
    "pay_max": "INTEGER",
    "manual": "INTEGER DEFAULT 0",  # 1 = added by hand (Indeed, LinkedIn, referrals...)
}

# Which "new" jobs belong in the inbox: relevant, applicable, and not stale.
INBOX_FILTER = ("hidden=0 AND eligible<>'no' AND score>=? AND first_seen>=? "
                "AND (posted_at='' OR substr(posted_at,1,10)>=?)")


def inbox_args(cfg):
    days = cfg["scoring"].get("max_age_days", 14)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [cfg["scoring"]["min_score"], cutoff.isoformat(timespec="seconds"), cutoff.date().isoformat()]


def get_meta(conn, key):
    r = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r[0] if r else None


def set_meta(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))
    conn.commit()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_local():
    return datetime.now().isoformat(timespec="minutes")


def days_from_today(n):
    return (date.today() + timedelta(days=n)).isoformat()


def job_id(url, title="", company=""):
    key = (url or f"{title}|{company}").strip().lower().rstrip("/")
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def add_event(conn, jid, text):
    conn.execute("INSERT INTO events (job_id, at, text) VALUES (?,?,?)", (jid, now_local(), text))


def connect():
    DB_PATH.parent.mkdir(exist_ok=True)
    existed = DB_PATH.exists()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < VERSION:
        if existed:
            conn.close()
            backup = DB_PATH.with_name(f"jobs.backup-v{version}.db")
            if not backup.exists():  # keep a copy of the data as it was before upgrading
                shutil.copy2(DB_PATH, backup)
            conn = sqlite3.connect(DB_PATH, timeout=30)
            conn.row_factory = sqlite3.Row
        upgrade(conn)
    return conn


def upgrade(conn):
    conn.executescript(SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    for name, decl in ADDED_COLUMNS.items():
        if name not in have:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {decl}")
    # Applications made before the tracker existed: start them at "applied", follow-up due 5 days later.
    conn.execute("""INSERT INTO events (job_id, at, text)
                    SELECT id, applied_at, 'Applied' FROM jobs WHERE status='applied' AND stage IS NULL""")
    conn.execute("""UPDATE jobs SET stage='applied', due_on=date(substr(applied_at,1,10), '+5 days')
                    WHERE status='applied' AND stage IS NULL""")
    # Some old rows kept RSS-style dates ("Fri, 23 Oct 2026 ..."), which break date comparisons.
    for jid, posted in conn.execute("SELECT id, posted_at FROM jobs WHERE posted_at GLOB '[A-Za-z]*'").fetchall():
        try:
            fixed = parsedate_to_datetime(posted).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            fixed = ""
        conn.execute("UPDATE jobs SET posted_at=? WHERE id=?", (fixed, jid))
    conn.execute(f"PRAGMA user_version={VERSION}")
    conn.commit()
    conn.execute("PRAGMA journal_mode=WAL")  # lets the dashboard keep working while a fetch writes


def insert_jobs(conn, jobs):
    """Insert new jobs; returns how many were actually new."""
    new = 0
    for j in jobs:
        jid = job_id(j["url"], j["title"], j.get("company", ""))
        # The same posting often appears on several boards under different URLs.
        if j.get("company") and conn.execute(
            "SELECT 1 FROM jobs WHERE lower(title)=lower(?) AND lower(company)=lower(?) AND id<>?",
            (j["title"], j["company"], jid),
        ).fetchone():
            continue
        cur = conn.execute(
            """INSERT OR IGNORE INTO jobs
               (id, source, url, title, company, location, salary, job_type, posted_at, description, tags,
                first_seen, manual)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (jid, j["source"], j["url"], j["title"], j.get("company", ""), j.get("location", ""),
             j.get("salary", ""), j.get("job_type", ""), j.get("posted_at", ""),
             j.get("description", ""), j.get("tags", ""), now(), int(j.get("manual", 0))),
        )
        new += cur.rowcount
    conn.commit()
    return new
