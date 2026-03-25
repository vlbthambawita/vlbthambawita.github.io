#!/usr/bin/env python3
"""
fetch_scholar.py
================
Fetches Google Scholar statistics and top-cited publications for
Vajira Lasantha Thambawita (scholar ID: hSe42z0AAAAJ) and writes
the results to _data/scholar_stats.yml.

This script is designed to be called from a GitHub Actions workflow
(see .github/workflows/update_scholar.yml) on a weekly/monthly schedule.

Usage:
    pip install scholarly pyyaml
    python scripts/fetch_scholar.py

The script tries the `scholarly` library first, which uses
rotate-proxy or direct access depending on availability. If that
fails it falls back to the Semantic Scholar REST API.
"""

import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCHOLAR_ID = "hSe42z0AAAAJ"
SCHOLAR_PROFILE_URL = f"https://scholar.google.com/citations?user={SCHOLAR_ID}&hl=en"
SEMANTIC_SCHOLAR_SEARCH_URL = (
    "https://api.semanticscholar.org/graph/v1/author/search"
    "?query=Vajira+Lasantha+Thambawita"
    "&fields=name,citationCount,hIndex,paperCount,papers.title,"
    "papers.year,papers.citationCount,papers.venue,papers.authors"
)

# Top papers from _data/scholar_stats.yml that we want to update citations for
TOP_PAPER_TITLES = [
    "HyperKvasir, a comprehensive multi-class image and video dataset for gastrointestinal endoscopy",
    "DeepFake electrocardiograms using generative adversarial networks are the beginning of the end for privacy issues in medicine",
    "Kvasir-Capsule, a video capsule endoscopy dataset",
    "SinGAN-Seg: Synthetic training data generation for medical image segmentation",
    "An extensive study on cross-dataset bias and evaluation metrics interpretation for machine learning applied to gastrointestinal tract abnormality classification",
    "Machine learning-based analysis of sperm videos and participant data for male fertility prediction",
    "On evaluation metrics for medical applications of artificial intelligence",
    "Impact of image resolution on deep learning performance in endoscopy image classification: An experimental study using a large dataset of endoscopic images",
    "VISEM-Tracking, a human spermatozoa tracking dataset",
    "Explaining deep neural networks for knowledge discovery in electrocardiogram analysis",
]

YAML_OUTPUT = Path(__file__).parent.parent / "_data" / "scholar_stats.yml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_url(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; vlbthambawita-site-bot/1.0; "
                "+https://github.com/vlbthambawita/vlbthambawita.github.io)"
            ),
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _title_similarity(a: str, b: str) -> float:
    """Rough word-overlap similarity."""
    a_words = set(a.lower().split())
    b_words = set(b.lower().split())
    if not a_words or not b_words:
        return 0.0
    return len(a_words & b_words) / max(len(a_words), len(b_words))


# ---------------------------------------------------------------------------
# Method 1: scholarly
# ---------------------------------------------------------------------------

def fetch_via_scholarly() -> dict | None:
    """
    Uses the `scholarly` library to pull profile stats + top publications.
    Returns a dict ready to write to YAML, or None on failure.
    """
    try:
        from scholarly import scholarly as sch
    except ImportError:
        print("[scholarly] Package not installed. Skipping.", file=sys.stderr)
        return None

    try:
        print("[scholarly] Searching for author …")
        author = sch.search_author_id(SCHOLAR_ID)
        print("[scholarly] Filling author …")
        author = sch.fill(author, sections=["basics", "counts", "publications"])
    except Exception as exc:
        print(f"[scholarly] Failed: {exc}", file=sys.stderr)
        return None

    stats = {
        "total_citations": int(author.get("citedby", 0) or 0),
        "citations_since_2020": int(author.get("citedby5y", 0) or 0),
        "h_index": int(author.get("hindex", 0) or 0),
        "h_index_since_2020": int(author.get("hindex5y", 0) or 0),
        "i10_index": int(author.get("i10index", 0) or 0),
        "i10_index_since_2020": int(author.get("i10index5y", 0) or 0),
    }

    # Build top-cited list — sort publications by citedby count
    pubs = author.get("publications", [])
    pubs_sorted = sorted(
        pubs,
        key=lambda p: int(p.get("num_citations", 0) or 0),
        reverse=True,
    )

    top_cited = []
    for pub in pubs_sorted[:15]:
        bib = pub.get("bib", {})
        title = bib.get("title", "")
        if not title:
            continue

        # Find matching entry from our known list for scholar_url
        scholar_url = pub.get("pub_url") or (
            "https://scholar.google.com/scholar?q="
            + urllib.parse.quote_plus(title[:80])
        )

        top_cited.append({
            "title": title,
            "authors": bib.get("author", ""),
            "venue": bib.get("venue") or bib.get("journal") or bib.get("conference") or "",
            "year": int(bib.get("pub_year", 0) or 0),
            "citations": int(pub.get("num_citations", 0) or 0),
            "scholar_url": scholar_url,
        })

    return {"stats": stats, "top_cited": top_cited[:10]}


# ---------------------------------------------------------------------------
# Method 2: Semantic Scholar REST API
# ---------------------------------------------------------------------------

def fetch_via_semantic_scholar() -> dict | None:
    """
    Uses the public Semantic Scholar API (no auth key required for low-volume).
    Returns a dict ready to write to YAML, or None on failure.
    """
    print("[semantic-scholar] Querying author search …")
    try:
        raw = _fetch_url(SEMANTIC_SCHOLAR_SEARCH_URL)
        data = json.loads(raw)
    except Exception as exc:
        print(f"[semantic-scholar] Failed: {exc}", file=sys.stderr)
        return None

    authors = data.get("data", [])
    if not authors:
        print("[semantic-scholar] No authors found.", file=sys.stderr)
        return None

    # Pick the best match
    author = authors[0]
    print(f"[semantic-scholar] Found author: {author.get('name')}")

    stats = {
        "total_citations": int(author.get("citationCount", 0) or 0),
        "citations_since_2020": 0,   # Not available via basic search endpoint
        "h_index": int(author.get("hIndex", 0) or 0),
        "h_index_since_2020": 0,
        "i10_index": 0,              # Not available via this endpoint
        "i10_index_since_2020": 0,
    }

    papers = author.get("papers", [])
    papers_sorted = sorted(
        papers,
        key=lambda p: int(p.get("citationCount", 0) or 0),
        reverse=True,
    )

    top_cited = []
    for paper in papers_sorted[:10]:
        title = paper.get("title", "")
        authors_list = [
            a.get("name", "") for a in (paper.get("authors") or [])
        ]
        authors_str = "; ".join(authors_list[:5])
        if len(authors_list) > 5:
            authors_str += " et al."

        top_cited.append({
            "title": title,
            "authors": authors_str,
            "venue": paper.get("venue", ""),
            "year": int(paper.get("year", 0) or 0),
            "citations": int(paper.get("citationCount", 0) or 0),
            "scholar_url": (
                "https://scholar.google.com/scholar?q="
                + title[:80].replace(" ", "+")
            ),
        })

    return {"stats": stats, "top_cited": top_cited}


# ---------------------------------------------------------------------------
# YAML writer (avoids PyYAML dependency for the basic case)
# ---------------------------------------------------------------------------

def _yaml_str(s: str) -> str:
    """Quote a string for YAML if it contains special chars."""
    if not s:
        return '""'
    if any(c in s for c in ('"', "'", ":", "#", "{", "}", "[", "]", ",", "&", "*", "?", "|", "-", "<", ">", "=", "!", "%", "@", "`", "\n")):
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return s


def write_yaml(data: dict) -> None:
    """
    Writes (or updates) _data/scholar_stats.yml preserving the
    highlights and other static sections while updating stats and
    top_cited blocks.
    """
    try:
        import yaml

        # Read existing YAML to preserve static sections (highlights, etc.)
        existing = {}
        if YAML_OUTPUT.exists():
            with open(YAML_OUTPUT, "r", encoding="utf-8") as fh:
                existing = yaml.safe_load(fh) or {}

        # Merge dynamic data
        existing["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        existing["auto_updated"] = True
        existing["stats"] = data["stats"]
        if data.get("top_cited"):
            existing["top_cited"] = data["top_cited"]

        with open(YAML_OUTPUT, "w", encoding="utf-8") as fh:
            yaml.dump(existing, fh, allow_unicode=True, sort_keys=False, default_flow_style=False)

        print(f"[writer] Wrote YAML with PyYAML → {YAML_OUTPUT}")

    except ImportError:
        # Fallback: manual write (only updates stats block, preserves rest via sed-like approach)
        _write_yaml_manual(data)


def _write_yaml_manual(data: dict) -> None:
    """Fallback YAML writer without PyYAML."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = []

    # Read existing file and replace only the stats/last_updated/auto_updated sections
    if YAML_OUTPUT.exists():
        content = YAML_OUTPUT.read_text(encoding="utf-8")
        # Replace last_updated
        import re
        content = re.sub(r'last_updated:.*', f'last_updated: "{today}"', content)
        content = re.sub(r'auto_updated:.*', 'auto_updated: true', content)

        # Replace stats block
        stats = data["stats"]
        stats_block = f"""stats:
  total_citations: {stats['total_citations']}
  citations_since_2020: {stats['citations_since_2020']}
  h_index: {stats['h_index']}
  h_index_since_2020: {stats['h_index_since_2020']}
  i10_index: {stats['i10_index']}
  i10_index_since_2020: {stats['i10_index_since_2020']}"""

        content = re.sub(
            r'stats:\n(?:  \w[^\n]*\n)+',
            stats_block + "\n",
            content,
        )

        YAML_OUTPUT.write_text(content, encoding="utf-8")
        print(f"[writer] Updated YAML (manual) → {YAML_OUTPUT}")
    else:
        print("[writer] YAML file not found; please create _data/scholar_stats.yml first.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print(f"  Scholar data fetch — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    result = None

    # Try scholarly first
    result = fetch_via_scholarly()
    if result:
        print("[main] scholarly succeeded.")
    else:
        print("[main] Trying Semantic Scholar …")
        time.sleep(1)
        result = fetch_via_semantic_scholar()

    if not result:
        print("[main] All methods failed. Leaving YAML unchanged.", file=sys.stderr)
        sys.exit(1)

    print(f"[main] Stats: {result['stats']}")
    print(f"[main] Top cited papers: {len(result.get('top_cited', []))}")

    write_yaml(result)
    print("[main] Done.")


if __name__ == "__main__":
    main()
