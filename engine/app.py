"""Local dashboard: browse scored jobs, draft applications, track status."""
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_file

from . import core, db, drafting, sources

app = Flask(__name__)
INDEX = Path(__file__).resolve().parent / "index.html"
STATUSES = {"new", "saved", "applied", "skipped"}


def row(r):
    return dict(r)


@app.get("/")
def index():
    return send_file(INDEX)


@app.get("/api/jobs")
def jobs():
    cfg = core.load_config()
    a = request.args
    status = a.get("status", "new")
    sql, args = "SELECT * FROM jobs WHERE status=?", [status]
    # Score/location/age filters only apply to the New inbox; tracked jobs always show.
    if status == "new" and a.get("all") != "1":
        sql += f" AND {db.INBOX_FILTER}"
        args += db.inbox_args(cfg)
    if a.get("track"):
        sql += " AND track=?"
        args.append(a["track"])
    if a.get("source"):
        sql += " AND source=?"
        args.append(a["source"])
    if a.get("q"):
        sql += " AND (title LIKE ? OR company LIKE ? OR description LIKE ?)"
        args += [f"%{a['q']}%"] * 3
    order = "applied_at DESC" if a.get("status") == "applied" else "score DESC, first_seen DESC"
    conn = db.connect()
    rows = conn.execute(f"{sql} ORDER BY {order} LIMIT 300", args).fetchall()
    counts = dict(conn.execute("SELECT status, COUNT(*) FROM jobs WHERE status<>'new' GROUP BY status").fetchall())
    counts["new"] = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE status='new' AND {db.INBOX_FILTER}",
                                 db.inbox_args(cfg)).fetchone()[0]
    last_fetch = db.get_meta(conn, "last_fetch")
    sources_ = [r[0] for r in conn.execute("SELECT DISTINCT source FROM jobs ORDER BY 1")]
    conn.close()
    tracks = {k: v["label"] for k, v in cfg["tracks"].items()}
    return jsonify(jobs=[row(r) for r in rows], counts=counts, sources=sources_, tracks=tracks, last_fetch=last_fetch)


@app.post("/api/jobs/<jid>")
def update(jid):
    body = request.get_json()
    conn = db.connect()
    if body.get("status") in STATUSES:
        applied_at = datetime.now().isoformat(timespec="minutes") if body["status"] == "applied" else None
        conn.execute("UPDATE jobs SET status=?, applied_at=COALESCE(?, applied_at) WHERE id=?",
                     (body["status"], applied_at, jid))
    for field in ("notes", "draft"):
        if field in body:
            conn.execute(f"UPDATE jobs SET {field}=? WHERE id=?", (body[field], jid))
    conn.commit()
    conn.close()
    return jsonify(ok=True)


@app.post("/api/jobs/<jid>/draft")
def draft(jid):
    conn = db.connect()
    get_job = lambda: conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    try:
        drafting.api_key()  # fail fast before fetching anything
        job = get_job()
        if not job:
            return jsonify(error="Job not found"), 404
        if job["source"] == "onlinejobs" and not job["detailed"]:
            conn.execute("UPDATE jobs SET description=?, detailed=1 WHERE id=?",
                         (sources.olj_details(job["url"]), jid))
            conn.commit()
            job = get_job()
        text = drafting.generate(job)
        conn.execute("UPDATE jobs SET draft=? WHERE id=?", (text, jid))
        conn.commit()
        return jsonify(draft=text, description=job["description"])
    except Exception as e:
        return jsonify(error=str(e)), 500
    finally:
        conn.close()


@app.post("/api/fetch")
def fetch():
    summary = core.fetch_all()  # progress prints in the serve terminal
    return jsonify(summary=[{"source": s, "found": f, "new": n, "error": e} for s, f, n, e in summary])


@app.get("/api/links")
def links():
    return jsonify(sources.search_links(core.load_config()["links"]["keywords"]))
