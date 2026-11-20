"""Shared glue: load config (+ each person's saved settings), run the sources, store + score."""
import json
import time
import tomllib
from datetime import date, timedelta
from pathlib import Path

from . import db, scoring, sources

ROOT = Path(__file__).resolve().parent.parent
TRACK_FIELDS = ("label", "kind", "search", "keywords")


def load_defaults():
    with open(ROOT / "config.toml", "rb") as f:
        return tomllib.load(f)


def get_settings(conn=None):
    """What this person chose in the dashboard's Settings (None until they save once)."""
    own = conn is None
    conn = conn or db.connect()
    raw = db.get_meta(conn, "settings")
    if own:
        conn.close()
    return json.loads(raw) if raw else None


def load_config():
    """config.toml with the person's settings laid over it.
    cfg["catalog"] = every job type (with enabled/custom flags); cfg["tracks"] = only the enabled ones."""
    cfg = load_defaults()
    user = get_settings() or {}
    catalog = {}
    for name, t in cfg.get("tracks", {}).items():
        catalog[name] = {"label": name, "kind": "remote", "search": [], "keywords": [], **t, "custom": False}
    for name, t in user.get("tracks", {}).items():
        if name in catalog:
            catalog[name].update({k: v for k, v in t.items() if k in (*TRACK_FIELDS, "enabled")})
        elif t.get("custom"):
            catalog[name] = {"label": name, "kind": "remote", "search": [], "keywords": [], "enabled": True, **t}
    for t in catalog.values():
        t["enabled"] = bool(t.get("enabled", True))
        t["kind"] = "abroad" if t.get("kind") == "abroad" else "remote"
    cfg["catalog"] = catalog
    cfg["tracks"] = {k: t for k, t in catalog.items() if t["enabled"]}

    for name, on in user.get("sources", {}).items():
        cfg.setdefault("sources", {}).setdefault(name, {})["enabled"] = bool(on)
    s = cfg["scoring"]
    pick = user.get("scoring", {})
    for key in ("min_score", "max_age_days"):
        if isinstance(pick.get(key), int):
            s[key] = pick[key]
    if pick.get("demote_senior") is False:
        s["demote_title"] = []
    cfg["fetch_choice"] = user.get("fetch")
    cfg["setup_done"] = bool(user.get("setup"))
    return cfg


def save_settings(new):
    """Store only what differs from config.toml, so improvements to the defaults still reach everyone."""
    defaults = load_defaults()
    base = defaults.get("tracks", {})
    old = get_settings() or {}
    tracks = {}
    for name, t in (new.get("tracks") or {}).items():
        if not isinstance(t, dict):
            continue
        clean = {"enabled": bool(t.get("enabled", True))}
        for k in TRACK_FIELDS:
            if k in t:
                v = t[k]
                clean[k] = [str(x).strip().lower() for x in v if str(x).strip()] if k in ("search", "keywords") else str(v).strip()
        if name in base:
            d = {"label": name, "kind": "remote", "search": [], "keywords": [], **base[name]}
            tracks[name] = {k: v for k, v in clean.items() if k == "enabled" or v != d.get(k)}
        elif t.get("custom"):
            tracks[name] = {**clean, "custom": True}
    settings = {
        "tracks": tracks,
        "sources": {k: bool(v) for k, v in (new.get("sources") or {}).items()},
        "scoring": {k: v for k, v in (new.get("scoring") or {}).items() if k in ("min_score", "max_age_days", "demote_senior")},
        "fetch": old.get("fetch"),
        "setup": True,
    }
    conn = db.connect()
    db.set_meta(conn, "settings", json.dumps(settings))
    scoring.rescore_all(conn, load_config())
    conn.close()


def save_fetch_choice(tracks, source_names):
    settings = get_settings() or {"tracks": {}, "sources": {}, "scoring": {}}
    settings["fetch"] = {"tracks": list(tracks), "sources": list(source_names)}
    conn = db.connect()
    db.set_meta(conn, "settings", json.dumps(settings))
    conn.close()


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


def fetch_all(log=print, tracks=None, source_names=None):
    """Fetch new jobs. tracks / source_names limit the run (None = every enabled one).
    Search sites only search the chosen job types' terms, and jobs that match none of the
    chosen job types are not saved."""
    cfg = load_config()
    chosen = {k: t for k, t in cfg["tracks"].items() if tracks is None or k in tracks}
    if not chosen:
        raise ValueError("Pick at least one job type to fetch.")
    kinds = {t["kind"] for t in chosen.values()}
    match_cfg = {**cfg, "tracks": chosen}

    conn = db.connect()
    db.set_meta(conn, "last_fetch", db.now())
    known = {r[0] for r in conn.execute("SELECT url FROM jobs")}
    ctx = {
        "seen": known.__contains__,
        "cutoff": (date.today() - timedelta(days=cfg["scoring"].get("max_age_days", 14))).isoformat(),
    }
    summary = []
    for name, fn in sources.SOURCES.items():
        scfg = cfg["sources"].get(name, {})
        if source_names is not None:
            if name not in source_names:
                continue
        elif not scfg.get("enabled", True):
            continue
        kind = sources.INFO[name]["kind"]
        if kind not in kinds:
            log(f"  {name:<15} skipped (no {kind} job types chosen)")
            continue
        ctx["search"] = list(dict.fromkeys(term for t in chosen.values() if t["kind"] == kind for term in t["search"]))
        warnings = []
        ctx["warn"] = lambda msg, name=name, w=warnings: (w.append(msg), log(f"  {name:<15} warning: {msg}"))
        log(f"  {name:<15} searching...")
        try:
            # The same job turns up under several search terms; keep one copy.
            found = list({j["url"]: j for j in fn(scfg, ctx) if j.get("url") and j.get("title")}.values())
            jobs = [j for j in found if scoring.matches(j, match_cfg)]
            if scfg.get("only_visa"):  # boards full of local-hire jobs: keep posts that offer a visa / relocation
                jobs = [j for j in jobs if scoring.sponsorship(scoring.as_row(j), cfg) == "yes"]
            if name in sources.DETAILS_ON_FETCH:
                fresh = [j for j in jobs if j["url"] not in known]
                for i, j in enumerate(fresh, 1):
                    log(f"  {name:<15} reading new post {i}/{len(fresh)}...")
                    try:
                        j["description"] = sources.DETAILS[name](j["url"]) or j["description"]
                        j["detailed"] = 1
                    except Exception as e:  # keep the preview text
                        ctx["warn"](f"full post for {j['url']}: {e}")
                    time.sleep(scfg.get("delay_seconds", 2))
            new = db.insert_jobs(conn, jobs)
            summary.append((name, len(jobs), new, "; ".join(warnings) or None))
            log(f"  {name:<15} {len(found):>4} found, {len(jobs):>4} relevant, {new:>4} new")
        except Exception as e:  # one broken source shouldn't stop the others
            summary.append((name, 0, 0, str(e)))
            log(f"  {name:<15} FAILED: {e}")
    scoring.rescore_all(conn, cfg)
    db.set_meta(conn, "scored_version", str(db.VERSION))
    conn.close()
    return summary
