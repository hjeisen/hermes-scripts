#!/usr/bin/env python3
"""
Mr. Moneyball Cron Runner
Weekly Monday 7 AM execution for the Mr. Moneyball agent.
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

# Configuration
MR_MONEYBALL_SCRIPT = "/opt/data/mr_moneyball.py"
CRON_DIR = "/opt/data/cron"
LOG_DIR = "/opt/data/cron/output"
PID_FILE = "/opt/data/cron/mr_moneyball.pid"
LOG_FILE = "/opt/data/cron/output/mr_moneyball.log"

# Ensure dirs exist
os.makedirs(LOG_DIR, exist_ok=True)

running = True

def signal_handler(signum, frame):
    global running
    print(f"[{datetime.datetime.now().isoformat()}] Received signal {signum}, stopping...")
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
    timestamp = datetime.datetime.now().isoformat()
    line = f"[{timestamp}] {message}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def send_message_in_chunks(content, webhook_url, username="Mr. Moneyball"):
    """
    Send a Discord message in chunks to comply with Discord's 2000 character limit.
    """
    chunks = split_message_into_chunks(content, chunk_size=1900)
    all_success = True
    for i, chunk in enumerate(chunks):
        payload = {
            'content': chunk,
            'username': username
        }
        cmd = [
            'curl', '-s', '-X', 'POST',
            '-H', 'Content-Type: application/json',
            '-d', json.dumps(payload),
            webhook_url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            print(f'[WARN] Chunk {i+1}/{len(chunks)} FAILED: {result.stderr}')
            all_success = False
    return all_success

def split_message_into_chunks(content, chunk_size=1900):
    """
    Split a message into chunks that fit within Discord's character limit.
    """
    if len(content) <= chunk_size:
        return [content]

    lines = content.split('\n')
    chunks = []
    current_chunk = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > chunk_size:
            if current_chunk:
                chunks.append('\n'.join(current_chunk))
            current_chunk = [line]
            current_len = line_len
        else:
            if current_chunk:
                current_chunk.append(line)
            else:
                current_chunk = [line]
            current_len += line_len

    if current_chunk:
        chunks.append('\n'.join(current_chunk))

    return chunks

def run_mr_moneyball():
    """Run the Mr. Moneyball agent."""
    log("Starting Mr. Moneyball agent...")
    try:
        result = subprocess.run(
            [sys.executable, MR_MONEYBALL_SCRIPT],
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

def send_discord_notification(dry_run=False):
    """
    Build the Mr. Moneyball message and send it to Discord.
    Uses chunking to comply with Discord's character limit.
    """
    # Score Stocks
    log("Scoring stocks...")
    data_centers = score_sectors(SECTOR_SYMBOLS["data_centers"], "data_centers")
    renewable_energy = score_sectors(SECTOR_SYMBOLS["renewable_energy"], "renewable_energy")
    data_centers.sort(key=lambda x: x["score"], reverse=True)
    renewable_energy.sort(key=lambda x: x["score"], reverse=True)

    # Portfolio Allocation
    allocation = allocate_portfolio(data_centers, renewable_energy, INITIAL_PORTFOLIO)

    # Build message
    message = build_discord_message(data_centers, renewable_energy, allocation, INITIAL_PORTFOLIO)

    if dry_run:
        log("Dry run - skipping Discord delivery")
        print(message)
        return True

    log("Sending to Discord...")
    success = send_message_in_chunks(message, DISCORD_WEBHOOK, username="Mr. Moneyball")
    if success:
        log("Discord delivery successful")
    else:
        log("Discord delivery failed")
    return success

def main():
    write_pid()
    log("Mr. Moneyball cron runner started")

    # Check if called with a specific schedule
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        log("Running once (--once flag)")
        success = send_discord_notification(dry_run=True)
        remove_pid()
        sys.exit(0 if success else 1)

    # Default: run in a loop (for nohup background execution)
    log("Running in loop mode — will execute weekly Monday 7 AM")
    log("To run once: python crons.sh --once")

    # Run immediately on startup (for testing), then wait for next Monday 7 AM
    log("Running initial test execution...")
    success = send_discord_notification(dry_run=False)
    log("Initial run complete")

    # Calculate seconds until next Monday 7:00 AM
    now = datetime.datetime.now()
    # Target: next Monday at 7:00 AM
    days_until_monday = (7 - now.weekday()) % 7  # 0 if today is Monday, 1 if tomorrow is Monday, etc.
    target = now + datetime.timedelta(days=days_until_monday)
    # If today is Monday, target should be next Monday (add 7 days)
    if days_until_monday == 0:
        target += datetime.timedelta(days=7)
    # Set to 7:00 AM
    target = target.replace(hour=7, minute=0, second=0, microsecond=0)

    seconds_until = (target - now).total_seconds()
    log(f"Next execution: {target.strftime('%A %Y-%m-%d %H:%M:%S')} (in {seconds_until:.0f} seconds)")

    # Sleep in chunks to handle signals
    while running:
        remaining = (target - datetime.datetime.now()).total_seconds()
        if remaining <= 0:
            log("Time reached — running Mr. Moneyball agent...")
            run_mr_moneyball()
            # Schedule next week
            now = datetime.datetime.now()
            days_until_monday = (7 - now.weekday()) % 7
            target = now + datetime.timedelta(days=days_until_monday)
            if days_until_monday == 0:
                target += datetime.timedelta(days=7)
            target = target.replace(hour=7, minute=0, second=0, microsecond=0)
            seconds_until = (target - datetime.datetime.now()).total_seconds()
            log(f"Next execution: {target.strftime('%A %Y-%m-%d %H:%M:%S')} (in {seconds_until:.0f} seconds)")
        # Sleep in 60-second chunks
        sleep_time = min(60, remaining) if remaining > 0 else 60
        time.sleep(sleep_time)

    remove_pid()
    log("Runner stopped")

if __name__ == "__main__":
    main()
