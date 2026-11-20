"""Keyword scoring + location / visa eligibility + pay. Deterministic and free (no AI calls).

How a job is ranked (the dashboard's "Why this score?" shows the same breakdown):
  1. Every enabled job type scores the job: title_weight points per search term or keyword found in
     the title, body_weight per term found only in the description. The best-scoring type wins.
  2. Remote job types: +eligible_bonus if the job is open to the Philippines / worldwide.
     Abroad job types: +eligible_bonus if the post offers visa sponsorship or relocation.
  3. Senior titles (demote_title) lose demote_points.
  4. Stated pay at/above good_usd_month earns good_bonus; below low_usd_month loses low_penalty.
  5. In the dashboard, posts from the last fresh_days get fresh_bonus while they're new.
"""
import re
from functools import lru_cache

from . import pay, sources


@lru_cache(maxsize=None)
def pattern(word):
    # Word boundaries so "java" doesn't match "javascript" and "ai" doesn't match "maintain".
    return re.compile(r"(?<![a-z0-9])" + re.escape(word.lower()) + r"(?![a-z0-9])")


def has(word, text):
    # A plain substring test is far faster and rules out most words before the regex runs.
    return word.lower() in text and bool(pattern(word).search(text))


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


def sponsorship(job, cfg):
    """'yes' if the post offers visa sponsorship / relocation, 'no' if it rules it out, '' if silent."""
    a = cfg.get("abroad", {})
    text = f"{job['title'] or ''} {job['description'] or ''} {job['tags'] or ''}".lower()
    if any(p in text for p in a.get("no_sponsor", [])):
        return "no"
    if any(has(p, text) for p in a.get("sponsor", [])):
        return "yes"
    return ""


def best_track(job, tracks, s):
    """(track name, points, title hits, body hits) for the job type that matches best."""
    title = (job["title"] or "").lower()
    body = f"{job['description'] or ''} {job['tags'] or ''}".lower()
    best = (None, 0, [], [])
    for name, track in tracks.items():
        in_title, in_body = [], []
        for kw in dict.fromkeys(track.get("search", []) + track.get("keywords", [])):
            if has(kw, title):
                in_title.append(kw)
            elif has(kw, body):
                in_body.append(kw)
        # Abroad job types share generic words ("secondary", "IB"), so the subject itself
        # (one of the search terms, e.g. "math teacher") has to appear somewhere.
        if track.get("kind") == "abroad" and not set(track.get("search", [])) & set(in_title + in_body):
            continue
        pts = s["title_weight"] * len(in_title) + s["body_weight"] * len(in_body)
        if pts > best[1]:
            best = (name, pts, in_title, in_body)
    return best


def tracks_for(job, tracks):
    """A remote board's jobs only compete among remote job types, a teaching-abroad site's among abroad
    ones. Jobs added by hand can match any."""
    info = sources.INFO.get(job["source"])
    if not info or job["manual"]:
        return tracks
    return {k: t for k, t in tracks.items() if t.get("kind", "remote") == info["kind"]}


def as_row(j):
    """A freshly fetched job dict, shaped like a database row for scoring."""
    return {"title": "", "description": "", "tags": "", "location": "", "source": "", "salary": "", "manual": 0, **j}


def matches(job, cfg):
    """Does a freshly fetched job match any of cfg's job types at all?"""
    job = as_row(job)
    return best_track(job, tracks_for(job, cfg["tracks"]), cfg["scoring"])[0] is not None


def score_job(job, cfg, explain=False):
    s = cfg["scoring"]
    pay_cfg = cfg.get("pay", {})
    title = (job["title"] or "").lower()
    why = []

    track_name, best, in_title, in_body = best_track(job, tracks_for(job, cfg["tracks"]), s)
    track = cfg["tracks"].get(track_name) or {}
    abroad = track.get("kind") == "abroad"
    if track_name:
        if in_title:
            why.append((s["title_weight"] * len(in_title), f"{track['label']}: in the title: {', '.join(in_title)}"))
        if in_body:
            why.append((s["body_weight"] * len(in_body), f"{track['label']}: in the description: {', '.join(in_body)}"))
    else:
        why.append((0, "Matches none of your job types"))

    visa = sponsorship(job, cfg)
    if abroad:
        eligible = {"yes": "yes", "no": "no"}.get(visa, "unknown")
    else:
        eligible = eligibility(job, cfg["location"])
    score = best
    if eligible == "yes" and best > 0:  # the bonus only boosts jobs that match a track
        score += s["eligible_bonus"]
        why.append((s["eligible_bonus"], "Mentions visa sponsorship / relocation" if abroad else "Open to applicants in the Philippines"))
    elif eligible == "no":
        why.append((0, "Rules out visa sponsorship (hidden)" if abroad else "Restricted to other countries (hidden)"))
    elif best > 0:
        why.append((0, "Visa sponsorship not mentioned" if abroad else "Location unclear"))
    senior = next((w for w in s["demote_title"] if w in title), None)
    if senior:
        score -= s["demote_points"]
        why.append((-s["demote_points"], f"Senior title (\"{senior.strip()}\")"))

    # Pay: well-paid jobs move up, jobs whose stated pay is low move down. Unstated pay is neutral.
    pay_min, pay_max = pay.parse(job["salary"], job["source"], pay_cfg)
    if pay_max is not None and best > 0:
        mid = (pay_min + pay_max) / 2
        if mid >= pay_cfg.get("good_usd_month", 1200):
            score += pay_cfg.get("good_bonus", 4)
            why.append((pay_cfg.get("good_bonus", 4), f"Good pay (≈${round(mid):,}/mo)"))
        elif mid < pay_cfg.get("low_usd_month", 500):
            score -= pay_cfg.get("low_penalty", 4)
            why.append((-pay_cfg.get("low_penalty", 4), f"Low pay (≈${round(mid):,}/mo)"))

    excluded = None if abroad else next((w for w in s["exclude_title"] if w in title), None)
    if excluded:
        why.append((0, f"Title contains \"{excluded}\" (hidden)"))
    out = {"track": track_name, "score": score, "eligible": eligible, "hidden": int(bool(excluded)),
           "pay_min": pay_min, "pay_max": pay_max, "visa": int(visa == "yes")}
    if explain:
        out["why"] = [{"points": p, "text": t} for p, t in why]
    return out


def rescore_all(conn, cfg):
    rows = conn.execute("SELECT * FROM jobs").fetchall()
    conn.executemany(
        "UPDATE jobs SET track=:track, score=:score, eligible=:eligible, hidden=:hidden, "
        "pay_min=:pay_min, pay_max=:pay_max, visa=:visa WHERE id=:id",
        [{**score_job(row, cfg), "id": row["id"]} for row in rows])
    conn.commit()
    return len(rows)
