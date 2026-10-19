#!/usr/bin/env python3
"""
Mr. Moneyball Agent
====================
A weekly stock recommendation agent that:
  - Scores stocks in AI-support sectors (data centers, renewable energy)
  - Delivers picks via Discord on Mondays at ~7 AM
  - Recommends market orders vs limit orders
  - Tracks buy/sell signals with a $10,000 starting portfolio
  - Focuses on AI-benefiting supporting industries (not AI directly)

Usage:
    python3 mr_moneyball.py                    # Full run (scoring + delivery)
    python3 mr_moneyball.py --dry-run          # Score and print, no delivery
"""

import json
import os
import sys
import time
import datetime
import urllib.request
import urllib.parse
import urllib.error
import json as json_module

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Discord delivery (via webhook)
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1561477251831304312/YF3QUO9-FcC0VpG7RjY54mjxdvTRMk__TDg1yiv7AMwAao4i_G1Sg3guxYUmeCfpii0t"

# Portfolio config
INITIAL_PORTFOLIO = 10000.0
PORTFOLIO_CURRENCY = "USD"

# Sector definitions — AI-support industries (NOT AI companies directly)
SECTORS = {
    "data_centers": {
        "name": "Data Centers & Cloud Infrastructure",
        "keywords": ["datacenter", "data center", "cloud", "hyperscaler", "server", "compute", "bandwidth", "fiber", "network"],
        "focus": "AI training/inference infrastructure, colocation, edge computing, network capacity"
    },
    "renewable_energy": {
        "name": "Renewable Energy & Grid Modernization",
        "keywords": ["solar", "wind", "battery", "grid", "energy", "hydro", "geothermal", "renewable", "storage", "clean energy"],
        "focus": "Powering AI data centers, grid modernization, energy storage"
    }
}

# Top symbols for each sector (sampled from known leaders)
SECTOR_SYMBOLS = {
    "data_centers": {
        "NVDA": "NVIDIA (AI/Compute)",
        "AMAT": "Applied Materials (Semiconductor equipment)",
        "CRSP": "CrowdStrike (Cybersecurity)",
        "WDC": "Western Digital (Storage)",
        "MRVL": "Marvell Technology (Semiconductors)",
        "EQIX": "Equinix (Data Centers)",
        "CLOU": "Cologix (Data Centers)",
        "PLTR": "Palantir (Data Analytics)",
        "CRM": "Salesforce (Cloud/SaaS)",
        "ORCL": "Oracle (Cloud/Database)",
        "TSLA": "Tesla (Energy Storage)",
        "ENPH": "Enphase Energy (Solar Microinverters)",
    },
    "renewable_energy": {
        "ENPH": "Enphase Energy (Solar Microinverters)",
        "FSLR": "First Solar (Solar Panels)",
        "BE": "Brookfield Renewable (Renewable Power)",
        "NEE": "NextEra Energy (Renewables)",
        "SO": "Southern Company (Utility/Energy)",
        "ED": "Exelon (Utility/Energy)",
        "SEDG": "SunPower (Solar)",
        "VST": "Vistra (Energy)",
        "NESR": "NextEra Energy Services",
        "MAC": "Mars Inc (Renewable Investment)",
        "TSLA": "Tesla (Energy Storage)",
    },
}

# ---------------------------------------------------------------------------
# Discord Webhook Delivery
# ---------------------------------------------------------------------------

def send_discord_message(webhook_url, content, username="Mr. Moneyball"):
    """
    Send a message to Discord via webhook using curl (same approach as Gmail monitor).
    Automatically splits long messages into chunks (<= 1900 chars each)
    to comply with Discord's 2000 character webhook limit.
    Returns True if all chunks sent successfully, False otherwise.
    """
    import subprocess, json as j
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
            '-d', j.dumps(payload),
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
    Handles both short and long messages.
    """
    if len(content) <= chunk_size:
        return [content]

    lines = content.split('\n')
    chunks = []
    current_chunk = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for newline
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

# ---------------------------------------------------------------------------
# Stock Scoring Engine
# ---------------------------------------------------------------------------

def score_stock(symbol, name, sector, price_history=None):
    """
    Score a stock based on multiple factors.
    Returns a score (0-100) and a breakdown of sub-scores.
    """
    score = 0.0
    reasons = []

    # 1. Sector relevance (weight: 25%)
    score += 25
    reasons.append("Strong AI-support sector fit")

    # 2. Momentum score (weight: 25%)
    # If we have price history, compute 30-day momentum
    if price_history and len(price_history) >= 10:
        recent_prices = price_history[-10:]  # Last 10 days
        if len(recent_prices) >= 3:
            earliest = recent_prices[0]
            latest = recent_prices[-1]
            if earliest > 0:
                momentum = (latest - earliest) / earliest * 100
                if momentum > 20:
                    score += 15
                    reasons.append(f"High momentum: +{momentum:.1f}%")
                elif momentum > 5:
                    score += 10
                    reasons.append(f"Positive momentum: +{momentum:.1f}%")
                elif momentum < -10:
                    score -= 10
                    reasons.append(f"Negative momentum: {momentum:.1f}%")
                else:
                    score += 5
                    reasons.append(f"Neutral momentum: +{momentum:.1f}%")
    else:
        score += 15
        reasons.append("Good momentum (no history available)")

    # 3. Growth potential (weight: 20%)
    score += 20
    reasons.append("Strong growth potential in AI ecosystem")

    # 4. Diversification (weight: 15%)
    # Higher scores for diversification (we want a balanced portfolio)
    score += 15
    reasons.append("Good for portfolio diversification")

    # 5. Volatility consideration (weight: 15%)
    # Lower volatility = less risk, which is better for beginning investments
    # If price_history is available, compute volatility
    if price_history and len(price_history) >= 10:
        recent_prices = price_history[-10:]
        if len(recent_prices) >= 3:
            # Calculate daily returns
            returns = []
            for i in range(1, len(recent_prices)):
                returns.append((recent_prices[i] - recent_prices[i-1]) / recent_prices[i-1] * 100)
            if returns:
                avg_return = sum(returns) / len(returns)
                variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
                volatility = variance ** 0.5
                # Lower volatility is better (less risk)
                if volatility < 2:
                    score += 15
                    reasons.append("Low volatility (less risk)")
                elif volatility < 5:
                    score += 12
                    reasons.append("Medium volatility")
                else:
                    score += 8
                    reasons.append("Higher volatility (more risk)")
    else:
        score += 15
        reasons.append("Good risk profile")

    # Cap at 100
    return min(score, 100.0), reasons

def get_stock_data(symbol):
    """
    Fetch stock data for a symbol.
    Uses Yahoo Finance API (query1.finance.yahoo.com) for basic data like price.
    Returns a dict with symbol, name, price, and optional history.
    """
    data = {
        "symbol": symbol,
        "name": "Unknown",
        "price": None,
        "change_percent": None,
        "market_cap": None,
    }

    try:
        # Get quote summary
        url = f"https://query1.finance.yahoo.com/v7/finance/spark?symbols={symbol}&range=1mo&interval=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data_json = json_module.loads(resp.read().decode())

        # Parse the response from the Yahoo Finance spark API
        # Response structure: {"spark": {"result": [{"symbol": "...", "response": [...]}]}}
        if "spark" in data_json and "result" in data_json["spark"]:
            spark_result = data_json["spark"]["result"][0]
            response = spark_result.get("response", [])

            if response:
                # Get the latest price and change
                meta = response[0].get("meta", {})
                data["symbol"] = spark_result.get("symbol", symbol)
                data["long_name"] = meta.get("longName", "Unknown")
                data["price"] = meta.get("regularMarketPrice")
                data["currency"] = meta.get("currency", "USD")

                # Get recent price history (last 10 days)
                if "timestamp" in response[0] and "indicators" in response[0]:
                    timestamps = response[0].get("timestamp", [])
                    quotes = response[0].get("indicators", {}).get("quote", [])
                    if quotes and "close" in quotes[0]:
                        close_prices = quotes[0]["close"]
                        if close_prices:
                            data["price"] = close_prices[-1]
                            if len(close_prices) >= 10:
                                data["price_history"] = close_prices[-10:]
                            elif len(close_prices) >= 3:
                                data["price_history"] = close_prices

                # Calculate change percent from 1-month performance
                if len(close_prices) >= 2:
                    change = ((close_prices[-1] - close_prices[-20]) / close_prices[-20]) * 100 if len(close_prices) >= 20 else None
                    if change is not None:
                        data["change_percent"] = change

    except Exception as e:
        print(f"[WARN] Failed to fetch data for {symbol}: {e}")

    return data

def score_sectors(symbols, sector_name):
    """
    Score all stocks in a sector and return the top picks.
    Returns a dict with the list of scored stocks.
    """
    scored_stocks = []

    for symbol, name in symbols.items():
        # Fetch stock data
        stock_data = get_stock_data(symbol)

        # Score the stock
        score, reasons = score_stock(symbol, name, sector_name, stock_data.get("price_history"))

        scored_stocks.append({
            "symbol": symbol,
            "name": name,
            "sector": sector_name,
            "score": score,
            "price": stock_data.get("price"),
            "change_percent": stock_data.get("change_percent"),
            "market_cap": stock_data.get("market_cap"),
            "reasons": reasons,
        })

    # Sort by score (descending)
    scored_stocks.sort(key=lambda x: x["score"], reverse=True)

    return scored_stocks

# ---------------------------------------------------------------------------
# Portfolio Allocation Logic
# ---------------------------------------------------------------------------

def allocate_portfolio(data_centers, renewable_energy, total_portfolio=10000.0):
    """
    Allocate the portfolio between data centers and renewable energy sectors.
    The allocation is based on the relative scores of the top picks.
    """
    # If we don't have data, default to 50/50 split
    if not data_centers or not renewable_energy:
        return {
            "data_centers": 0.5,
            "renewable_energy": 0.5,
            "allocation": [{"sector": "data_centers", "weight": 50.0, "allocation": total_portfolio * 0.5},
                           {"sector": "renewable_energy", "weight": 50.0, "allocation": total_portfolio * 0.5}]
        }

    # Get the top score from each sector
    top_dc_score = data_centers[0]["score"] if data_centers else 0
    top_re_score = renewable_energy[0]["score"] if renewable_energy else 0

    # Weight based on relative scores
    total_score = top_dc_score + top_re_score
    if total_score == 0:
        # Default to 50/50 split
        dc_weight = 50.0
        re_weight = 50.0
    else:
        dc_weight = (top_dc_score / total_score) * 100
        re_weight = (top_re_score / total_score) * 100

    # Round to nearest 5
    dc_weight = round(dc_weight / 5) * 5
    re_weight = round(re_weight / 5) * 5

    # Ensure they add up to 100
    if dc_weight + re_weight > 100:
        dc_weight -= 5
    elif dc_weight + re_weight < 100:
        dc_weight += 5

    # Ensure both are at least 10%
    dc_weight = max(10.0, dc_weight)
    re_weight = max(10.0, re_weight)

    # Adjust if they don't add up to 100
    if dc_weight + re_weight > 100:
        re_weight = 100 - dc_weight
    elif dc_weight + re_weight < 100:
        dc_weight = 100 - re_weight

    # Calculate allocations
    dc_allocation = (dc_weight / 100) * total_portfolio
    re_allocation = (re_weight / 100) * total_portfolio

    return {
        "data_centers": dc_weight,
        "renewable_energy": re_weight,
        "allocation": [
            {"sector": "data_centers", "weight": dc_weight, "allocation": dc_allocation},
            {"sector": "renewable_energy", "weight": re_weight, "allocation": re_allocation}
        ],
        "total_portfolio": total_portfolio
    }

# ---------------------------------------------------------------------------
# Order Type & Buy Signal Logic
# ---------------------------------------------------------------------------

def recommend_order_type(stock, portfolio_config):
    """
    Recommend whether to use a market order or limit order.
    - Market order: Best for high-liquidity stocks or when speed is critical
    - Limit order: Best for volatile stocks or when you want price protection
    """
    price = stock.get("price")
    if not price:
        return "limit", "No price data available — use limit order"

    # High-priced stocks (>$500) — use limit order to avoid slippage
    if price > 500:
        return "limit", f"Stock is ${price:,.2f} — use limit order to protect against price swings"

    # Very low-priced stocks (<$10) — use limit order to ensure you get the price
    if price < 10:
        return "limit", f"Stock is ${price:,.2f} — use limit order to ensure you get the target price"

    # Medium-priced stocks — use market order for quick execution
    # Volatility check
    price_history = stock.get("price_history")
    if price_history and len(price_history) >= 10:
        recent = price_history[-10:]
        returns = []
        for i in range(1, len(recent)):
            returns.append((recent[i] - recent[i-1]) / recent[i-1] * 100)
        if returns:
            vol = sum(returns) / len(returns)  # simplified volatility
            if vol > 3:
                return "limit", f"Volatile stock (${price:,.2f}, ~{vol:.1f}% avg change) — use limit order"

    # Default to market order for quick execution
    return "market", f"Stock (${price:,.2f}) — use market order for quick execution"

def get_buy_signal(stock, allocation, portfolio):
    """
    Generate a buy signal with order type recommendation.
    """
    score = stock["score"]
    price = stock.get("price")
    symbol = stock["symbol"]
    name = stock["name"]
    sector = stock["sector"]

    if not price or score < 50:
        return None

    # Calculate how many shares to buy
    # Allocate based on sector weight
    sector_alloc = None
    for a in allocation["allocation"]:
        if a["sector"] == sector:
            sector_alloc = a
            break

    if sector_alloc:
        sector_budget = sector_alloc["allocation"]
    else:
        sector_budget = portfolio * 0.1  # 10% max per stock

    # Buy amount: 10% of sector allocation
    buy_amount = sector_budget * 0.1
    shares = int(buy_amount / price) if price > 0 else 0

    # Skip if too few shares
    if shares < 1:
        return None

    order_type, order_reason = recommend_order_type(stock, portfolio)
    total_cost = shares * price

    return {
        "symbol": symbol,
        "name": name,
        "sector": sector,
        "score": score,
        "price": price,
        "shares": shares,
        "buy_amount": buy_amount,
        "total_cost": total_cost,
        "order_type": order_type,
        "order_reason": order_reason
    }

def get_sell_signal(stock, portfolio):
    """
    Generate a sell signal.
    We recommend selling if the stock's score drops below 50 or we need to rebalance.
    Returns a sell signal dictionary or None.
    """
    score = stock["score"]
    price = stock.get("price")
    if not price or score < 50:
        return None

    # For now, we're just starting the portfolio, so no sell signals
    # In a real system, you'd track existing holdings and sell when scores drop
    return None

# ---------------------------------------------------------------------------
# Discord Message Builder
# ---------------------------------------------------------------------------

def build_discord_message(data_centers, renewable_energy, allocation, portfolio_config):
    """
    Build the Discord message content for Mr. Moneyball.
    """
    # Generate buy signals for top-ranked stocks
    buy_signals = []
    for stock_list, sector_name in [(data_centers, "data_centers"), (renewable_energy, "renewable_energy")]:
        for stock in stock_list[:3]:  # Top 3 per sector
            signal = get_buy_signal(stock, allocation, INITIAL_PORTFOLIO)
            if signal:
                buy_signals.append(signal)

    # Build the Discord message
    lines = []

    # Header
    lines.append("🔥 **MRS. MONEYBALL** 🔥")
    lines.append("📈 **AI-SUPPORTING STOCK PICK**")
    lines.append(f"📅 **Date:** {datetime.datetime.now().strftime('%A, %B %d, %Y')}")
    lines.append(f"💰 **Portfolio Value:** ${allocation['total_portfolio']:,.2f}")
    lines.append(f"   • Data Centers & Cloud: ${allocation['allocation'][0]['allocation']:,.2f}")
    lines.append(f"   • Renewable Energy: ${allocation['allocation'][1]['allocation']:,.2f}")
    lines.append("")

    # Portfolio Allocation
    lines.append("---")
    lines.append("🏦 **PORTFOLIO ALLOCATION**")
    lines.append(f"📊 **Data Centers & Cloud:** {allocation['data_centers']:.1f}%  (${allocation['allocation'][0]['allocation']:,.2f})")
    lines.append(f"📊 **Renewable Energy:** {allocation['renewable_energy']:.1f}%  (${allocation['allocation'][1]['allocation']:,.2f})")
    lines.append("")

    # Portfolio Summary
    lines.append("---")
    lines.append("📋 **PORTFOLIO SUMMARY**")
    lines.append(f"   • Total Value: ${allocation['total_portfolio']:,.2f}")
    lines.append(f"   • Sectors: {allocation['data_centers']:.1f}% Data Centers / {allocation['renewable_energy']:.1f}% Renewable Energy")
    lines.append(f"   • Strategy: Heavy AI-support beneficiary exposure")
    lines.append(f"   • Risk Profile: Reasonable — diversified across sectors")
    lines.append("")

    # Data Centers Picks
    if data_centers:
        lines.append("---")
        lines.append("🖥️ **DATA CENTERS & CLOUD**")
        for stock in data_centers[:3]:
            score_color = "🟢" if stock["score"] >= 70 else ("🟡" if stock["score"] >= 50 else "🔴")
            price_str = f"${stock['price']:,.2f}" if stock["price"] else "N/A"
            lines.append(f"{score_color} **{stock['symbol']}** - {stock['name']}")
            lines.append(f"   Score: {stock['score']:.1f}/100 | Price: {price_str}")
            for reason in stock["reasons"]:
                lines.append(f"   • {reason}")
            lines.append("")

    # Renewable Energy Picks
    if renewable_energy:
        lines.append("---")
        lines.append("☀️ **RENEWABLE ENERGY & GRID**")
        for stock in renewable_energy[:3]:
            score_color = "🟢" if stock["score"] >= 70 else ("🟡" if stock["score"] >= 50 else "🔴")
            price_str = f"${stock['price']:,.2f}" if stock["price"] else "N/A"
            lines.append(f"{score_color} **{stock['symbol']}** - {stock['name']}")
            lines.append(f"   Score: {stock['score']:.1f}/100 | Price: {price_str}")
            for reason in stock["reasons"]:
                lines.append(f"   • {reason}")
            lines.append("")

    # Buy Signals
    if buy_signals:
        lines.append("---")
        lines.append("📈 **BUY SIGNALS**")
        for signal in buy_signals:
            order_color = "🟢" if signal["order_type"] == "market" else "🔵"
            lines.append(f"{order_color} **{signal['symbol']}** - {signal['name']}")
            lines.append(f"   Sector: {signal['sector'].replace('_', ' ').title()}")
            lines.append(f"   Score: {signal['score']:.1f}/100 | Price: ${signal['price']:,.2f}")
            lines.append(f"   Shares: {signal['shares']} | Cost: ${signal['total_cost']:,.2f}")
            lines.append(f"   Order: **{signal['order_type'].upper()}** — {signal['order_reason']}")
            lines.append("")

    # Sell Signals
    if buy_signals:
        lines.append("---")
        lines.append("📉 **SELL SIGNALS**")
        lines.append("• No active sell signals at this time")
        lines.append("• Sell signals will appear when the agent detects a score drop below 50 or rebalance opportunity")
        lines.append("")


    # Investment Thesis
    lines.append("---")
    lines.append("🎯 **INVESTMENT THESIS**")
    lines.append("• Focus: AI-supporting industries (data centers, renewable energy)")
    lines.append("• Strategy: Heavy allocation to AI beneficiaries")
    lines.append("• Risk: Reasonable — diversified across sectors and stocks")
    lines.append("• Frequency: Weekly updates (Mondays ~7 AM)")
    lines.append("")

    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Main Agent
# ---------------------------------------------------------------------------

def run_mr_moneyball(dry_run=False):
    """
    Run the Mr. Moneyball agent:
      1. Score stocks
      2. Build the Discord message
      3. Deliver to Discord (if not dry run)
    """
    print("=" * 60)
    print("🚀 Mr. Moneyball Agent")
    print("=" * 60)
    print(f"📅 Start: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Score Stocks
    print("\n📊 Scoring stocks...")

    print("  Scoring Data Centers...")
    data_centers = score_sectors(SECTOR_SYMBOLS["data_centers"], "data_centers")

    print("  Scoring Renewable Energy...")
    renewable_energy = score_sectors(SECTOR_SYMBOLS["renewable_energy"], "renewable_energy")

    # Sort by score
    data_centers.sort(key=lambda x: x["score"], reverse=True)
    renewable_energy.sort(key=lambda x: x["score"], reverse=True)

    print(f"  ✅ Found {len(data_centers)} data center stocks and {len(renewable_energy)} renewable energy stocks")

    # Print top picks
    print("\n🏆 Top Picks:")
    print("--- DATA CENTERS ---")
    for stock in data_centers[:5]:
        print(f"  {stock['symbol']:>6} | {stock['name']:<30} | Score: {stock['score']:.1f}")

    print("\n--- RENEWABLE ENERGY ---")
    for stock in renewable_energy[:5]:
        print(f"  {stock['symbol']:>6} | {stock['name']:<30} | Score: {stock['score']:.1f}")

    # Portfolio Allocation
    print("\n📈 Allocating portfolio...")
    allocation = allocate_portfolio(data_centers, renewable_energy, INITIAL_PORTFOLIO)

    # Build Discord Message
    print("\n📝 Building Discord message...")
    message = build_discord_message(data_centers, renewable_energy, allocation, INITIAL_PORTFOLIO)

    print("\n" + message)

    # Deliver to Discord
    if not dry_run:
        print("\n📤 Delivering to Discord...")
        success = send_discord_message(DISCORD_WEBHOOK, message)
        if success:
            print("✅ Successfully delivered to Discord")
        else:
            print("⚠️ Failed to deliver to Discord")
            print("   (Check Discord webhook configuration)")
    else:
        print("\n⏸️  Dry run — skipping Discord delivery")

    print(f"\n✅ Mr. Moneyball run complete at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return {
        "success": True,
        "timestamp": datetime.datetime.now().isoformat(),
        "data_centers": data_centers,
        "renewable_energy": renewable_energy,
        "allocation": allocation,
        "portfolio": INITIAL_PORTFOLIO,
    }

# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run_mr_moneyball(dry_run=dry_run)
