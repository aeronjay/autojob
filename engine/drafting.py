"""Application replies and follow-ups via the Claude Code CLI (`claude -p`, called only when you click)."""
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "profile.md"
PROFILE_TEMPLATE = ROOT / "profile.example.md"
PROMPT_PATH = ROOT / "prompt.md"
FOLLOWUP_PATH = ROOT / "followup.md"
SYSTEM = "You write job application replies and cover letters. Follow the user's instructions exactly and output only what they ask for. Do not use tools."


# A line still to fill in: "- Rates: TODO", "- TODO", "## Teaching (TODO ...". Not the file's own
# instructions, which mention the word in passing ("Fill in every line marked TODO").
UNFILLED = re.compile(r"(?:^|[-:(#]\s*)TODO\b")


def read_profile():
    """profile.md, created from profile.example.md the first time (each person keeps their own)."""
    if not PROFILE_PATH.exists() and PROFILE_TEMPLATE.exists():
        PROFILE_PATH.write_text(PROFILE_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    return PROFILE_PATH.read_text(encoding="utf-8") if PROFILE_PATH.exists() else ""


def save_profile(text):
    PROFILE_PATH.write_text(text.replace("\r\n", "\n"), encoding="utf-8")


def load_profile():
    """profile.md without comments or unfilled TODO lines, so the model can't copy examples as facts."""
    text = re.sub(r"<!--.*?-->", "", read_profile(), flags=re.S)
    return "\n".join(line for line in text.splitlines() if "TODO" not in line)


def profile_todos():
    """How many lines of profile.md are still unfilled (those lines never reach Claude)."""
    text = re.sub(r"<!--.*?-->", "", read_profile(), flags=re.S)
    return sum(bool(UNFILLED.search(line)) for line in text.splitlines())


def job_text(job):
    return (f"Source: {job['source']}\nTitle: {job['title']}\nCompany: {job['company'] or '?'}\n"
            f"Location: {job['location'] or '?'}\nPay: {job['salary'] or 'not stated'}\nType: {job['job_type'] or '?'}\n\n"
            f"{(job['description'] or '')[:12000]}")


def fill(template_path, **parts):
    # str.replace, not .format, so braces in the template or the post can't break anything.
    text = template_path.read_text(encoding="utf-8")
    for key, value in parts.items():
        text = text.replace("{" + key + "}", value)
    return text


def track_text(track):
    """track = {"label", "kind"} of the job's job type, or None."""
    if not track:
        return "unknown (treat as remote)"
    if track.get("kind") == "abroad":
        return f"{track['label']} (abroad: an on-site job in another country; the applicant would relocate and usually needs visa sponsorship)"
    return f"{track['label']} (remote: the applicant works from home in their own country)"


def build_prompt(job, extra="", track=None):
    return fill(PROMPT_PATH, profile=load_profile(), extra=extra.strip() or "none", job=job_text(job), track=track_text(track))


def build_followup_prompt(job, days, extra="", track=None):
    return fill(FOLLOWUP_PATH, profile=load_profile(), extra=extra.strip() or "none", job=job_text(job),
                reply=(job["draft"] or "").strip() or "(not saved)", days=str(days), track=track_text(track))


def claude_bin():
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("The `claude` CLI was not found on PATH. Install Claude Code and log in (run `claude` once).")
    return exe


def split(text):
    """(reply, note): the prompt puts the note after a line of three dashes."""
    parts = re.split(r"^\s*-{3,}\s*$", text, maxsplit=1, flags=re.M)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")


def run_claude(prompt):
    cmd = [claude_bin(), "-p", "--output-format", "json", "--model", os.environ.get("CLAUDE_MODEL", "sonnet"),
           "--system-prompt", SYSTEM, "--tools", "", "--strict-mcp-config", "--disable-slash-commands",
           "--no-session-persistence"]
    # Prompt goes over stdin (Windows caps command lines at ~32k chars). Run in a temp dir
    # so no project CLAUDE.md gets mixed in.
    with tempfile.TemporaryDirectory() as tmp:
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                               encoding="utf-8", timeout=240, cwd=tmp)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Claude took longer than 4 minutes. Try again.")
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude CLI failed (exit {r.returncode}): {(r.stderr or r.stdout)[:400]}")
    if data.get("is_error") or not data.get("result"):
        raise RuntimeError(f"Claude error: {str(data.get('result') or data)[:400]}")
    return data["result"]


def generate(job, extra="", track=None):
    return split(run_claude(build_prompt(job, extra, track)))


def followup(job, days, extra="", track=None):
    return split(run_claude(build_followup_prompt(job, days, extra, track)))[0]
