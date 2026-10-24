"""SQLite storage: one row per job, deduped by URL. Doubles as the application tracker."""
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "jobs.db"

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
    draft       TEXT,
    detailed    INTEGER DEFAULT 0,        -- 1 once the full post has been fetched
    notes       TEXT,
    first_seen  TEXT NOT NULL,
    applied_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

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


def job_id(url, title="", company=""):
    key = (url or f"{title}|{company}").strip().lower().rstrip("/")
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def connect():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


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
               (id, source, url, title, company, location, salary, job_type, posted_at, description, tags, first_seen)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (jid, j["source"], j["url"], j["title"], j.get("company", ""), j.get("location", ""),
             j.get("salary", ""), j.get("job_type", ""), j.get("posted_at", ""),
             j.get("description", ""), j.get("tags", ""), now()),
        )
        new += cur.rowcount
    conn.commit()
    return new
