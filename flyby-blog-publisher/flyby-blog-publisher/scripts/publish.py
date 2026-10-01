#!/usr/bin/env python3
"""
Publishes the next queued blog post to a self-hosted WordPress site via the
REST API, using an Application Password (Basic Auth). Designed to run inside
GitHub Actions on a daily schedule.

Queue format: markdown files in posts_queue/*.md with YAML frontmatter:
---
title: "Post title"
slug: "post-url-slug"
meta_description: "Short SEO meta description"
categories: ["Pilot Training"]
tags: ["CPL", "DGCA"]
---
Body content in markdown/HTML goes here...

Already-published files are moved to posts_queue/published/ by this script,
and the workflow commits that move back to the repo so the next run knows
what's left.
"""
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
QUEUE_DIR = REPO_ROOT / "posts_queue"
PUBLISHED_DIR = QUEUE_DIR / "published"

WP_SITE_URL = os.environ.get("WP_SITE_URL", "").rstrip("/")
WP_USERNAME = os.environ.get("WP_USERNAME", "")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "")


def die(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def parse_frontmatter(text):
    """Minimal YAML-ish frontmatter parser (no external deps)."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not m:
        die("post file is missing --- frontmatter block")
    fm_raw, body = m.group(1), m.group(2)

    meta = {}
    for line in fm_raw.splitlines():
        line = line.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        # list syntax: ["a", "b"]
        if value.startswith("[") and value.endswith("]"):
            items = [v.strip().strip('"').strip("'") for v in value[1:-1].split(",") if v.strip()]
            meta[key] = items
        else:
            meta[key] = value.strip('"').strip("'")
    return meta, body.strip()


def wp_request(path, method="GET", payload=None):
    url = f"{WP_SITE_URL}/wp-json/wp/v2/{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    token = base64.b64encode(f"{WP_USERNAME}:{WP_APP_PASSWORD}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        die(f"WordPress API {method} {path} failed ({e.code}): {body}")


def get_or_create_term(taxonomy, name):
    """taxonomy: 'categories' or 'tags'"""
    existing = wp_request(f"{taxonomy}?search={urllib.parse.quote(name)}")
    for term in existing:
        if term["name"].strip().lower() == name.strip().lower():
            return term["id"]
    created = wp_request(taxonomy, method="POST", payload={"name": name})
    return created["id"]


def next_post_file():
    if not QUEUE_DIR.exists():
        die(f"queue directory not found: {QUEUE_DIR}")
    candidates = sorted(p for p in QUEUE_DIR.glob("*.md") if p.is_file())
    return candidates[0] if candidates else None


def main():
    missing = [n for n in ("WP_SITE_URL", "WP_USERNAME", "WP_APP_PASSWORD") if not os.environ.get(n)]
    if missing:
        die(f"missing required environment variables: {', '.join(missing)}")

    post_file = next_post_file()
    if post_file is None:
        print("Queue is empty — nothing to publish today. Add more .md files to posts_queue/.")
        return

    text = post_file.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)

    title = meta.get("title") or post_file.stem
    slug = meta.get("slug") or None
    meta_description = meta.get("meta_description", "")

    category_ids = [get_or_create_term("categories", c) for c in meta.get("categories", [])]
    tag_ids = [get_or_create_term("tags", t) for t in meta.get("tags", [])]

    payload = {
        "title": title,
        "content": body,
        "status": "publish",
        "categories": category_ids,
        "tags": tag_ids,
    }
    if slug:
        payload["slug"] = slug
    # Yoast SEO / RankMath both read meta_description via their own meta keys;
    # this generic 'excerpt' also covers themes that show it as a snippet.
    if meta_description:
        payload["excerpt"] = meta_description

    result = wp_request("posts", method="POST", payload=payload)
    link = result.get("link", "(no link returned)")
    print(f"Published: {title}")
    print(f"URL: {link}")

    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    post_file.rename(PUBLISHED_DIR / post_file.name)
    print(f"Moved {post_file.name} to posts_queue/published/")


if __name__ == "__main__":
    main()
def next_post_file():
    if not QUEUE_DIR.exists():
        die(f"queue directory not found: {QUEUE_DIR}")
    candidates = sorted(
        p for p in QUEUE_DIR.rglob("*.md")
        if p.is_file() and PUBLISHED_DIR not in p.parents
    )
    return candidates[0] if candidates else None
