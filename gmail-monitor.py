#!/usr/bin/env python3
"""
Gmail Monitor Agent
- Polls Gmail for emails from monitored senders
- Tracks seen email IDs to avoid duplicates
- Sends Discord webhook notifications
- Runs continuously in the background
"""

import json
import time
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# --- Configuration ---
WEBHOOK_URL = "https://discord.com/api/webhooks/1561477251831304312/YF3QUO9-FcC0VpG7RjY54mjxdvTRMk__TDg1yiv7AMwAao4i_G1Sg3guxYUmeCfpii0t"

# Senders to monitor
MONITORED_SENDERS = [
    "anthonyalcazar7@gmail.com",
    "jackiegaleano22@gmail.com",
]

# Sleep window: don't check Gmail between these hours (local time)
# Format: (start_hour, start_minute, end_hour, end_minute)
# Example: (23, 30, 6, 0) means 11:30 PM to 6:00 AM
SLEEP_WINDOW = (23, 30, 6, 0)

# Timezone for local time (America/Los_Angeles for Pacific Time)
TIMEZONE = "America/Los_Angeles"

# State file to track seen email IDs
STATE_FILE = Path("/opt/data/gmail_monitor_state.json")

# Poll interval in seconds (600 = 10 minutes)
POLL_INTERVAL = 600

# Log file
LOG_FILE = Path("/opt/data/gmail_monitor.log")

# Gmail search syntax for checking multiple senders
# Using OR with from: operator
SEARCH_QUERY = " OR ".join(f"from:{sender}" for sender in MONITORED_SENDERS)

# --- Google Workspace setup ---
TOKEN_PATH = Path("/opt/data/google_token.json")


def load_token():
    """Load the authenticated token."""
    if not TOKEN_PATH.exists():
        raise RuntimeError("Google OAuth token not found. Run setup first.")
    return TOKEN_PATH.read_text(encoding="utf-8")


def load_state():
    """Load seen email IDs from state file."""
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return data.get("seen_emails", [])
        except Exception:
            pass
    return []


def save_state(seen_emails):
    """Save seen email IDs to state file."""
    STATE_FILE.write_text(
        json.dumps({"seen_emails": seen_emails, "updated": datetime.now(timezone.utc).isoformat()}, indent=2),
        encoding="utf-8"
    )


def is_in_sleep_window():
    """Check if current local time falls within the sleep window."""
    local_tz = ZoneInfo(TIMEZONE)
    now = datetime.now(local_tz)
    start_h, start_m, end_h, end_m = SLEEP_WINDOW
    
    current_minute = now.hour * 60 + now.minute
    
    # Convert sleep window to minutes since midnight
    start_minute = start_h * 60 + start_m
    end_minute = end_h * 60 + end_m
    
    # If start < end, it's a normal window (e.g., 9:00 to 17:00)
    # If start > end, it's a night window (e.g., 23:30 to 6:00)
    if start_h < end_h or (start_h == end_h and start_m <= end_m):
        # Normal window
        return start_minute <= current_minute <= end_minute
    else:
        # Night window (e.g., 23:30 to 6:00)
        return current_minute >= start_minute or current_minute <= end_minute


def send_discord_webhook(content, username="Gmail Monitor"):
    """Send a notification to Discord via webhook using curl."""
    payload = {
        "content": content,
        "username": username,
        "avatar_url": "https://example.com/gmail-monitor.png"
    }
    import subprocess
    cmd = [
        "curl", "-s", "-X", "POST",
        "-H", "Content-Type: application/json",
        "-d", json.dumps(payload),
        WEBHOOK_URL
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return True
        else:
            print(f"Webhook error: {result.stderr}", flush=True)
            return False
    except Exception as e:
        print(f"Webhook exception: {e}", flush=True)
        return False


def check_gmail():
    """Check Gmail for new emails from monitored senders."""
    import subprocess
    
    # Use the Hermes Python to run google_api.py (it needs googleapiclient)
    gapi_python = "/opt/hermes/.venv/bin/python3"
    
    cmd = [
        gapi_python, "/opt/data/skills/productivity/google-workspace/scripts/google_api.py",
        "gmail", "search", f"({SEARCH_QUERY})", "--max", "20"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Gmail search error: {result.stderr}", flush=True)
        return []
    
    try:
        emails = json.loads(result.stdout)
        return emails
    except json.JSONDecodeError:
        print(f"Failed to parse Gmail search results: {result.stdout}", flush=True)
        return []


def format_email_for_discord(email):
    """Format an email as a Discord-friendly message."""
    from_field = email.get("from", "Unknown sender")
    subject = email.get("subject", "No subject")
    date = email.get("date", "Unknown date")
    snippet = email.get("snippet", "")
    
    # Truncate snippet if too long
    if len(snippet) > 500:
        snippet = snippet[:500] + "..."
    
    message = (
        f"**New email from {from_field}**\n"
        f"📅 *{date}*\n"
        f"📧 *{subject}*\n"
        f"> {snippet}"
    )
    return message


def main():
    print(f"[{datetime.now().isoformat()}] Gmail Monitor starting...", flush=True)
    print(f"Monitoring senders: {', '.join(MONITORED_SENDERS)}", flush=True)
    print(f"Poll interval: {POLL_INTERVAL}s", flush=True)
    print(f"Sleep window: {SLEEP_WINDOW[0]}:{SLEEP_WINDOW[1]:02d} to {SLEEP_WINDOW[2]}:{SLEEP_WINDOW[3]:02d} ({TIMEZONE})", flush=True)
    
    # Load initial state
    seen_emails = load_state()
    print(f"Loaded {len(seen_emails)} previously seen emails", flush=True)
    
    # Track new emails found in this session
    new_count = 0
    
    try:
        while True:
            try:
                # Check current time to see if we should sleep
                local_tz = ZoneInfo(TIMEZONE)
                now = datetime.now(local_tz)
                current_minute = now.hour * 60 + now.minute
                start_minute = SLEEP_WINDOW[0] * 60 + SLEEP_WINDOW[1]
                end_minute = SLEEP_WINDOW[2] * 60 + SLEEP_WINDOW[3]
                
                # Determine if we're in the sleep window
                if SLEEP_WINDOW[0] < SLEEP_WINDOW[2] or (SLEEP_WINDOW[0] == SLEEP_WINDOW[2] and SLEEP_WINDOW[1] <= SLEEP_WINDOW[3]):
                    # Normal window (e.g., 9:00 to 17:00)
                    in_sleep_window = start_minute <= current_minute <= end_minute
                else:
                    # Night window (e.g., 23:30 to 6:00)
                    in_sleep_window = current_minute >= start_minute or current_minute <= end_minute
                
                if in_sleep_window:
                    print(f"[{datetime.now().isoformat()}] Sleeping (within window 23:30-06:00)", flush=True)
                    time.sleep(POLL_INTERVAL)
                    continue
                
                emails = check_gmail()
                new_emails = []
                
                for email in emails:
                    email_id = email.get("id")
                    if email_id and email_id not in seen_emails:
                        seen_emails.append(email_id)
                        new_emails.append(email)
                        new_count += 1
                
                # If we found new emails, send notifications
                if new_emails:
                    print(f"[{datetime.now().isoformat()}] Found {len(new_emails)} new emails", flush=True)
                    save_state(seen_emails)
                    
                    for email in new_emails:
                        message = format_email_for_discord(email)
                        send_discord_webhook(message)
                        print(f"  Sent Discord notification for: {email.get('subject', 'No subject')}", flush=True)
                
                # Small delay between polls
                time.sleep(POLL_INTERVAL)
                
            except Exception as e:
                print(f"[{datetime.now().isoformat()}] Error: {e}", flush=True)
                time.sleep(POLL_INTERVAL)
    
    except KeyboardInterrupt:
        print(f"[{datetime.now().isoformat()}] Shutting down...", flush=True)
        save_state(seen_emails)
        print(f"Final state: {len(seen_emails)} seen emails", flush=True)


if __name__ == "__main__":
    main()
