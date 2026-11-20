"""Keyword scoring + location eligibility + pay. Deterministic and free (no AI calls)."""
import re
from functools import lru_cache

from . import pay


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
    if job["source"] == "onlinejobs" or job["manual"]:  # jobs you added yourself are ones you can apply to
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
    pay_cfg = cfg.get("pay", {})
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

    # Pay: well-paid jobs move up, jobs whose stated pay is low move down. Unstated pay is neutral.
    pay_min, pay_max = pay.parse(job["salary"], job["source"], pay_cfg)
    if pay_max is not None and best > 0:
        mid = (pay_min + pay_max) / 2
        if mid >= pay_cfg.get("good_usd_month", 1200):
            score += pay_cfg.get("good_bonus", 4)
        elif mid < pay_cfg.get("low_usd_month", 500):
            score -= pay_cfg.get("low_penalty", 4)

    hidden = int(any(w in title for w in s["exclude_title"]))
    return {"track": best_track, "score": score, "eligible": eligible, "hidden": hidden,
            "pay_min": pay_min, "pay_max": pay_max}


def rescore_all(conn, cfg):
    rows = conn.execute("SELECT * FROM jobs").fetchall()
    conn.executemany(
        "UPDATE jobs SET track=:track, score=:score, eligible=:eligible, hidden=:hidden, "
        "pay_min=:pay_min, pay_max=:pay_max WHERE id=:id",
        [{**score_job(row, cfg), "id": row["id"]} for row in rows])
    conn.commit()
    return len(rows)
