#!/usr/bin/env python3
"""
Build script for the HowTheFox musings section.

Reads Markdown files from posts/, generates static HTML into musings/,
plus an index page and an RSS feed. No server, no database, no CMS —
just run this after adding or editing a post.

Usage:
    python3 build.py

Writing a new post:
    1. Create posts/YYYY-MM-DD-a-short-slug.md
    2. First line of the file: a level-1 heading, e.g. "# My title"
    3. Optionally add frontmatter above it for a custom summary:

        ---
        summary: One sentence used for previews and social sharing.
        ---
        # My title

        The rest is plain Markdown.

    4. Run: python3 build.py
"""

import html
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    import markdown
except ImportError:
    sys.exit(
        "Missing dependency 'markdown'. Install it with:\n"
        "    pip install markdown --break-system-packages\n"
        "(or just: pip install markdown)"
    )

import config

ROOT = Path(__file__).parent
POSTS_DIR = ROOT / "posts"
TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"
OUT_DIR = ROOT / "musings"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?\n)---\s*\n(.*)$", re.DOTALL)
FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$")


def parse_frontmatter(text):
    """Very small key: value frontmatter parser. Returns (dict, remaining_text)."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw, body = m.group(1), m.group(2)
    meta = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip().lower()] = value.strip()
    return meta, body


def extract_title(body):
    """Pull the first level-1 heading out of the Markdown body as the title."""
    lines = body.lstrip("\n").splitlines()
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        rest = "\n".join(lines[1:]).lstrip("\n")
        return title, rest
    return None, body


def make_summary(html_body, limit=160):
    text = re.sub(r"<[^>]+>", " ", html_body)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def load_posts():
    posts = []
    for path in sorted(POSTS_DIR.glob("*.md")):
        if path.name.startswith("_"):
            continue  # leading underscore = draft, skipped

        fm_match = FILENAME_RE.match(path.name)
        if not fm_match:
            print(f"Skipping {path.name}: filename must look like YYYY-MM-DD-slug.md")
            continue
        date_str, slug = fm_match.groups()
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            print(f"Skipping {path.name}: invalid date {date_str!r}")
            continue

        raw = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(raw)

        title = meta.get("title")
        extracted_title, body = extract_title(body)
        title = title or extracted_title
        if not title:
            print(f"Skipping {path.name}: no title found (add '# Title' as the first line)")
            continue

        content_html = markdown.markdown(
            body, extensions=["extra", "smarty", "sane_lists"]
        )
        summary = meta.get("summary") or make_summary(content_html)

        posts.append(
            {
                "slug": slug,
                "title": title,
                "date": date,
                "summary": summary,
                "content_html": content_html,
            }
        )

    posts.sort(key=lambda p: p["date"], reverse=True)
    return posts


def render(template_text, values):
    out = template_text
    for key, val in values.items():
        out = out.replace("{{" + key + "}}", val)
    return out


def build():
    if not TEMPLATES_DIR.exists():
        sys.exit("templates/ directory not found — run this from the project root.")

    post_template = (TEMPLATES_DIR / "post.html").read_text(encoding="utf-8")
    index_template = (TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)

    # static assets
    shutil.copytree(STATIC_DIR, OUT_DIR / "static")
    shutil.copy(STATIC_DIR / "favicon.svg", OUT_DIR / "favicon.svg")

    posts = load_posts()
    year = str(datetime.now().year)

    common = {
        "SITE_NAME": config.SITE_NAME,
        "SITE_TAGLINE": config.SITE_TAGLINE,
        "SITE_URL": config.SITE_URL,
        "SECTION_URL": config.SECTION_URL,
        "SECTION_PATH": config.SECTION_PATH,
        "AUTHOR": config.AUTHOR,
        "YEAR": year,
    }

    # per-post pages
    for post in posts:
        post_dir = OUT_DIR / post["slug"]
        post_dir.mkdir(parents=True, exist_ok=True)
        url = f"{config.SECTION_URL}/{post['slug']}/"
        values = dict(common)
        values.update(
            {
                "TITLE": html.escape(post["title"]),
                "DESCRIPTION": html.escape(post["summary"]),
                "URL": url,
                "DATE_ISO": post["date"].strftime("%Y-%m-%d"),
                "DATE_DISPLAY": post["date"].strftime("%-d %B %Y"),
                "CONTENT": post["content_html"],
            }
        )
        (post_dir / "index.html").write_text(
            render(post_template, values), encoding="utf-8"
        )

    # index page
    if posts:
        items = []
        for post in posts:
            url = f"{config.SECTION_PATH}/{post['slug']}/"
            items.append(
                "  <li>\n"
                f'    <h2><a href="{url}">{html.escape(post["title"])}</a></h2>\n'
                f'    <p class="summary">{html.escape(post["summary"])}</p>\n'
                f'    <p class="post-meta">{post["date"].strftime("%-d %B %Y")}</p>\n'
                "  </li>"
            )
        post_list_html = "\n".join(items)
    else:
        post_list_html = '  <li class="empty-note">Nothing posted yet.</li>'

    index_values = dict(common)
    index_values["POST_LIST"] = post_list_html
    (OUT_DIR / "index.html").write_text(
        render(index_template, index_values), encoding="utf-8"
    )

    # RSS feed
    write_feed(posts, common)

    print(f"Built {len(posts)} post(s) into {OUT_DIR}/")


def write_feed(posts, common):
    items_xml = []
    for post in posts:
        url = f"{config.SECTION_URL}/{post['slug']}/"
        pub_date = post["date"].strftime("%a, %d %b %Y 00:00:00 +0000")
        items_xml.append(
            "  <item>\n"
            f"    <title>{escape_xml(post['title'])}</title>\n"
            f"    <link>{url}</link>\n"
            f"    <guid>{url}</guid>\n"
            f"    <pubDate>{pub_date}</pubDate>\n"
            f"    <description>{escape_xml(post['summary'])}</description>\n"
            "  </item>"
        )
    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>\n'
        f"  <title>{escape_xml(common['SITE_NAME'])} — {escape_xml(common['SITE_TAGLINE'])}</title>\n"
        f"  <link>{config.SECTION_URL}/</link>\n"
        f"  <description>Short essays and stray thoughts from {escape_xml(common['AUTHOR'])}.</description>\n"
        + "\n".join(items_xml)
        + "\n</channel></rss>\n"
    )
    (OUT_DIR / "feed.xml").write_text(feed, encoding="utf-8")


def escape_xml(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


if __name__ == "__main__":
    build()
