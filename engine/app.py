"""Local dashboard: browse scored jobs, get Claude's replies, track applications through to an offer."""
import csv
import io
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, request, send_file

from . import core, db, drafting, scoring, sources

app = Flask(__name__)
INDEX = Path(__file__).resolve().parent / "index.html"
STATUSES = {"new": "Inbox", "saved": "Saved", "applied": "Applications", "skipped": "Skipped"}
STAGES = {"applied": "Applied", "replied": "Replied", "interview": "Interview", "offer": "Offer",
          "rejected": "Rejected", "ghosted": "No response"}
WAITING = ("applied", "replied", "interview")  # stages where a next action can be due
# List rows leave out the long text fields; the detail endpoint returns everything.
LIGHT = ("id, source, url, title, company, location, salary, job_type, posted_at, track, score, eligible, "
         "status, stage, due_on, followups, pay_min, pay_max, first_seen, applied_at, manual, visa, "
         "(COALESCE(draft,'')<>'') AS has_draft, (COALESCE(notes,'')<>'') AS has_notes")
DUE = "status='applied' AND stage IN ('applied','replied','interview') AND due_on IS NOT NULL AND due_on<=?"
MANUAL_SOURCES = {"linkedin.": "linkedin", "indeed.": "indeed", "upwork.": "upwork", "jobstreet.": "jobstreet",
                  "onlinejobs.ph": "onlinejobs"}


def today():
    return date.today().isoformat()


def stale_before(cfg):
    """Applications still at 'applied' from before this date have probably gone nowhere."""
    return (date.today() - timedelta(days=core.tracking(cfg)["ghost_days"])).isoformat()


@app.get("/")
def index():
    return send_file(INDEX)


def pay_filter(bands):
    """Pay ranges picked in the list's Pay filter: "none" (pay not stated) or "lo-hi" USD/month,
    hi optional ("3000-" = 3,000 and up). A job falls in the range its midpoint is in."""
    conds, args = [], []
    for b in bands:
        if b == "none":
            conds.append("pay_max IS NULL")
            continue
        lo, _, hi = b.partition("-")
        if not lo.isdigit() or (hi and not hi.isdigit()):
            continue
        c = "pay_max IS NOT NULL AND (pay_min+pay_max)/2.0>=?"
        args.append(int(lo))
        if hi:
            c += " AND (pay_min+pay_max)/2.0<?"
            args.append(int(hi))
        conds.append(f"({c})")
    return (f" AND ({' OR '.join(conds)})", args) if conds else ("", [])


@app.get("/api/jobs")
def jobs():
    cfg = core.load_config()
    a = request.args
    status = a.get("status", "new")
    s = cfg["scoring"]
    # "rank" = score plus a boost for very fresh posts: early applicants get read.
    fresh = (datetime.now(timezone.utc) - timedelta(days=s.get("fresh_days", 2))).strftime("%Y-%m-%d %H:%M")
    posted = "CASE WHEN posted_at<>'' THEN posted_at ELSE replace(substr(first_seen,1,16),'T',' ') END"
    sql = f"SELECT {LIGHT}, score + CASE WHEN {posted}>=? THEN ? ELSE 0 END AS rank FROM jobs WHERE status=?"
    args = [fresh, s.get("fresh_bonus", 3), status]
    # Score/location/age filters only apply to the inbox; tracked jobs always show.
    if status == "new" and a.get("all") != "1":
        sql += f" AND {db.INBOX_FILTER}"
        args += db.inbox_args(cfg)
    # Each filter can pick several values (?track=a&track=b); none picked = no filter.
    for col in ("track", "source"):
        picked = [v for v in a.getlist(col) if v]
        if picked:
            sql += f" AND {col} IN ({','.join('?' * len(picked))})"
            args += picked
    if status != "applied":
        sql_pay, pay_args = pay_filter(a.getlist("pay"))
        sql += sql_pay
        args += pay_args
    if a.get("q"):
        sql += " AND (title LIKE ? OR company LIKE ? OR description LIKE ? OR notes LIKE ?)"
        args += [f"%{a['q']}%"] * 4
    if status == "applied":
        if a.get("stage") == "due":
            sql += f" AND {DUE}"
            args.append(today())
        elif a.get("stage") in STAGES:
            sql += " AND stage=?"
            args.append(a["stage"])
        order = "(stage IN ('applied','replied','interview') AND due_on IS NOT NULL AND due_on<=?) DESC, applied_at DESC"
        args.append(today())
    else:
        order = {"newest": f"{posted} DESC", "pay": "pay_max IS NULL, pay_max DESC, rank DESC"}.get(
            a.get("sort"), "rank DESC, first_seen DESC")

    conn = db.connect()
    rows = conn.execute(f"{sql} ORDER BY {order}", args).fetchall()
    counts = dict(conn.execute("SELECT status, COUNT(*) FROM jobs WHERE status<>'new' GROUP BY status").fetchall())
    counts["new"] = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE status='new' AND {db.INBOX_FILTER}",
                                 db.inbox_args(cfg)).fetchone()[0]
    stage_counts = dict(conn.execute("SELECT stage, COUNT(*) FROM jobs WHERE status='applied' GROUP BY stage").fetchall())
    stage_counts["due"] = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {DUE}", (today(),)).fetchone()[0]
    last_fetch = db.get_meta(conn, "last_fetch")
    sources_ = [r[0] for r in conn.execute("SELECT DISTINCT source FROM jobs ORDER BY 1")]
    conn.close()
    limit = 400
    return jsonify(jobs=[dict(r) for r in rows[:limit]], total=len(rows), counts=counts, stage_counts=stage_counts,
                   sources=sources_, tracks={k: v["label"] for k, v in cfg["tracks"].items()},
                   track_kinds={k: v["kind"] for k, v in cfg["catalog"].items()},
                   track_labels={k: v["label"] for k, v in cfg["catalog"].items()},
                   source_names={k: v["label"] for k, v in sources.INFO.items()},
                   stages=list(STAGES.items()), last_fetch=last_fetch, today=today(),
                   follow_up_days=core.tracking(cfg)["follow_up_days"], profile_todos=drafting.profile_todos(),
                   setup_done=cfg["setup_done"])


@app.get("/api/jobs/<jid>")
def job(jid):
    conn = db.connect()
    r = conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if not r:
        conn.close()
        return jsonify(error="Job not found"), 404
    events = [dict(e) for e in conn.execute("SELECT at, text FROM events WHERE job_id=? ORDER BY id DESC", (jid,))]
    conn.close()
    return jsonify(job=dict(r), events=events, why=why(r))


def why(job):
    """The score breakdown shown under "Why this score?"."""
    cfg = core.load_config()
    out = scoring.score_job(job, cfg, explain=True)["why"]
    s = cfg["scoring"]
    posted = job["posted_at"] or (job["first_seen"] or "")[:16].replace("T", " ")
    fresh = (datetime.now(timezone.utc) - timedelta(days=s.get("fresh_days", 2))).strftime("%Y-%m-%d %H:%M")
    if job["status"] == "new" and posted >= fresh:
        out.append({"points": s.get("fresh_bonus", 3), "text": f"Posted in the last {s.get('fresh_days', 2)} days (early applicants get read)"})
    return out


@app.post("/api/jobs")
def add():
    """Add a job by hand: something found on LinkedIn/Indeed, a referral, a direct email..."""
    b = request.get_json(silent=True) or {}
    title, url = (b.get("title") or "").strip(), (b.get("url") or "").strip()
    if not title:
        return jsonify(error="A job title is required."), 400
    if url and urlparse(url).scheme not in ("http", "https"):
        return jsonify(error="The link must start with http:// or https://"), 400
    status = b.get("status") if b.get("status") in ("saved", "applied") else "saved"
    host = urlparse(url).netloc.lower()
    source = next((name for part, name in MANUAL_SOURCES.items() if part in host), "manual")
    company = (b.get("company") or "").strip()
    jid = db.job_id(url, title, company)
    conn = db.connect()
    created = db.insert_jobs(conn, [{
        "source": source, "url": url, "title": title, "company": company, "manual": 1,
        "location": (b.get("location") or "").strip(), "salary": (b.get("salary") or "").strip(),
        "description": (b.get("description") or "").strip(),
        "posted_at": "",
    }])
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if not row:  # same title + company already tracked under another link
        row = conn.execute("SELECT * FROM jobs WHERE lower(title)=lower(?) AND lower(company)=lower(?)",
                           (title, company)).fetchone()
        jid = row["id"]
    if created:
        r = scoring.score_job(row, core.load_config())
        conn.execute("UPDATE jobs SET track=:track, score=:score, eligible=:eligible, hidden=:hidden, "
                     "pay_min=:pay_min, pay_max=:pay_max, visa=:visa, detailed=1 WHERE id=:id", {**r, "id": jid})
        db.add_event(conn, jid, "Added by hand")
    conn.commit()
    conn.close()
    change(jid, {"status": status})
    return jsonify(id=jid, status=status, existed=not created)


def change(jid, body):
    """Apply a status / stage / follow-up / text change to one job and log it on the timeline."""
    cfg = core.load_config()
    follow_up_days = core.tracking(cfg)["follow_up_days"]
    conn = db.connect()
    job = conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if not job:
        conn.close()
        return False
    sets = {}
    status = body.get("status")
    if status in STATUSES and status != job["status"]:
        sets["status"] = status
        if status == "applied":
            sets.update(stage="applied", applied_at=db.now_local(), due_on=db.days_from_today(follow_up_days), followups=0)
            db.add_event(conn, jid, "Applied")
        else:
            if job["status"] == "applied":  # taken back out of the tracker
                sets.update(stage=None, applied_at=None, due_on=None, followups=0)
            db.add_event(conn, jid, f"Moved to {STATUSES[status]}")
    is_applied = sets.get("status", job["status"]) == "applied"
    stage = body.get("stage")
    if stage in STAGES and is_applied and stage != sets.get("stage", job["stage"]):
        sets["stage"] = stage
        # Waiting on them again -> schedule a follow-up. Anything else: you decide the next date.
        sets["due_on"] = db.days_from_today(follow_up_days) if stage == "applied" else None
        db.add_event(conn, jid, f"Stage: {STAGES[stage]}")
    if body.get("followed_up") and is_applied:
        sets["followups"] = (job["followups"] or 0) + 1
        sets["due_on"] = db.days_from_today(follow_up_days + 2)
        db.add_event(conn, jid, f"Followed up (#{sets['followups']})")
    if isinstance(body.get("snooze"), int) and is_applied:
        sets["due_on"] = db.days_from_today(body["snooze"])
    if "due_on" in body and is_applied:
        sets["due_on"] = body["due_on"] or None
    for field in ("notes", "draft", "followup_draft"):
        if field in body:
            sets[field] = body[field]
    if sets:
        conn.execute(f"UPDATE jobs SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", [*sets.values(), jid])
    conn.commit()
    conn.close()
    return True


@app.post("/api/jobs/<jid>")
def update(jid):
    if not change(jid, request.get_json(silent=True) or {}):
        return jsonify(error="Job not found"), 404
    return jsonify(ok=True)


@app.post("/api/jobs/<jid>/draft")
def draft(jid):
    """Claude writes the application reply, or (kind=followup) a follow-up message."""
    body = request.get_json(silent=True) or {}
    conn = db.connect()
    get_job = lambda: conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    try:
        drafting.claude_bin()  # fail fast before fetching anything
        job = get_job()
        if not job:
            return jsonify(error="Job not found"), 404
        cfg = core.load_config()
        if job["source"] in sources.DETAILS and not job["detailed"]:
            conn.execute("UPDATE jobs SET description=?, detailed=1 WHERE id=?",
                         (sources.DETAILS[job["source"]](job["url"]), jid))
            # The full post can change the ranking (visa details, more keywords).
            conn.execute("UPDATE jobs SET track=:track, score=:score, eligible=:eligible, hidden=:hidden, "
                         "pay_min=:pay_min, pay_max=:pay_max, visa=:visa WHERE id=:id",
                         {**scoring.score_job(get_job(), cfg), "id": jid})
            conn.commit()
            job = get_job()
        track = cfg["catalog"].get(job["track"])
        if body.get("kind") == "followup":
            days = (date.today() - date.fromisoformat(job["applied_at"][:10])).days if job["applied_at"] else 0
            text = drafting.followup(job, days, body.get("extra", ""), track)
            conn.execute("UPDATE jobs SET followup_draft=? WHERE id=?", (text, jid))
            conn.commit()
            return jsonify(followup_draft=text, description=job["description"])
        reply, note = drafting.generate(job, body.get("extra", ""), track)
        conn.execute("UPDATE jobs SET draft=?, note=? WHERE id=?", (reply, note, jid))
        conn.commit()
        return jsonify(draft=reply, note=note, description=job["description"])
    except Exception as e:
        return jsonify(error=str(e)), 500
    finally:
        conn.close()


# --- Applications: numbers, clean-up, export --------------------------------

def pay_band(lo, hi):
    if hi is None:
        return "Pay not stated"
    mid = (lo + hi) / 2
    return "Under $500/mo" if mid < 500 else "$500–999/mo" if mid < 1000 else "$1,000–1,999/mo" if mid < 2000 else "$2,000+/mo"


@app.get("/api/stats")
def stats():
    cfg = core.load_config()
    conn = db.connect()
    rows = conn.execute("SELECT source, track, stage, applied_at, pay_min, pay_max FROM jobs WHERE status='applied'").fetchall()
    due = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {DUE}", (today(),)).fetchone()[0]
    conn.close()
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    labels = {k: v["label"] for k, v in cfg["catalog"].items()}

    def breakdown(key):
        groups = {}
        for r in rows:
            g = groups.setdefault(key(r), {"applied": 0, "heard": 0, "positive": 0})
            g["applied"] += 1
            g["heard"] += r["stage"] in ("replied", "interview", "offer", "rejected")
            g["positive"] += r["stage"] in ("replied", "interview", "offer")
        return [{"name": k, **v} for k, v in sorted(groups.items(), key=lambda kv: -kv[1]["applied"])]

    mids = sorted((r["pay_min"] + r["pay_max"]) / 2 for r in rows if r["pay_max"] is not None)
    return jsonify(
        total=len(rows),
        week=sum((r["applied_at"] or "")[:10] > week_ago for r in rows),
        stages={s: sum(r["stage"] == s for r in rows) for s in STAGES},
        positive=sum(r["stage"] in ("replied", "interview", "offer") for r in rows),
        due=due,
        stale=sum(r["stage"] == "applied" and (r["applied_at"] or "9")[:10] < stale_before(cfg) for r in rows),
        ghost_days=core.tracking(cfg)["ghost_days"],
        median_pay=round(mids[len(mids) // 2]) if mids else None,
        by_track=breakdown(lambda r: labels.get(r["track"], "Other")),
        by_source=breakdown(lambda r: r["source"]),
        by_pay=breakdown(lambda r: pay_band(r["pay_min"], r["pay_max"])),
    )


@app.post("/api/applications/close-stale")
def close_stale():
    """Mark applications with no reply after [tracking] ghost_days as 'No response'."""
    conn = db.connect()
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM jobs WHERE status='applied' AND stage='applied' AND substr(applied_at,1,10)<?",
        (stale_before(core.load_config()),))]
    for jid in ids:
        db.add_event(conn, jid, f"Stage: {STAGES['ghosted']}")
    conn.executemany("UPDATE jobs SET stage='ghosted', due_on=NULL WHERE id=?", [(i,) for i in ids])
    conn.commit()
    conn.close()
    return jsonify(closed=len(ids))


@app.get("/api/export.csv")
def export():
    cols = ["title", "company", "source", "url", "salary", "pay_min", "pay_max", "track", "stage",
            "applied_at", "due_on", "followups", "notes"]
    conn = db.connect()
    rows = conn.execute(f"SELECT {', '.join(cols)} FROM jobs WHERE status='applied' ORDER BY applied_at DESC").fetchall()
    conn.close()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(cols)
    w.writerows([list(r) for r in rows])
    return Response("﻿" + out.getvalue(), mimetype="text/csv",  # BOM so Excel reads it as UTF-8
                    headers={"Content-Disposition": f"attachment; filename=applications-{today()}.csv"})


# --- Fetching runs in the background so the dashboard stays usable -----------

FETCH = {"running": False, "log": [], "summary": None, "error": None}


def run_fetch(tracks, source_names):
    def log(msg):
        print(msg)
        FETCH["log"].append(msg.strip())
    try:
        FETCH["summary"] = [{"source": s, "found": f, "new": n, "error": e}
                            for s, f, n, e in core.fetch_all(log, tracks, source_names)]
    except Exception as e:
        FETCH["error"] = str(e)
    finally:
        FETCH["running"] = False


@app.post("/api/fetch")
def fetch():
    """Body: {"tracks": [...], "sources": [...]} limits the run; missing = every enabled one."""
    b = request.get_json(silent=True) or {}
    tracks = b.get("tracks") if isinstance(b.get("tracks"), list) else None
    source_names = b.get("sources") if isinstance(b.get("sources"), list) else None
    if tracks is not None and not tracks:
        return jsonify(error="Pick at least one job type."), 400
    if source_names is not None and not source_names:
        return jsonify(error="Pick at least one site."), 400
    if tracks is not None and source_names is not None:
        core.save_fetch_choice(tracks, source_names)
    if not FETCH["running"]:
        FETCH.update(running=True, log=[], summary=None, error=None)
        threading.Thread(target=run_fetch, args=(tracks, source_names), daemon=True).start()
    return fetch_status()


@app.get("/api/fetch")
def fetch_status():
    return jsonify(running=FETCH["running"], last=FETCH["log"][-1] if FETCH["log"] else "",
                   summary=FETCH["summary"], error=FETCH["error"])


@app.get("/api/links")
def links():
    return jsonify(sources.search_links(core.load_config()["tracks"]))


# --- Settings: job types, sites, ranking, profile ------------------------------

@app.get("/api/settings")
def get_settings():
    cfg = core.load_config()
    defaults = core.load_defaults()
    tracks = [{"id": k, **{f: t.get(f) for f in ("label", "kind", "search", "keywords", "enabled", "custom")},
               "default": ({"label": k, "kind": "remote", "search": [], "keywords": [], **defaults["tracks"][k]}
                           if k in defaults.get("tracks", {}) else None)}
              for k, t in cfg["catalog"].items()]
    srcs = [{"id": k, **info, "enabled": cfg["sources"].get(k, {}).get("enabled", True)} for k, info in sources.INFO.items()]
    s = cfg["scoring"]
    return jsonify(tracks=tracks, sources=srcs, setup_done=cfg["setup_done"], fetch=cfg["fetch_choice"],
                   scoring={"min_score": s["min_score"], "max_age_days": s.get("max_age_days", 14),
                            "demote_senior": bool(s["demote_title"])})


@app.post("/api/settings")
def post_settings():
    b = request.get_json(silent=True) or {}
    tracks = b.get("tracks") or {}
    if not any(isinstance(t, dict) and t.get("enabled") for t in tracks.values()):
        return jsonify(error="Turn on at least one job type."), 400
    for name, t in tracks.items():
        if isinstance(t, dict) and t.get("enabled") and not t.get("search"):
            return jsonify(error=f"“{t.get('label') or name}” needs at least one search term."), 400
    core.save_settings(b)
    return jsonify(ok=True)


@app.get("/api/profile")
def get_profile():
    return jsonify(text=drafting.read_profile(), todos=drafting.profile_todos())


@app.post("/api/profile")
def post_profile():
    text = (request.get_json(silent=True) or {}).get("text")
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="The profile can't be empty."), 400
    drafting.save_profile(text)
    return jsonify(ok=True, todos=drafting.profile_todos())
