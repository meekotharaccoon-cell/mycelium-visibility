#!/usr/bin/env python3
"""
visibility_agent.py -- Autonomous Social Visibility Agent
==========================================================
Posts to Bluesky (AT Protocol), Mastodon (ActivityPub), and Dev.to.
Reads from data/content_queue.json, tracks posts in data/posts_log.json.

Can run standalone or be called by the nerve-center.
All API calls are real -- stdlib only, no external dependencies.

Environment variables:
  BLUESKY_IDENTIFIER     - Bluesky handle (e.g. meeko.bsky.social)
  BLUESKY_APP_PASSWORD   - Bluesky app password (generate at bsky.app/settings)
  MASTODON_ACCESS_TOKEN  - Mastodon access token
  MASTODON_INSTANCE      - Mastodon instance (default: mastodon.social)
  DEVTO_API_KEY          - Dev.to API key
"""

import os
import re
import json
import hashlib
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

QUEUE_FILE = DATA / "content_queue.json"
LOG_FILE   = DATA / "posts_log.json"

REPO_URL  = "https://github.com/meekotharaccoon-cell/meeko-nerve-center"
STORE_URL = "https://meekotharaccoon-cell.github.io/meeko-nerve-center"


# ---------------------------------------------------------------------------
# UTILITIES
# ---------------------------------------------------------------------------
def _now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _content_hash(text: str) -> str:
    """SHA-256 of post text -- used to deduplicate."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_queue() -> list:
    """Load the content queue. Returns list of post dicts."""
    if QUEUE_FILE.exists():
        try:
            data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else data.get("posts", [])
        except Exception:
            pass
    return []


def save_queue(posts: list):
    QUEUE_FILE.write_text(json.dumps(posts, indent=2, default=str), encoding="utf-8")


def load_log() -> dict:
    """Load posts log. Keys = content hashes, values = post metadata."""
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_log(log: dict):
    LOG_FILE.write_text(json.dumps(log, indent=2, default=str), encoding="utf-8")


def is_duplicate(text: str, log: dict) -> bool:
    return _content_hash(text) in log


# ---------------------------------------------------------------------------
# BLUESKY -- AT Protocol (https://bsky.social/xrpc/)
# ---------------------------------------------------------------------------
BSKY_HOST          = "https://bsky.social"
BLUESKY_IDENTIFIER = os.environ.get("BLUESKY_IDENTIFIER", "")
BLUESKY_APP_PASS   = os.environ.get("BLUESKY_APP_PASSWORD", "")


def _bsky_request(endpoint: str, payload: dict, token: str = None) -> dict:
    """POST to a Bluesky XRPC endpoint."""
    url  = f"{BSKY_HOST}/xrpc/{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def bsky_login() -> tuple:
    """Authenticate with Bluesky. Returns (access_token, did) or (None, None)."""
    if not BLUESKY_IDENTIFIER or not BLUESKY_APP_PASS:
        return None, None
    try:
        resp = _bsky_request("com.atproto.server.createSession", {
            "identifier": BLUESKY_IDENTIFIER,
            "password":   BLUESKY_APP_PASS,
        })
        return resp.get("accessJwt"), resp.get("did")
    except Exception as e:
        print(f"  [bluesky] login failed: {e}")
        return None, None


def _bsky_parse_facets(text: str) -> list:
    """Extract URL facets for richtext links in Bluesky posts."""
    facets = []
    for m in re.finditer(r"https?://\S+", text):
        start = len(text[:m.start()].encode("utf-8"))
        end   = len(text[:m.end()].encode("utf-8"))
        facets.append({
            "index": {"byteStart": start, "byteEnd": end},
            "features": [{
                "$type": "app.bsky.richtext.facet#link",
                "uri": m.group(),
            }],
        })
    return facets


def bsky_post(token: str, did: str, text: str) -> tuple:
    """Create a Bluesky post. Returns (success: bool, url_or_error: str)."""
    try:
        text = text[:300]
        record = {
            "$type":     "app.bsky.feed.post",
            "text":      text,
            "createdAt": _now_iso(),
        }
        facets = _bsky_parse_facets(text)
        if facets:
            record["facets"] = facets

        resp = _bsky_request("com.atproto.repo.createRecord", {
            "repo":       did,
            "collection": "app.bsky.feed.post",
            "record":     record,
        }, token=token)

        uri = resp.get("uri", "")
        if uri.startswith("at://"):
            parts = uri.replace("at://", "").split("/")
            if len(parts) == 3:
                return True, f"https://bsky.app/profile/{parts[0]}/post/{parts[2]}"
        return True, uri
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# MASTODON -- ActivityPub API (https://docs.joinmastodon.org/methods/statuses/)
# ---------------------------------------------------------------------------
MASTODON_TOKEN    = os.environ.get("MASTODON_ACCESS_TOKEN", "")
MASTODON_INSTANCE = os.environ.get("MASTODON_INSTANCE", "mastodon.social").rstrip("/")


def mastodon_post(text: str) -> tuple:
    """Post a status to Mastodon. Returns (success: bool, url_or_error: str)."""
    if not MASTODON_TOKEN:
        return False, "MASTODON_ACCESS_TOKEN not set"
    try:
        url  = f"https://{MASTODON_INSTANCE}/api/v1/statuses"
        data = urllib.parse.urlencode({"status": text[:500]}).encode("utf-8")
        req  = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {MASTODON_TOKEN}")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
            return True, body.get("url", "")
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# DEV.TO -- Forem API (https://developers.forem.com/api/v1)
# ---------------------------------------------------------------------------
DEVTO_API_KEY = os.environ.get("DEVTO_API_KEY", "")


def devto_post(title: str, body_markdown: str, tags: list = None) -> tuple:
    """Publish an article to Dev.to. Returns (success: bool, url_or_error: str)."""
    if not DEVTO_API_KEY:
        return False, "DEVTO_API_KEY not set"
    try:
        url = "https://dev.to/api/articles"
        payload = {
            "article": {
                "title":         title[:128],
                "body_markdown": body_markdown,
                "published":     True,
                "tags":          (tags or ["opensource", "ai", "python"])[:4],
            }
        }
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("api-key", DEVTO_API_KEY)
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
            return True, body.get("url", "")
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# MAIN DISPATCH
# ---------------------------------------------------------------------------
def run(max_posts_per_platform: int = 3):
    """
    Drain the content queue. Post each item to the platforms it targets.
    Skip duplicates. Log everything.
    """
    print("=" * 60)
    print(f"VISIBILITY AGENT -- {_now_iso()}")
    print("=" * 60)

    posts  = load_queue()
    log    = load_log()

    if not posts:
        print("  Queue empty -- nothing to post. Run content_generator.py first.")
        print("=" * 60)
        return {"bluesky": 0, "mastodon": 0, "devto": 0}

    # --- Bluesky session ---
    bsky_token, bsky_did = None, None
    if BLUESKY_IDENTIFIER and BLUESKY_APP_PASS:
        bsky_token, bsky_did = bsky_login()
        if bsky_token:
            print(f"  [bluesky] authenticated as {BLUESKY_IDENTIFIER}")
        else:
            print("  [bluesky] login failed -- will skip")
    else:
        print("  [bluesky] credentials not set -- skipping")

    if not MASTODON_TOKEN:
        print("  [mastodon] MASTODON_ACCESS_TOKEN not set -- skipping")
    else:
        print(f"  [mastodon] targeting {MASTODON_INSTANCE}")

    if not DEVTO_API_KEY:
        print("  [devto] DEVTO_API_KEY not set -- skipping")
    else:
        print("  [devto] API key configured")

    counts = {"bluesky": 0, "mastodon": 0, "devto": 0}
    updated_posts = []

    for post in posts:
        text      = post.get("text", "") or post.get("content", "")
        platforms = post.get("platforms", ["bluesky", "mastodon"])
        title     = post.get("title", "")
        tags      = post.get("tags", [])

        if not text:
            updated_posts.append(post)
            continue

        h = _content_hash(text)

        # --- Bluesky ---
        if ("bluesky" in platforms and bsky_token
                and counts["bluesky"] < max_posts_per_platform):
            if not post.get("sent_bluesky") and not is_duplicate(h + "_bsky", log):
                ok, url = bsky_post(bsky_token, bsky_did, text)
                post["sent_bluesky"] = True
                post["bsky_url"]     = url if ok else ""
                post["bsky_at"]      = _now_iso()
                log[h + "_bsky"] = {
                    "platform": "bluesky", "ok": ok,
                    "url": url, "at": _now_iso(),
                }
                counts["bluesky"] += 1
                tag = "OK" if ok else "FAIL"
                print(f"  [bluesky] {tag}: {(url or 'no url')[:80]}")

        # --- Mastodon ---
        if ("mastodon" in platforms and MASTODON_TOKEN
                and counts["mastodon"] < max_posts_per_platform):
            if not post.get("sent_mastodon") and not is_duplicate(h + "_masto", log):
                ok, url = mastodon_post(text)
                post["sent_mastodon"] = True
                post["mastodon_url"]  = url if ok else ""
                post["mastodon_at"]   = _now_iso()
                log[h + "_masto"] = {
                    "platform": "mastodon", "ok": ok,
                    "url": url, "at": _now_iso(),
                }
                counts["mastodon"] += 1
                tag = "OK" if ok else "FAIL"
                print(f"  [mastodon] {tag}: {(url or 'no url')[:80]}")

        # --- Dev.to ---
        if ("devto" in platforms and DEVTO_API_KEY
                and counts["devto"] < max_posts_per_platform):
            if not post.get("sent_devto") and not is_duplicate(h + "_devto", log):
                article_title = title or text[:60].rstrip() + "..."
                ok, url = devto_post(article_title, text, tags)
                post["sent_devto"] = True
                post["devto_url"]  = url if ok else ""
                post["devto_at"]   = _now_iso()
                log[h + "_devto"] = {
                    "platform": "devto", "ok": ok,
                    "url": url, "at": _now_iso(),
                }
                counts["devto"] += 1
                tag = "OK" if ok else "FAIL"
                print(f"  [devto] {tag}: {(url or 'no url')[:80]}")

        updated_posts.append(post)

    save_queue(updated_posts)
    save_log(log)

    total = sum(counts.values())
    print(f"\n  Totals -- bluesky: {counts['bluesky']}, "
          f"mastodon: {counts['mastodon']}, devto: {counts['devto']}")
    print(f"  Log entries: {len(log)}")
    print("=" * 60)
    return counts


if __name__ == "__main__":
    run()
