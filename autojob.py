"""autojob: find remote jobs, rank them, have Claude write replies, track every application. You click send.

Usage:
  python autojob.py fetch     # pull new jobs from every source
  python autojob.py serve     # open the dashboard at http://127.0.0.1:5000 (5050 on a Mac)
  python autojob.py rescore   # re-apply config.toml scoring to saved jobs
"""
import os
import sys
import webbrowser

from dotenv import load_dotenv

load_dotenv()

from engine import core, db, scoring  # noqa: E402


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "fetch":
        print("Fetching jobs...")
        core.fetch_all()
        conn = db.connect()
        n = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE status='new' AND {db.INBOX_FILTER}",
                         db.inbox_args(core.load_config())).fetchone()[0]
        print(f"Done. {n} matching jobs waiting in the dashboard (python autojob.py serve).")
    elif cmd == "serve":
        from engine.app import app
        core.ensure_scored()
        # macOS uses port 5000 for AirPlay Receiver, so Macs default to 5050. PORT in .env overrides.
        port = int(os.environ.get("PORT") or (5050 if sys.platform == "darwin" else 5000))
        webbrowser.open(f"http://127.0.0.1:{port}")
        app.run(port=port, debug=False)
    elif cmd == "rescore":
        print(f"Rescored {scoring.rescore_all(db.connect(), core.load_config())} jobs.")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
