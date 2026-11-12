#!/usr/bin/env python3
"""Build assets/data/reading_list.sqlite from scripts/reading_list/links.json.

links.json is an export of the Notion "Reading List" page and its topic
sub-pages. Each entry: url, title, topic, subsection, kind, note, category,
subcategory. `category` is one of the keys in CATEGORIES below, or "paper" /
"news" / "other" / "pdf" for links kept in links.json but left out of the site.
Only web pages are published: PDF links are always skipped.
Re-run after editing links.json:

    python3 scripts/reading_list/build_db.py
"""
import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
SRC = Path(__file__).with_name("links.json")
OUT = ROOT / "assets" / "data" / "reading_list.sqlite"

# key -> (display name, description). Order here is display order.
CATEGORIES = {
    "course":     ("Courses & Tutorials",     "Structured courses, hands-on tutorials and notebooks"),
    "article":    ("Articles & Explainers",   "Blog posts and visual explanations of concepts"),
    "video":      ("Videos & Talks",          "Lectures, tutorials and paper walkthroughs on video"),
    "guide":      ("Books & Guides",          "Books, handbooks, checklists and how-to guides"),
    "survey":     ("Surveys & Reports",       "Review papers and state-of-the-field reports"),
    "library":    ("Libraries & Frameworks",  "Python packages and frameworks to build with"),
    "tool":       ("Tools & Platforms",       "Apps, web tools and platforms for research and engineering"),
    "model":      ("Models & Code",           "Pretrained models, demos and reference implementations"),
    "data":       ("Datasets & Data Portals", "Datasets, data repositories and data infrastructure"),
    "eval":       ("Evaluation & Metrics",    "Metrics libraries, evaluation guides and leaderboards"),
    "collection": ("Curated Collections",     "Awesome-lists and hand-picked resource lists"),
}

# Personal / access-restricted links kept out of the public database
# (already removed from links.json; kept here as a guard for future exports).
EXCLUDE_PREFIXES = (
    "https://idp.feide.no/",
    "https://researchrabbitapp.com/home",
    "https://drive.google.com/",
    "https://docs.google.com/",
)

PDF = re.compile(r"\.e?pdf($|[?#])|arxiv\.org/(pdf|ftp)/", re.I)

SCHEMA = """
CREATE TABLE categories (
    id          INTEGER PRIMARY KEY,
    key         TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    description TEXT
);
CREATE TABLE subcategories (
    id          INTEGER PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    name        TEXT NOT NULL,
    UNIQUE (category_id, name)
);
CREATE TABLE topics (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
);
CREATE TABLE links (
    id          INTEGER PRIMARY KEY,
    url         TEXT NOT NULL,
    domain      TEXT NOT NULL,
    title       TEXT,
    category_id    INTEGER NOT NULL REFERENCES categories(id),
    subcategory_id INTEGER NOT NULL REFERENCES subcategories(id),
    topic_id       INTEGER NOT NULL REFERENCES topics(id),
    subsection  TEXT,
    note        TEXT
);
CREATE INDEX links_category ON links(category_id);
CREATE INDEX links_subcat   ON links(subcategory_id);
CREATE INDEX links_topic    ON links(topic_id);
CREATE INDEX links_domain   ON links(domain);
CREATE VIEW reading_list AS
    SELECT l.id, c.name AS category, s.name AS subcategory, t.name AS topic,
           l.subsection, l.title, l.url, l.domain, l.note
    FROM links l
    JOIN categories c    ON c.id = l.category_id
    JOIN subcategories s ON s.id = l.subcategory_id
    JOIN topics t        ON t.id = l.topic_id;
"""


def main() -> None:
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    seen: set[tuple[str, str]] = set()
    kept = []
    for r in rows:
        key = (r["url"], r["topic"])
        if (r.get("category") in CATEGORIES and r.get("subcategory") and key not in seen
                and not r["url"].startswith(EXCLUDE_PREFIXES) and not PDF.search(r["url"])):
            seen.add(key)
            kept.append(r)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.unlink(missing_ok=True)
    db = sqlite3.connect(OUT)
    db.executescript(SCHEMA)

    cat_ids = {}
    for key, (name, desc) in CATEGORIES.items():
        cat_ids[key] = db.execute(
            "INSERT INTO categories(key, name, description) VALUES (?,?,?)", (key, name, desc)
        ).lastrowid

    sub_ids: dict[tuple[str, str], int] = {}
    for r in sorted(kept, key=lambda r: (list(CATEGORIES).index(r["category"]), r["subcategory"])):
        k = (r["category"], r["subcategory"])
        if k not in sub_ids:
            sub_ids[k] = db.execute(
                "INSERT INTO subcategories(category_id, name) VALUES (?,?)", (cat_ids[k[0]], k[1])
            ).lastrowid

    topic_ids: dict[str, int] = {}
    for r in kept:
        name = r["topic"]
        if name not in topic_ids:
            topic_ids[name] = db.execute("INSERT INTO topics(name) VALUES (?)", (name,)).lastrowid
        db.execute(
            """INSERT INTO links(url, domain, title, category_id, subcategory_id, topic_id,
                                 subsection, note)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                r["url"],
                urlparse(r["url"]).netloc.removeprefix("www."),
                r.get("title") or None,
                cat_ids[r["category"]],
                sub_ids[(r["category"], r["subcategory"])],
                topic_ids[name],
                r.get("subsection") or None,
                r.get("note") or None,
            ),
        )
    db.commit()
    db.execute("VACUUM")
    db.close()
    print(f"{len(kept)} links kept of {len(rows)}, {len(CATEGORIES)} categories, "
          f"{len(sub_ids)} subcategories, {len(topic_ids)} topics -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
