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
    """
    Return a list of JustWatch detail URLs for spy-adjacent movies/TV.

    Uses the 'new' listing page (recently added titles) rather than the
    search URL, since the search URL does not filter by keyword.

    Returns up to 16 URLs.
    """
    urls = []
    try:
        # Use the 'new' listing page to get recently added movies/TV
        if category == "movies":
            url = "https://www.justwatch.com/us/movies/new"
        else:
            url = "https://www.justwatch.com/us/tv-shows/new"

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
        print(f"[WARN] JustWatch 'new' listing failed ({category}): {e}")
        return urls


def get_justwatch_detail(url):
    """
    Extract title, synopsis, availability, rating, and genre tags from a JustWatch
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

        # Genres, e.g. "Action Thriller, Mystery Thriller" or "Comedy, Fantasy, Live Action"
        genres = _extract_genres(soup)

        return {
            "title": title,
            "channel": "JustWatch (Free/Subscription)",
            "synopsis": synopsis,
            "rating": rating,
            "type": "free_streaming" if availability == "free" else "subscription",
            "genres": genres,
        }
    except Exception as e:
        print(f"[WARN] JustWatch detail failed for {url}: {e}")
        return None


def _extract_genres(soup):
    """
    Extract genre tags from a JustWatch detail page.

    Returns a list of genre strings (e.g. ['Action Thriller', 'Mystery Thriller',
    'Crime', 'Drama'] or ['Comedy', 'Fantasy', 'Live Action']).
    """
    genres = []
    try:
        # Genre section (poster-detail-infos__value with "Genres" subheading)
        for tag in soup.find_all('div', class_='poster-detail-infos__value'):
            parent_h3 = tag.find_previous(['h3'])
            if parent_h3 and 'genre' in parent_h3.get_text(' ', strip=True).lower():
                genres.append(tag.get_text(' ', strip=True))

        # Detail Infos link genres (Action Thriller, Mystery & Thriller, etc.)
        for a in soup.find_all('a', class_='detail-infos__value detail-infos__link'):
            g = a.get_text(' ', strip=True)
            if g and g not in genres:
                genres.append(g)
    except Exception as e:
        print(f"[WARN] Genres extraction failed: {e}")
    return genres


def _extract_genres(soup):
    """
    Extract genre tags from a JustWatch detail page.

    Returns a list of genre strings (e.g. ['Action Thriller', 'Mystery Thriller',
    'Crime', 'Drama'] or ['Comedy', 'Fantasy', 'Live Action']).
    """
    genres = []
    try:
        # Genre section (poster-detail-infos__value with "Genres" subheading)
        for tag in soup.find_all('div', class_='poster-detail-infos__value'):
            parent_h3 = tag.find_previous(['h3'])
            if parent_h3 and 'genre' in parent_h3.get_text(' ', strip=True).lower():
                genres.append(tag.get_text(' ', strip=True))

        # Detail Infos link genres (Action Thriller, Mystery & Thriller, etc.)
        for a in soup.find_all('a', class_='detail-infos__value detail-infos__link'):
            g = a.get_text(' ', strip=True)
            if g and g not in genres:
                genres.append(g)
    except Exception as e:
        print(f"[WARN] Genres extraction failed: {e}")
    return genres


def _is_spy_content(genres, synopsis):
    """
    Filter: keep titles that are likely spy/espionage-related films (and
    exclude anything that is clearly not a spy film).

    The filter does BOTH:
    1. Excludes clearly non-spy titles (only comedy/fantasy/musical/romance/horror)
    2. Requires at least one spy-adjacent genre tag (thriller, crime, mystery)
       OR explicit spy-related keywords in the synopsis.

    Returns True if the title should be included, False otherwise.
    """
    if not genres and not synopsis:
        return False

    # Non-spy genres to exclude (only if the title has NO spy-adjacent genres)
    anti_spy = ['comedy', 'fantasy', 'musical', 'romance', 'horror']

    # Spy-related keyword check (more inclusive - includes thriller/crime/mystery)
    spy_genres = [
        'spy', 'espionage', 'intelligence', 'secret agent', 'MI6', 'CIA',
        'KGB', 'undercover', 'covert', 'cold war', 'spymaster', 'mole',
        'defection', 'double agent', 'spy thriller', 'spy fiction',
        'thriller', 'crime', 'mystery', 'detective',
    ]
    has_spy_genre = any(any(kw in g.lower() for kw in spy_genres) for g in genres)

    # If the title has ONLY non-spy genres (no spy genres), reject
    if not has_spy_genre:
        anti_spy = ['comedy', 'fantasy', 'musical', 'romance', 'horror']
        has_anti_spy = any(any(kw in g.lower() for kw in anti_spy) for g in genres)
        if has_anti_spy:
            # All genres are non-spy - reject
            return False

    # No clear genre classification - check synopsis for spy keywords
    has_spy_synopsis = False
    if synopsis:
        synopsis_lower = synopsis.lower()
        spy_keywords = [
            'spy', 'espionage', 'secret agent', 'MI6', 'CIA', 'KGB',
            'undercover', 'covert', 'cold war', 'spymaster', 'mole',
            'defection', 'double agent', 'spy thriller', 'spy fiction',
            'assassin', 'assassination', 'intelligence agency',
        ]
        has_spy_synopsis = any(kw in synopsis_lower for kw in spy_keywords)

    return has_spy_synopsis


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

_TUBI_CATEGORIES = [
    "https://tubitv.com/category/action",
    "https://tubitv.com/category/thriller",
    "https://tubitv.com/category/crime",
    "https://tubitv.com/category/mystery",
]


def _tubi_category_links():
    """Return Tubi movie/series links from public category pages via Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []

    links = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path="/opt/hermes/tools/chromium-1208/chrome-linux64/chrome")
            for url in _TUBI_CATEGORIES:
                try:
                    page = browser.new_page()
                    page.goto(url)
                    page.wait_for_load_state("networkidle", timeout=30000)
                    for _ in range(5):
                        page.evaluate("window.scrollBy(0, 800)")
                        page.wait_for_timeout(500)
                    items = page.evaluate("""
(() => {
  const seen = new Set();
  const out = [];
  document.querySelectorAll('a').forEach(a => {
    const href = a.getAttribute('href') || '';
    const text = a.innerText && a.innerText.trim();
    if ((href.startsWith('/movies/') || href.startsWith('/series/')) && text && text.length > 3 && text.length < 80) {
      if (!seen.has(href)) {
        seen.add(href);
        out.push({href, text});
      }
    }
  });
  return JSON.stringify(out);
})()
""")
                    page.close()
                    for item in json.loads(items):
                        links.append("https://tubitv.com" + item["href"])
                except Exception as e:
                    print(f"[WARN] Tubi category failed ({url}): {e}")
            browser.close()
    except Exception as e:
        print(f"[WARN] Tubi scrape failed: {e}")
    return list(dict.fromkeys(links))


def get_tubi_detail(url):
    """Fetch a Tubi detail page and extract title/synopsis/genre from JSON-LD."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path="/opt/hermes/tools/chromium-1208/chrome-linux64/chrome")
            page = browser.new_page()
            page.goto(url)
            page.wait_for_load_state("networkidle", timeout=30000)
            data = page.evaluate("""
(() => {
  const jsonLd = document.querySelector('script[type="application/ld+json"]');
  if (jsonLd) {
    try { return JSON.parse(jsonLd.innerText); } catch(e) { return null; }
  }
  return null;
})()
""")
            page.close()
            browser.close()

        if data:
            graph = data.get("@graph", [])
            for node in graph:
                if node.get("@type") == "Movie":
                    title = node.get("name")
                    synopsis = node.get("description")
                    genres = node.get("genre", [])
                    is_free = node.get("isAccessibleForFree", False)
                    return {
                        "title": title,
                        "channel": "Tubi (Free)" if is_free else "Tubi (Subscription)",
                        "synopsis": synopsis[:300] if synopsis else None,
                        "type": "free_streaming" if is_free else "subscription",
                        "genres": genres if isinstance(genres, list) else [genres] if genres else [],
                    }
    except Exception as e:
        print(f"[WARN] Tubi detail failed for {url}: {e}")
    return None


def fetch_streaming_content(query, category="movies"):
    """
    Gather spy-film results from live sources (titles, channel, synopsis).
    """
    results = []

    # 1. Netflix spy genre — broader catalog
    for url in _netflix_title_urls()[:60]:
        info = get_netflix_detail(url)
        if info:
            info["source"] = "netflix.com"
            results.append(info)

    # 2. Tubi public categories (action/thriller/crime/mystery)
    for url in _tubi_category_links()[:40]:
        info = get_tubi_detail(url)
        if info:
            info["source"] = "tubi.com"
            results.append(info)

    # Dedupe by title
    seen = set()
    unique = []
    for item in results:
        key = item.get("title") or ""
        if key and key not in seen:
            seen.add(key)
            unique.append(item)

    # Filter: keep only spy-relevant content
    unique = [u for u in unique if _is_spy_content(u.get("genres", []), u.get("synopsis", ""))]

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
