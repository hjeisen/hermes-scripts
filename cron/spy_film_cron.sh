#!/usr/bin/env python3
"""
Spy Film Cron Runner
Weekly Thursday 7:00 AM execution for the spy_film agent.
This script is designed to be run in a background loop (sleep + nohup)
because the cron executable at /opt/data/cron/ is not systemd-schedulable.
"""

import os
import sys
import time
import subprocess
import signal
import datetime
import json
from zoneinfo import ZoneInfo

# Timezone for scheduling (Burbank, CA = America/Los_Angeles)
TZ_NAME = "America/Los_Angeles"
TZ = ZoneInfo(TZ_NAME)

# Configuration
SPY_FILM_SCRIPT = "/opt/data/home/hermes-agents/spy_film.py"
CRON_DIR = "/opt/data/cron"
LOG_DIR = "/opt/data/cron/output"
PID_FILE = "/opt/data/cron/spy_film.pid"
LOG_FILE = "/opt/data/cron/output/spy_film.log"

# Ensure dirs exist
os.makedirs(LOG_DIR, exist_ok=True)

running = True

def signal_handler(signum, frame):
    global running
    print(f"[{datetime.datetime.now().isoformat()}] Received signal {signum}, stopping...", flush=True)
    running = False

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

def write_pid():
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

def remove_pid():
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)

def log(message):
    timestamp = datetime.datetime.now(TZ).isoformat()
    line = f"[{timestamp}] {message}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def run_spy_film():
    """Run the spy_film agent."""
    log("Starting spy_film agent...")
    try:
        result = subprocess.run(
            [sys.executable, SPY_FILM_SCRIPT],
            capture_output=True,
            text=True,
            timeout=300
        )
        if result.stdout:
            log(f"Agent stdout: {result.stdout[:500]}")
        if result.stderr:
            log(f"Agent stderr: {result.stderr[:500]}")
        if result.returncode == 0:
            log("Agent completed successfully")
        else:
            log(f"Agent failed with exit code {result.returncode}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        log("Agent timed out after 300 seconds")
        return False
    except Exception as e:
        log(f"Error running agent: {e}")
        return False

def main():
    write_pid()
    log("Spy Film cron runner started")
    log("Running in loop mode — will execute weekly Thursday 7:00 AM (Los Angeles)")
    log("To run once: python spy_film_cron.sh --once")

    # Run initial test execution
    log("Running initial test execution...")
    success = run_spy_film()
    log("Initial run complete")

    # Calculate seconds until next Thursday 7:00 AM in Los Angeles timezone
    now = datetime.datetime.now(TZ)
    # Target: next Thursday at 7:00 AM (Burbank, CA = America/Los_Angeles)
    days_until_thursday = (3 - now.weekday()) % 7  # 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday
    if days_until_thursday == 0:
        days_until_thursday = 7  # Today is Thursday, use next Thursday
    target = now + datetime.timedelta(days=days_until_thursday)
    target = target.replace(hour=7, minute=0, second=0, microsecond=0)

    # Convert to UTC for comparison
    target_utc = target.astimezone(ZoneInfo("UTC"))
    now_utc = now.astimezone(ZoneInfo("UTC"))
    seconds_until = (target_utc - now_utc).total_seconds()

    log(f"Next execution: {target.strftime('%A %Y-%m-%d %H:%M:%S')} PDT (in {seconds_until:.0f} seconds)")

    # Sleep in chunks to handle signals
    while running:
        remaining = (target - datetime.datetime.now(TZ)).total_seconds()
        if remaining <= 0:
            log("Time reached — running spy_film agent...")
            run_spy_film()
            # Schedule next week
            now = datetime.datetime.now(TZ)
            days_until_thursday = (3 - now.weekday()) % 7
            if days_until_thursday == 0:
                days_until_thursday = 7
            target = now + datetime.timedelta(days=days_until_thursday)
            target = target.replace(hour=7, minute=0, second=0, microsecond=0)
            target_utc = target.astimezone(ZoneInfo("UTC"))
            now_utc = now.astimezone(ZoneInfo("UTC"))
            seconds_until = (target_utc - now_utc).total_seconds()
            log(f"Next execution: {target.strftime('%A %Y-%m-%d %H:%M:%S')} PDT (in {seconds_until:.0f} seconds)")
        # Sleep in 60-second chunks
        sleep_time = min(60, remaining) if remaining > 0 else 60
        time.sleep(sleep_time)

    remove_pid()
    log("Runner stopped")

if __name__ == "__main__":
    main()
