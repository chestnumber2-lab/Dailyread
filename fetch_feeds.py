#!/usr/bin/env python3
"""Fetch articles from the RSS/Atom feeds in feeds.json and write docs/articles.json.

Run:  python fetch_feeds.py
Test: python fetch_feeds.py --feeds my_test_feeds.json --out /tmp/articles.json

Each run merges new items into the existing articles.json, so the archive keeps
growing until items are older than `keep_days`.
"""
import argparse
import hashlib
import html
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser

USER_AGENT = "Mozilla/5.0 (compatible; DailyReadBot/1.0; +personal news reader)"
TIMEOUT = 25
TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|cmp$|share$)", re.I)
TAG_RE = re.compile(r"<[^>]+>")
IMG_RE = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.I)
WS_RE = re.compile(r"\s+")


def clean_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw or "")
    text = html.unescape(TAG_RE.sub(" ", raw))
    return WS_RE.sub(" ", text).strip()


def truncate(text: str, limit: int = 320) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:-— ")
    return cut + "…"


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not TRACKING.match(k)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, urlencode(query), ""))


def entry_date(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _http_url(url):
    """Accept only absolute http(s) URLs (upgrading protocol-relative ones)."""
    if not url:
        return None
    url = html.unescape(url.strip())
    if url.startswith("//"):
        url = "https:" + url
    return url if url.startswith(("http://", "https://")) else None


def entry_image(entry, body_html: str):
    for key in ("media_content", "media_thumbnail"):
        for item in entry.get(key, []) or []:
            if item.get("medium", "image") == "image" or key == "media_thumbnail":
                url = _http_url(item.get("url"))
                if url:
                    return url
    for link in entry.get("links", []) or []:
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image"):
            url = _http_url(link.get("href"))
            if url:
                return url
    for match in IMG_RE.finditer(body_html or ""):
        url = _http_url(match.group(1))
        if url:
            return url
    return None


def entry_body(entry) -> str:
    content = entry.get("content")
    if content:
        return max((c.get("value", "") for c in content), key=len)
    return entry.get("summary", "") or entry.get("description", "")


def fetch_one(feed: dict, settings: dict):
    """Return (feed_status, [articles])."""
    status = {"name": feed["name"], "category": feed["category"], "ok": False, "count": 0, "error": None}
    try:
        req = urllib.request.Request(feed["url"], headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
        parsed = feedparser.parse(data)
        if not parsed.entries:
            raise ValueError("no entries found (bad URL or not a feed)")

        include = re.compile(feed["include"], re.I) if feed.get("include") else None
        exclude = re.compile(feed["exclude"], re.I) if feed.get("exclude") else None
        limit = feed.get("max_items", settings["max_items_per_feed"])
        weight = feed.get("weight", 2)

        articles = []
        for entry in parsed.entries:
            title = clean_text(entry.get("title", ""))
            link = entry.get("link", "")
            if not title or not link.startswith(("http://", "https://")):
                continue
            body_html = entry_body(entry)
            body_text = clean_text(body_html)
            blob = f"{title} {body_text}"
            if include and not include.search(blob):
                continue
            if exclude and exclude.search(blob):
                continue
            url = normalize_url(link)
            summary = truncate(clean_text(entry.get("summary", "")) or body_text)
            published = entry_date(entry)
            words = len(body_text.split())
            articles.append({
                "id": hashlib.sha1(url.encode()).hexdigest()[:16],
                "title": title,
                "url": url,
                "source": feed["name"],
                "category": feed["category"],
                "weight": weight,
                "published": published.isoformat(timespec="seconds"),
                "summary": summary,
                "image": entry_image(entry, body_html),
                # Only trust reading time when the feed ships the full text.
                "minutes": max(1, round(words / 220)) if words >= 600 else None,
                "author": clean_text(entry.get("author", "")) or None,
            })
            if len(articles) >= limit:
                break
        status.update(ok=True, count=len(articles))
        return status, articles
    except Exception as exc:  # one broken feed must never stop the run
        status["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return status, []


def score(article: dict, now: datetime) -> float:
    """Higher = surface sooner. Source quality dominates, freshness breaks ties."""
    age_h = max(0.0, (now - datetime.fromisoformat(article["published"])).total_seconds() / 3600)
    freshness = max(0.0, 1 - age_h / 72)  # fades to 0 after 3 days
    value = article["weight"] * 10 + freshness * 12
    if article.get("image"):
        value += 1
    if len(article.get("summary", "")) > 120:
        value += 2
    if article.get("minutes"):
        value += 2
    return round(value, 2)


def main() -> int:
    root = Path(__file__).parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--feeds", default=str(root / "feeds.json"))
    ap.add_argument("--out", default=str(root / "docs" / "articles.json"))
    args = ap.parse_args()

    config = json.loads(Path(args.feeds).read_text(encoding="utf-8"))
    settings = {"keep_days": 30, "max_items_per_feed": 15, "max_total": 1500, **config.get("settings", {})}
    out_path = Path(args.out)

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda f: fetch_one(f, settings), config["feeds"]))

    statuses = [s for s, _ in results]
    fresh = [a for _, items in results for a in items]
    ok = sum(s["ok"] for s in statuses)
    for s in statuses:
        mark = "ok  " if s["ok"] else "FAIL"
        print(f"[{mark}] {s['name']:<32} {s['count']:>3} items" + (f"  — {s['error']}" if s["error"] else ""))

    if ok == 0:
        print("All feeds failed; keeping the previous articles.json untouched.", file=sys.stderr)
        return 1

    # Merge with the archive from earlier runs.
    merged = {}
    if out_path.exists():
        try:
            for a in json.loads(out_path.read_text(encoding="utf-8")).get("articles", []):
                merged[a["id"]] = a
        except (json.JSONDecodeError, KeyError):
            pass
    for a in fresh:
        merged[a["id"]] = a

    # Same story from two feeds (e.g. Ars index + Ars science): keep the higher-weighted copy.
    by_title = {}
    for a in merged.values():
        key = re.sub(r"\W+", "", a["title"].lower())
        if key not in by_title or a["weight"] > by_title[key]["weight"]:
            by_title[key] = a

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=settings["keep_days"])
    articles = [a for a in by_title.values() if datetime.fromisoformat(a["published"]) >= cutoff]
    for a in articles:
        a["score"] = score(a, now)
    articles.sort(key=lambda a: a["published"], reverse=True)
    articles = articles[: settings["max_total"]]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated": now.isoformat(timespec="seconds"),
        "feeds": statuses,
        "articles": articles,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"\n{ok}/{len(statuses)} feeds ok · {len(fresh)} fetched · {len(articles)} in archive → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
