"""Application replies via the Claude Code CLI (`claude -p`, called only when you click Ask Claude)."""
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "profile.md"
PROMPT_PATH = ROOT / "prompt.md"
SYSTEM = "You write job application replies. Follow the user's instructions exactly and output only what they ask for. Do not use tools."


def load_profile():
    """profile.md without comments or unfilled TODO lines, so the model can't copy examples as facts."""
    text = re.sub(r"<!--.*?-->", "", PROFILE_PATH.read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(line for line in text.splitlines() if "TODO" not in line)


def build_prompt(job, extra=""):
    post = (f"Source: {job['source']}\nTitle: {job['title']}\nCompany: {job['company'] or '?'}\n"
            f"Location: {job['location'] or '?'}\nPay: {job['salary'] or 'not stated'}\nType: {job['job_type'] or '?'}\n\n"
            f"{(job['description'] or '')[:12000]}")
    # str.replace, not .format, so braces in prompt.md or the post can't break anything.
    return (PROMPT_PATH.read_text(encoding="utf-8")
            .replace("{profile}", load_profile())
            .replace("{extra}", extra.strip() or "none")
            .replace("{job}", post))


def claude_bin():
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("The `claude` CLI was not found on PATH. Install Claude Code and log in (run `claude` once).")
    return exe


def split(text):
    """(reply, note): the prompt puts the note after a line of three dashes."""
    parts = re.split(r"^\s*-{3,}\s*$", text, maxsplit=1, flags=re.M)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")


def generate(job, extra=""):
    cmd = [claude_bin(), "-p", "--output-format", "json", "--model", os.environ.get("CLAUDE_MODEL", "sonnet"),
           "--system-prompt", SYSTEM, "--tools", "", "--strict-mcp-config", "--disable-slash-commands",
           "--no-session-persistence"]
    # Prompt goes over stdin (Windows caps command lines at ~32k chars). Run in a temp dir
    # so no project CLAUDE.md gets mixed in.
    with tempfile.TemporaryDirectory() as tmp:
        try:
            r = subprocess.run(cmd, input=build_prompt(job, extra), capture_output=True, text=True,
                               encoding="utf-8", timeout=240, cwd=tmp)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Claude took longer than 4 minutes. Try again.")
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude CLI failed (exit {r.returncode}): {(r.stderr or r.stdout)[:400]}")
    if data.get("is_error") or not data.get("result"):
        raise RuntimeError(f"Claude error: {str(data.get('result') or data)[:400]}")
    return split(data["result"])
