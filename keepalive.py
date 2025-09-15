#!/usr/bin/env python3
"""
Keepalive bot:
- Reads TARGET_URL from env
- Stores state in .github/keepalive.json
- When due, hits the URL, logs to docs/keepalive-log.md, commits to main
- Schedules next run randomly 120–144 hours later
"""

import os, json, random, datetime, pathlib, sys, subprocess, urllib.request

UTC = datetime.timezone.utc

TARGET_URL = os.environ.get("TARGET_URL", "").strip()
STATE_FILE = os.environ.get("STATE_FILE", ".github/keepalive.json")
LOG_FILE   = os.environ.get("LOG_FILE", "docs/keepalive-log.md")
DEFAULT_BRANCH = os.environ.get("DEFAULT_BRANCH", "main")

def now_utc():
    return datetime.datetime.now(UTC)

def read_state(path: str):
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}

def parse_iso(ts: str):
    if not ts:
        return None
    try:
        # Accept "Z" suffix and offset formats
        ts = ts.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(ts)
    except Exception:
        return None

def http_ping(url: str, timeout=15):
    """Return (status_text, http_code_text)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "keepalive-bot/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            # 2xx/3xx = success
            if 200 <= code < 400:
                return ("success", str(code))
            return (f"failed_http_{code}", str(code))
    except Exception as e:
        # Don’t raise — record failure and continue scheduling
        return (f"failed_error", "error")

def write_state(path: str, data: dict):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))

def append_log(path: str, row: str):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(
            "# Keepalive Log\n\n"
            "This file is updated whenever the keepalive workflow actually **pings** the portfolio "
            "(randomly every 120–144 hours).\n\n"
            "| Timestamp (UTC) | Result | HTTP | Next Scheduled (UTC) | URL |\n"
            "|---|---|---|---|---|\n"
        )
    with p.open("a") as f:
        f.write(row + "\n")

def git(cmd: list[str]):
    subprocess.run(cmd, check=True)

def main():
    if not TARGET_URL:
        print("TARGET_URL not set. Define a repo Actions variable named PORTFOLIO_URL.", file=sys.stderr)
        # Don’t fail the job so the schedule can continue
        return 0

    state = read_state(STATE_FILE)
    next_run = parse_iso(state.get("next_run", ""))

    now = now_utc()

    due = (next_run is None) or (now >= next_run)
    if not due:
        print(f"Not due yet. next_run={next_run.isoformat()}")
        return 0

    # Do the ping
    status_text, http_code = http_ping(TARGET_URL)

    # Schedule next time: random 120–144 hours
    hours = random.randint(120, 144)
    next_time = now + datetime.timedelta(hours=hours)

    # Save state
    new_state = {
        "last_run": now.isoformat(),
        "last_status": status_text,
        "http_status": http_code,
        "next_run": next_time.isoformat(),
        "window_hours": [120, 144],
        "target_url": TARGET_URL,
    }
    write_state(STATE_FILE, new_state)

    # Append markdown log row
    row = f"| {now.isoformat()} | {status_text} | {http_code} | {next_time.isoformat()} | {TARGET_URL} |"
    append_log(LOG_FILE, row)

    # Commit to main
    try:
        git(["git", "config", "user.name", "github-actions[bot]"])
        git(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
        git(["git", "add", STATE_FILE, LOG_FILE])
        git(["git", "commit", "-m", f"keepalive: {status_text} (HTTP {http_code}) · next: {next_time.isoformat()}"])
        git(["git", "push", "origin", DEFAULT_BRANCH])
    except subprocess.CalledProcessError as e:
        # Still exit 0 so the job doesn’t fail if push races
        print(f"Commit/push skipped or failed: {e}", file=sys.stderr)

    print("Done.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
