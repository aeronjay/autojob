"""Keyword scoring + location eligibility. Deterministic and free (no AI calls)."""
import re
from functools import lru_cache


@lru_cache(maxsize=None)
def pattern(word):
    # Word boundaries so "java" doesn't match "javascript" and "ai" doesn't match "maintain".
    return re.compile(r"(?<![a-z0-9])" + re.escape(word.lower()) + r"(?![a-z0-9])")


def has(word, text):
    return bool(pattern(word).search(text))


def eligibility(job, loc_cfg):
    """yes = open to PH/worldwide, no = restricted elsewhere, unknown = can't tell."""
    loc = (job["location"] or "").lower().strip()
    body = (job["description"] or "").lower()
    if job["source"] == "onlinejobs":
        return "yes"
    if any(p in body for p in loc_cfg["blocked_phrases"]):
        return "no"
    if any(has(ok, loc) for ok in loc_cfg["ok"]):
        return "yes"
    if loc in ("", "remote", "remote job"):
        return "unknown"
    return "no"  # names specific countries/regions that aren't ours


def score_job(job, cfg):
    s = cfg["scoring"]
    title = (job["title"] or "").lower()
    body = f"{job['description'] or ''} {job['tags'] or ''}".lower()

    best_track, best = None, 0
    for name, track in cfg["tracks"].items():
        terms = dict.fromkeys(track.get("search", []) + track.get("keywords", []))
        pts = sum(s["title_weight"] if has(kw, title) else s["body_weight"] if has(kw, body) else 0
                  for kw in terms)
        if pts > best:
            best_track, best = name, pts

    eligible = eligibility(job, cfg["location"])
    score = best
    if eligible == "yes" and best > 0:  # the bonus only boosts jobs that match a track
        score += s["eligible_bonus"]
    if any(w in title for w in s["demote_title"]):
        score -= s["demote_points"]
    hidden = int(any(w in title for w in s["exclude_title"]))
    return {"track": best_track, "score": score, "eligible": eligible, "hidden": hidden}


def rescore_all(conn, cfg):
    rows = conn.execute("SELECT * FROM jobs").fetchall()
    for row in rows:
        r = score_job(row, cfg)
        conn.execute("UPDATE jobs SET track=?, score=?, eligible=?, hidden=? WHERE id=?",
                     (r["track"], r["score"], r["eligible"], r["hidden"], row["id"]))
    conn.commit()
    return len(rows)
