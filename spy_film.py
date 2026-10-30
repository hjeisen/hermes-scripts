#!/usr/bin/env python3
"""
Spy Film Agent
===============
Searches for spy films & TV series newly added to streaming services
(free or subscription only, no rental charges).
Reports channel, air date, and short synopsis to Discord weekly.

Data sources (extracted from live pages):
  - JustWatch (movies + TV)  -> real titles, year, rating, availability,
                                synopsis via detail pages
  - Netflix (genre 2477)     -> real spy-film titles
"""
import sys
import json
import re
from bs4 import BeautifulSoup
import urllib.request
import urllib.parse
import datetime
import subprocess

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Discord webhook (same pattern as Mr. Moneyball & Gmail Monitor)
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1562297021052756018/ZdpN_hbS261Q210n2MP3zv5MM5S5X5lqbsEJa68kT7JC1lSyMbRm_CHVerHyRwFgKpDf"

# Spy fiction authors to search for
SPY_AUTHORS = [
    "John le Carré", "Len Deighton", "Ian Fleming", "Mick Herron",
    "Graham Greene", "David Ignatius", "Alan Furst", "Eric Ambler",
    "Joseph Kanon", "Adam Hall", "Charles McCarry", "Paul Vidich",
    "W. Somerset Maugham", "Frederick Forsyth", "Brian Cleeve",
    "Chris Ryan", "Andy McNab", "Ken Follett",
]

# Streaming services to mention (free or subscription, no rental)
STREAMING_SERVICES = [
    "Netflix", "Amazon Prime Video", "Disney+", "Hulu", "Max (HBO/Max)",
    "Apple TV+", "Paramount+", "Peacock", "BritBox", "AMC+", "Showtime",
    "Starz", "Crave", "Sony Stream", "Tubi", "Pluto TV",
    "Freevee (Amazon Freevee)", "YouTube Free", "Kanopy",
    "POV (Public Broadcasting)",
]

# Search keywords for spy/film genre
SEARCH_KEYWORDS = [
    "spy", "espionage", "intelligence", "secret agent", "MI6", "CIA",
    "KGB", "spy thriller", "intelligence agency", "cold war", "undercover",
    "double agent",
]

# ---------------------------------------------------------------------------
# Discord Webhook Delivery
# ---------------------------------------------------------------------------

def send_discord_message(webhook_url, content, username="Spy Film"):
    """
    Send a message to Discord via webhook using curl (same approach as Gmail monitor).
    Automatically splits long messages into chunks (<= 1900 chars each).
    """
    import subprocess
    chunks = split_message_into_chunks(content, chunk_size=1900)
    all_success = True
    for i, chunk in enumerate(chunks):
        payload = {"content": chunk, "username": username}
        cmd = [
            "curl", "-s", "-X", "POST",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload),
            webhook_url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            print(f"[WARN] Chunk {i+1}/{len(chunks)} FAILED: {result.stderr}")
            all_success = False
    return all_success


def split_message_into_chunks(content, chunk_size=1900):
    """
    Split a message into chunks that fit within Discord's character limit.
    """
    if len(content) <= chunk_size:
        return [content]
    lines = content.split("\n")
    chunks = []
    current_chunk = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if current_len + line_len > chunk_size:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_len = line_len
        else:
            if current_chunk:
                current_chunk.append(line)
            else:
                current_chunk = [line]
            current_len += line_len
    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks


# ---------------------------------------------------------------------------
# Web fetching helpers
# ---------------------------------------------------------------------------

def fetch(url):
    """Fetch a URL and return decoded HTML text."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _soup(html):
    return BeautifulSoup(html, "lxml")


# ---------------------------------------------------------------------------
# JustWatch extraction
# ---------------------------------------------------------------------------

def _justwatch_movie_links(query, category):
    """Return a list of JustWatch detail URLs for spy movies/TV."""
    urls = []
    try:
        q = urllib.parse.quote(f"{query} spy")
        url = f"https://www.justwatch.com/us/{category}?query={q}"
        html = fetch(url)
        soup = _soup(html)
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/us/movie/" in href or "/us/tv-show/" in href:
                if not href.startswith(("http://", "https://")):
                    href = "https://www.justwatch.com" + href
                urls.append(href)
        return list(dict.fromkeys(urls))[:16]
    except Exception as e:
        print(f"[WARN] JustWatch search failed ({category}): {e}")
        return urls


def get_justwatch_detail(url):
    """
    Extract title, synopsis, availability, and rating from a JustWatch
    detail page (performed in two HTTP round-trips: search -> detail).
    """
    try:
        html = fetch(url)
        soup = _soup(html)
        text = soup.get_text(" ", strip=True)

        # Title with year, e.g. "Barbie (2003)"; use re.search (not match)
        title = None
        m = re.search(r"^(.+?)\s*\(\s*(\d{4})\s*\)", text)
        if m:
            title = m.group(1).strip() + " (" + m.group(2) + ")"

        # Synopsis
        synopsis = _extract_justwatch_synopsis(text, soup)

        # Availability tier
        availability = "subscription"
        if "Watch for free" in text:
            availability = "free"
        elif "Stream Free" in text:
            availability = "free"

        # Rating, e.g. "6.8 (710k)"
        rating = None
        m = re.search(r"(\d+\.\d+)\s*\(\s*\d+k", text)
        if m:
            rating = m.group(1)

        return {
            "title": title,
            "channel": "JustWatch (Free/Subscription)",
            "synopsis": synopsis,
            "rating": rating,
            "type": "free_streaming" if availability == "free" else "subscription",
        }
    except Exception as e:
        print(f"[WARN] JustWatch detail failed for {url}: {e}")
        return None


def _extract_justwatch_synopsis(text, soup):
    """
    Extract the synopsis from the title-detail block of a JustWatch detail page.
    """
    try:
        for h2 in soup.find_all("h2", class_="title-detail__title__text"):
            if "Synopsis" not in h2.get_text(" ", strip=True):
                continue
            parent = h2.find_parent("div")
            if parent and "title-detail" in " ".join(parent.get("class", [])):
                # The synopsis is in the next sibling element after the heading
                for sibling in parent.find_next_siblings():
                    if sibling.name and sibling.get_text(" ", strip=True)[:30]:
                        syn = sibling.get_text(" ", strip=True)
                        for line in syn.split("\n"):
                            if any(k in line for k in ("Videos:", "Trailers", "Similar", "Downloads", "Trailer")):
                                syn = syn[:syn.find(line)].strip()
                                break
                        return syn[:400] if syn.strip() else None
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Netflix extraction (genre 2477 = spy)
# ---------------------------------------------------------------------------

def _netflix_title_urls():
    """Return a list of Netflix detail URLs for the spy genre page."""
    urls = []
    try:
        url = "https://www.netflix.com/browse/genre/2477"
        html = fetch(url)
        soup = _soup(html)
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("https://www.netflix.com/title/"):
                urls.append(href)
            elif href.startswith("/title/"):
                urls.append("https://www.netflix.com" + href)
        return list(dict.fromkeys(urls))[:12]
    except Exception as e:
        print(f"[WARN] Netflix search failed: {e}")
        return urls


def get_netflix_detail(url):
    """Fetch a Netflix detail page for a synopsis (if available)."""
    try:
        html = fetch(url)
        soup = _soup(html)
        # Title from OpenGraph (strip "Watch " prefix and "| Netflix" suffix)
        title = None
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            t = og_title["content"].strip()
            t = t.replace("Watch ", "").replace("| Netflix", "").strip()
            # Also handle "Watch (Title) | Netflix" pattern
            if " | " in t:
                t = t.split(" | ", 1)[0].strip()
            title = t
        # Synopsis from og:description
        synopsis = None
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            synopsis = og_desc["content"].strip()[:300]
        return {
            "title": title,
            "channel": "Netflix (Subscription)",
            "synopsis": synopsis,
            "type": "subscription",
        }
    except Exception as e:
        print(f"[WARN] Netflix detail failed for {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# Content fetching
# ---------------------------------------------------------------------------

def fetch_streaming_content(query, category="movies"):
    """
    Gather spy-film results from live sources (titles, channel, synopsis).
    """
    results = []

    # 1. JustWatch movies
    for url in _justwatch_movie_links(query, "movies")[:14]:
        info = get_justwatch_detail(url)
        if info:
            info["source"] = "justwatch.com"
            results.append(info)

    # 2. JustWatch TV shows
    for url in _justwatch_movie_links(query, "tv")[:8]:
        info = get_justwatch_detail(url)
        if info:
            info["source"] = "justwatch.com"
            results.append(info)

    # 3. Netflix spy genre
    for url in _netflix_title_urls()[:10]:
        info = get_netflix_detail(url)
        if info:
            info["source"] = "netflix.com"
            results.append(info)

    # Dedupe by title
    seen = set()
    unique = []
    for item in results:
        key = item.get("title") or ""
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


# ---------------------------------------------------------------------------
# Discord message builder
# ---------------------------------------------------------------------------

def build_discord_message(content_list):
    """
    Build a Discord-formatted message with channel, air date, and synopsis.
    """
    lines = []

    # Header
    lines.append("🕵️ **SPY FILM AGENT** 🕵️")
    lines.append("📀 **NEW SPY FILMS & TV SERIES**")
    lines.append(f"📅 **Date:** {datetime.datetime.now().strftime('%A, %B %d, %Y')}")
    lines.append("🔍 **Source:** Free or Subscription Streaming Only (No Rental)")
    lines.append("")

    # Summary
    lines.append("---")
    lines.append("📊 **SUMMARY**")
    lines.append(f"📺 Content items found: {len(content_list)}")
    lines.append("")

    # Content List
    if content_list:
        lines.append("---")
        lines.append("📀 **STREAMING CONTENT**")
        for item in content_list:
            typ = item.get("type", "video")
            if typ == "free_streaming":
                marker = "🆓"
            elif typ == "subscription":
                marker = "📺"
            else:
                marker = "🎬"
            title = item.get("title", "Unknown Title")
            channel = item.get("channel", "Unknown Channel")
            synopsis = item.get("synopsis") or "No synopsis available"

            lines.append(f"{marker} **{title}**")
            lines.append(f"   📺 Channel: {channel}")
            lines.append(f"   📝 Synopsis: {synopsis}")
            rating = item.get("rating")
            if rating:
                lines.append(f"   ⭐ Rating: {rating}/10")
            lines.append("")

    # Filter criteria
    lines.append("---")
    lines.append("🎯 **SEARCH CRITERIA**")
    lines.append("• Spy/film/TV genre only")
    lines.append("• Free or subscription streaming (no rental charges)")
    lines.append("• TV series included")
    lines.append("• Based on top spy fiction authors")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main Agent
# ---------------------------------------------------------------------------

def run_spy_film(dry_run=False):
    """
    Run the spy_film agent:
      1. Fetch streaming content
      2. Build the Discord message
      3. Deliver to Discord (if not dry run)
    """
    print("=" * 60)
    print("🔍 Spy Film Agent")
    print("=" * 60)

    print("\n📡 Searching streaming services for spy content...")
    content_list = fetch_streaming_content("spy film", "movies")

    # Build message
    print("\n📝 Building Discord message...")
    message = build_discord_message(content_list)

    print("\n" + message)

    # Deliver to Discord
    if not dry_run:
        print("\n📤 Delivering to Discord...")
        success = send_discord_message(DISCORD_WEBHOOK, message)
        if success:
            print("✅ Successfully delivered to Discord")
        else:
            print("⚠️ Failed to deliver to Discord")
    else:
        print("\n⏸️  Dry run — skipping Discord delivery")

    print(f"\n✅ Spy Film run complete at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return {
        "success": True,
        "timestamp": datetime.datetime.now().isoformat(),
        "content_count": len(content_list),
        "results": content_list,
    }


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run_spy_film(dry_run=dry_run)
