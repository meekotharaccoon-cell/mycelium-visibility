#!/usr/bin/env python3
"""
content_generator.py -- Generates post content for the visibility agent
========================================================================
Fetches live crypto prices from CoinGecko (free, no key needed).
Creates market commentary, project updates, and engagement posts.
Outputs to data/content_queue.json for visibility_agent.py to consume.

No external dependencies -- stdlib only.
"""

import json
import random
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

QUEUE_FILE = DATA / "content_queue.json"

REPO_URL  = "https://github.com/meekotharaccoon-cell/meeko-nerve-center"
STORE_URL = "https://meekotharaccoon-cell.github.io/meeko-nerve-center"


# ---------------------------------------------------------------------------
# UTILITIES
# ---------------------------------------------------------------------------
def _now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_json(url: str, timeout: int = 15) -> dict:
    """GET request that returns parsed JSON."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "mycelium-visibility/1.0")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# CRYPTO PRICES -- CoinGecko free API (no key required)
# ---------------------------------------------------------------------------
COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=bitcoin,ethereum,solana,dogecoin"
    "&vs_currencies=usd"
    "&include_24hr_change=true"
)


def fetch_crypto_prices() -> dict:
    """
    Fetch live prices from CoinGecko.
    Returns dict like: {"bitcoin": {"usd": 65432, "usd_24h_change": -1.23}, ...}
    """
    try:
        return _get_json(COINGECKO_URL)
    except Exception as e:
        print(f"  [crypto] CoinGecko fetch failed: {e}")
        return {}


def _format_price(price: float) -> str:
    if price >= 1000:
        return f"${price:,.0f}"
    elif price >= 1:
        return f"${price:.2f}"
    else:
        return f"${price:.4f}"


def _format_change(change: float) -> str:
    arrow = "+" if change >= 0 else ""
    return f"{arrow}{change:.1f}%"


# ---------------------------------------------------------------------------
# POST GENERATORS
# ---------------------------------------------------------------------------
def generate_crypto_posts(prices: dict) -> list:
    """Generate market commentary posts from live crypto data."""
    if not prices:
        return []

    posts = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # --- Market overview post ---
    lines = []
    for coin_id, label in [("bitcoin", "BTC"), ("ethereum", "ETH"),
                            ("solana", "SOL"), ("dogecoin", "DOGE")]:
        info = prices.get(coin_id, {})
        if "usd" in info:
            price  = _format_price(info["usd"])
            change = _format_change(info.get("usd_24h_change", 0))
            lines.append(f"{label}: {price} ({change})")

    if lines:
        overview = f"Crypto {ts}\n\n" + "\n".join(lines)
        overview += f"\n\nTracked by SolarPunk -- autonomous AI organism\n{REPO_URL}"
        posts.append({
            "text": overview,
            "platforms": ["bluesky", "mastodon"],
            "tags": ["crypto", "bitcoin", "ai"],
            "source": "content_generator:crypto_overview",
            "generated_at": _now_iso(),
        })

    # --- Biggest mover post ---
    movers = []
    for coin_id in prices:
        change = prices[coin_id].get("usd_24h_change", 0)
        movers.append((coin_id, change))
    movers.sort(key=lambda x: abs(x[1]), reverse=True)

    if movers and abs(movers[0][1]) > 2.0:
        coin, change = movers[0]
        price = _format_price(prices[coin]["usd"])
        direction = "surging" if change > 0 else "dropping"
        post_text = (
            f"{coin.upper()} is {direction} -- {_format_change(change)} "
            f"in the last 24h (now at {price}).\n\n"
            f"SolarPunk tracks this automatically every cycle.\n{REPO_URL}"
        )
        posts.append({
            "text": post_text,
            "platforms": ["bluesky", "mastodon"],
            "tags": ["crypto", coin],
            "source": "content_generator:crypto_mover",
            "generated_at": _now_iso(),
        })

    return posts


def generate_project_posts() -> list:
    """Generate posts about the SolarPunk project itself."""
    posts = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # -- Rotating project facts --
    project_facts = [
        (
            f"SolarPunk runs 24/7 on free GitHub Actions. "
            f"Every 6 hours: gather intel, build products, distribute, self-expand.\n\n"
            f"MIT licensed. Every line readable.\n{REPO_URL}"
        ),
        (
            f"15% of every SolarPunk sale goes to Palestinian children via PCRF. "
            f"Not a toggle. Hardcoded in the architecture.\n\n"
            f"EIN: 93-1057665. Verify it yourself.\n{STORE_URL}"
        ),
        (
            f"The system asks Claude what Python engine is missing. "
            f"Claude writes it. The system commits and runs it next cycle.\n\n"
            f"Self-expanding autonomous AI.\n{REPO_URL}"
        ),
        (
            f"SolarPunk has 8 execution layers:\n"
            f"L0: Self-heal\nL1: Gather intel\nL2: Revenue plan\n"
            f"L3: Build content\nL4: Distribute\nL5: Collect payment\n"
            f"L6: Self-expand\nL7: Report + prove\n\n{REPO_URL}"
        ),
        (
            f"Everything in SolarPunk costs $1. "
            f"Internet-scale math: 5B users x 0.001% x $1 = $50K.\n"
            f"Friction is the enemy. $1 removes it.\n\n{STORE_URL}"
        ),
        (
            f"An AI system cannot run itself forever. "
            f"But it can detect every failure mode and either fix it or skip it gracefully.\n\n"
            f"That is close enough.\n{REPO_URL}"
        ),
    ]

    # Pick 1-2 facts for today
    chosen = random.sample(project_facts, min(2, len(project_facts)))
    for text in chosen:
        posts.append({
            "text": text,
            "platforms": ["bluesky", "mastodon"],
            "tags": ["opensource", "ai", "python", "solarpunk"],
            "source": "content_generator:project_fact",
            "generated_at": _now_iso(),
        })

    return posts


def generate_devto_article(prices: dict) -> list:
    """Generate a Dev.to article combining crypto data + project update."""
    if not prices:
        return []

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Build a simple markdown article
    lines = [f"# SolarPunk Daily -- {ts}\n"]
    lines.append("## Market Snapshot\n")
    for coin_id, label in [("bitcoin", "BTC"), ("ethereum", "ETH"),
                            ("solana", "SOL"), ("dogecoin", "DOGE")]:
        info = prices.get(coin_id, {})
        if "usd" in info:
            price  = _format_price(info["usd"])
            change = _format_change(info.get("usd_24h_change", 0))
            lines.append(f"- **{label}**: {price} ({change})")

    lines.append("\n## What is SolarPunk?\n")
    lines.append(
        "An autonomous AI organism that runs on free GitHub infrastructure. "
        "Every 6 hours it wakes up, gathers intelligence, builds digital products, "
        "distributes content, and routes 15% of every sale to Palestinian children "
        "via PCRF (EIN: 93-1057665).\n"
    )
    lines.append(
        "The system writes its own new Python engines by asking Claude "
        "what capability is missing, then committing the answer.\n"
    )
    lines.append(f"**Source (MIT)**: [{REPO_URL}]({REPO_URL})\n")
    lines.append(f"**Store**: [{STORE_URL}]({STORE_URL})\n")

    body = "\n".join(lines)

    return [{
        "text": body,
        "title": f"SolarPunk Daily: Autonomous AI + Crypto Snapshot ({ts})",
        "platforms": ["devto"],
        "tags": ["opensource", "ai", "crypto", "python"],
        "source": "content_generator:devto_article",
        "generated_at": _now_iso(),
    }]


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def run():
    print("=" * 60)
    print(f"CONTENT GENERATOR -- {_now_iso()}")
    print("=" * 60)

    # Load existing queue (preserve unsent items)
    existing = []
    if QUEUE_FILE.exists():
        try:
            data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
            existing = data if isinstance(data, list) else data.get("posts", [])
        except Exception:
            pass

    # Keep only unsent posts from previous runs
    unsent = [p for p in existing
              if not (p.get("sent_bluesky") and p.get("sent_mastodon")
                      and p.get("sent_devto"))]
    print(f"  Existing unsent posts: {len(unsent)}")

    new_posts = []

    # 1. Fetch crypto prices
    print("  Fetching crypto prices from CoinGecko...")
    prices = fetch_crypto_prices()
    if prices:
        print(f"  Got prices for: {', '.join(prices.keys())}")
        # Save raw prices for reference
        (DATA / "crypto_prices.json").write_text(
            json.dumps({"fetched_at": _now_iso(), "prices": prices}, indent=2),
            encoding="utf-8",
        )
    else:
        print("  No crypto data -- will generate project posts only")

    # 2. Generate posts
    crypto_posts  = generate_crypto_posts(prices)
    project_posts = generate_project_posts()
    devto_posts   = generate_devto_article(prices)

    new_posts.extend(crypto_posts)
    new_posts.extend(project_posts)
    new_posts.extend(devto_posts)

    print(f"  Generated: {len(crypto_posts)} crypto, "
          f"{len(project_posts)} project, {len(devto_posts)} devto")

    # 3. Merge and save
    all_posts = unsent + new_posts
    QUEUE_FILE.write_text(
        json.dumps(all_posts, indent=2, default=str), encoding="utf-8"
    )

    print(f"  Total queue: {len(all_posts)} posts")
    print("=" * 60)
    return {"generated": len(new_posts), "total_queue": len(all_posts)}


if __name__ == "__main__":
    run()
