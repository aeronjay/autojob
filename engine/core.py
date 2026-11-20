"""Shared glue: load config, run all sources, store + score."""
import tomllib
from datetime import date, timedelta
from pathlib import Path

from . import db, scoring, sources

ROOT = Path(__file__).resolve().parent.parent


def load_config():
    with open(ROOT / "config.toml", "rb") as f:
        return tomllib.load(f)


def tracking(cfg):
    """[tracking] settings with defaults, so older config.toml files keep working."""
    return {"follow_up_days": 5, "ghost_days": 21, **cfg.get("tracking", {})}


def ensure_scored(log=print):
    """After an upgrade, fill in the columns that scoring produces (pay estimates etc.)."""
    conn = db.connect()
    if db.get_meta(conn, "scored_version") != str(db.VERSION):
        log("Updating scores and pay estimates for existing jobs (one time)...")
        scoring.rescore_all(conn, load_config())
        db.set_meta(conn, "scored_version", str(db.VERSION))
    conn.close()


def fetch_all(log=print):
    cfg = load_config()
    conn = db.connect()
    db.set_meta(conn, "last_fetch", db.now())
    known = {r[0] for r in conn.execute("SELECT url FROM jobs")}
    ctx = {
        "search": list(dict.fromkeys(t for track in cfg["tracks"].values() for t in track.get("search", []))),
        "seen": known.__contains__,
        "cutoff": (date.today() - timedelta(days=cfg["scoring"].get("max_age_days", 14))).isoformat(),
    }
    summary = []
    for name, fn in sources.SOURCES.items():
        scfg = cfg["sources"].get(name, {})
        if not scfg.get("enabled", True):
            continue
        warnings = []
        ctx["warn"] = lambda msg, name=name, w=warnings: (w.append(msg), log(f"  {name:<15} warning: {msg}"))
        log(f"  {name:<15} searching...")
        try:
            # The same job turns up under several search terms; keep one copy.
            jobs = list({j["url"]: j for j in fn(scfg, ctx) if j.get("url") and j.get("title")}.values())
            new = db.insert_jobs(conn, jobs)
            summary.append((name, len(jobs), new, "; ".join(warnings) or None))
            log(f"  {name:<15} {len(jobs):>4} found, {new:>4} new")
        except Exception as e:  # one broken source shouldn't stop the others
            summary.append((name, 0, 0, str(e)))
            log(f"  {name:<15} FAILED: {e}")
    scoring.rescore_all(conn, cfg)
    db.set_meta(conn, "scored_version", str(db.VERSION))
    conn.close()
    return summary
