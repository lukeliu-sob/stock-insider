"""TP-035 live probe of the candidate news sources (never blocking).

For every candidate source: discover a feed (known URL, then the home
page's <link rel="alternate">, then common paths), parse it with
feedparser, and record entry counts, date coverage and link hosts.
For every body candidate: read robots.txt, fetch sample article pages
from the feed, and list the containers holding the most paragraph
text (input for the extraction templates). Every request goes through
the egress-checked page seam with its fixed User-Agent. The JSON
report goes to the path given as the first argument (default: stdout
summary only). Terms of use are not machine-checkable and are not
judged here.

Run: .venv/Scripts/python.exe test/live/probe_news_sources.py [report.json]

Implements: REQ-SI-FR-003, REQ-SI-FR-015, REQ-SI-SEC-003 (ADR-002)
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import feedparser
from bs4 import BeautifulSoup

from stockinsider.data.ingest.http import USER_AGENT, TransportError, stdlib_fetch_page
from stockinsider.shared.egress import EgressViolationError

#: (source_id, home page, known feed URLs, body candidate)
SOURCES: list[tuple[str, str, list[str], bool]] = [
    ("scmp", "https://www.scmp.com/", ["https://www.scmp.com/rss/91/feed", "https://www.scmp.com/rss/4/feed"], False),
    ("bbc", "https://www.bbc.co.uk/news/business", ["https://feeds.bbci.co.uk/news/business/rss.xml"], False),
    ("guardian", "https://www.theguardian.com/uk/business", ["https://www.theguardian.com/uk/business/rss"], False),
    ("cnbc", "https://www.cnbc.com/", ["https://www.cnbc.com/id/100003114/device/rss/rss.html"], True),
    ("marketwatch", "https://www.marketwatch.com/", [], True),
    ("standard", "https://www.thestandard.com.hk/", [], True),
    ("rthk", "https://news.rthk.hk/rthk/en/", ["https://rthk.hk/rthk/news/rss/e_expressnews_elocal.xml"], True),
    ("hkfp", "https://hongkongfp.com/", ["https://hongkongfp.com/feed/"], True),
    ("chinadailyhk", "https://www.chinadailyhk.com/", [], True),
    ("govhk", "https://www.news.gov.hk/eng/index.html", [], True),
]

COMMON_FEED_PATHS = ["/rss", "/rss.xml", "/feed", "/feed/", "/rss/feed", "/en/rss"]
PACE_SECONDS = 1.5


def fetch(url: str) -> dict[str, Any]:
    time.sleep(PACE_SECONDS)
    try:
        result = stdlib_fetch_page(url)
    except TransportError as exc:
        return {"ok": False, "kind": exc.kind, "status": exc.status, "error": str(exc)}
    except EgressViolationError as exc:
        return {"ok": False, "kind": "egress", "status": None, "error": str(exc)}
    return {
        "ok": True,
        "status": result.status,
        "body": result.body,
        "content_type": result.content_type,
        "final_url": result.final_url,
    }


def parse_feed(body: bytes) -> dict[str, Any]:
    parsed = feedparser.parse(body)
    entries = parsed.entries
    dated = [e for e in entries if e.get("published_parsed") or e.get("updated_parsed")]
    return {
        "bozo": bool(parsed.bozo),
        "version": parsed.version,
        "entries": len(entries),
        "dated": len(dated),
        "link_hosts": dict(Counter(urlparse(e.get("link", "")).hostname for e in entries).most_common(5)),
        "sample_titles": [e.get("title", "") for e in entries[:3]],
        "links": [e.get("link", "") for e in entries[:10]],
    }


def discover_feeds(home: str, body: bytes) -> list[str]:
    soup = BeautifulSoup(body, "html.parser")
    found = []
    for link in soup.find_all("link", rel=lambda v: v and "alternate" in v):
        kind = (link.get("type") or "").lower()
        if "rss" in kind or "atom" in kind:
            found.append(urljoin(home, link.get("href", "")))
    return found


def robots_for(url: str) -> RobotFileParser | None:
    parts = urlparse(url)
    fetched = fetch(f"{parts.scheme}://{parts.netloc}/robots.txt")
    if not fetched["ok"]:
        return None
    parser = RobotFileParser()
    parser.parse(fetched["body"].decode("utf-8", errors="replace").splitlines())
    return parser


def text_containers(body: bytes) -> list[dict[str, Any]]:
    soup = BeautifulSoup(body, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "aside", "header", "noscript"]):
        tag.decompose()
    scores: Counter[str] = Counter()
    for paragraph in soup.find_all("p"):
        parent = paragraph.parent
        if parent is None:
            continue
        key = f"{parent.name}.{'.'.join(parent.get('class') or [])}"
        scores[key] += len(paragraph.get_text(" ", strip=True))
    return [{"container": key, "chars": chars} for key, chars in scores.most_common(4)]


def probe_source(source_id: str, home: str, known: list[str], body_candidate: bool) -> dict[str, Any]:
    report: dict[str, Any] = {"source": source_id, "home": home, "feeds": [], "articles": []}
    home_fetch = fetch(home)
    report["home_status"] = home_fetch.get("status") if home_fetch["ok"] else home_fetch["kind"]
    candidates = list(known)
    if home_fetch["ok"]:
        candidates += [u for u in discover_feeds(home, home_fetch["body"]) if u not in candidates]
    if not candidates:
        root = f"{urlparse(home).scheme}://{urlparse(home).netloc}"
        candidates = [root + path for path in COMMON_FEED_PATHS]
    for feed_url in candidates[:6]:
        fetched = fetch(feed_url)
        entry: dict[str, Any] = {"url": feed_url}
        if not fetched["ok"]:
            entry.update({"ok": False, "kind": fetched["kind"], "status": fetched["status"]})
        else:
            entry.update({"ok": True, "status": fetched["status"], "final_url": fetched["final_url"]})
            entry.update(parse_feed(fetched["body"]))
        report["feeds"].append(entry)
    if body_candidate:
        links = next((f["links"] for f in report["feeds"] if f.get("ok") and f.get("entries")), [])
        if not links and home_fetch["ok"]:
            soup = BeautifulSoup(home_fetch["body"], "html.parser")
            host = urlparse(home).hostname or ""
            links = [
                urljoin(home, a["href"])
                for a in soup.find_all("a", href=True)
                if (urlparse(urljoin(home, a["href"])).hostname or "").endswith(host.removeprefix("www."))
                and len(urlparse(urljoin(home, a["href"])).path) > 30
            ][:10]
        robots = robots_for(links[0]) if links else robots_for(home)
        report["robots_fetched"] = robots is not None
        for article in links[:2]:
            allowed = robots.can_fetch(USER_AGENT, article) if robots is not None else None
            fetched = (
                fetch(article) if allowed is not False else {"ok": False, "kind": "robots-disallowed", "status": None}
            )
            row: dict[str, Any] = {"url": article, "robots_allowed": allowed}
            if fetched["ok"]:
                row.update({"status": fetched["status"], "bytes": len(fetched["body"])})
                row["containers"] = text_containers(fetched["body"])
            else:
                row.update({"kind": fetched["kind"], "status": fetched["status"]})
            report["articles"].append(row)
    return report


def main() -> int:
    reports = [probe_source(*source) for source in SOURCES]
    for report in reports:
        print(f"\n== {report['source']} home={report['home_status']}")
        for feed in report["feeds"]:
            if feed.get("ok"):
                print(
                    f"  feed {feed['url']} status={feed['status']} {feed['version']} entries={feed['entries']} "
                    f"dated={feed['dated']} bozo={feed['bozo']} hosts={feed['link_hosts']}"
                )
            else:
                print(f"  feed {feed['url']} FAIL {feed['kind']} {feed['status']}")
        for article in report["articles"]:
            print(f"  article robots={article['robots_allowed']} status={article.get('status')} {article['url']}")
            for container in article.get("containers", []):
                print(f"      {container['chars']:>6}  {container['container']}")
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as handle:
            json.dump(reports, handle, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
