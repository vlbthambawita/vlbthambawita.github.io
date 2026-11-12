#!/usr/bin/env python3
"""Download a small preview image for every published resource in links.json.

For each link it picks, in order:
  1. YouTube video thumbnail
  2. GitHub repository social card
  3. the page's own preview image (og:image / twitter:image)
  4. the site's icon (apple-touch-icon / largest <link rel=icon> / favicon.ico)
and stores a 320x180 WebP under assets/img/resources/. The file name is a hash of
the URL, and links.json gets an "image" field ("cover" or "icon" + path).
Existing thumbnails are kept; pass --force to refetch everything.

    python3 scripts/reading_list/fetch_thumbnails.py
    python3 scripts/reading_list/build_db.py
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import html
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
SRC = Path(__file__).with_name("links.json")
OUT_DIR = ROOT / "assets" / "img" / "resources"
SKIP = {"paper", "news", "other", "pdf"}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
W, H = 320, 180
BG = (15, 23, 42)  # matches the site's dark card colour


def get(url: str, limit: int = 3_000_000) -> tuple[bytes, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read(limit), r.headers.get("Content-Type", ""), r.geturl()
        except urllib.error.HTTPError as e:  # back off when rate-limited
            if e.code != 429 or attempt == 4:
                raise
            time.sleep(int(e.headers.get("Retry-After") or 0) or 5 * (attempt + 1))
    raise RuntimeError("unreachable")


def fallback_icon(url: str) -> tuple[str, str]:
    # Build-time only: a PNG rendering of the site's icon, for sites whose own icon is SVG.
    return ("icon", f"https://www.google.com/s2/favicons?domain={urlparse(url).netloc}&sz=128")


def meta(text: str, *names: str) -> str:
    for n in names:
        for pat in (rf'<meta[^>]+(?:property|name)=["\']{re.escape(n)}["\'][^>]*content=["\']([^"\']+)',
                    rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']{re.escape(n)}["\']'):
            m = re.search(pat, text, re.I)
            if m:
                return html.unescape(m.group(1)).strip()
    return ""


def icon_links(text: str, base: str) -> list[str]:
    found = []
    for tag in re.findall(r"<link[^>]+>", text, re.I):
        rel = re.search(r'rel=["\']([^"\']+)', tag, re.I)
        href = re.search(r'href=["\']([^"\']+)', tag, re.I)
        if not rel or not href or "icon" not in rel.group(1).lower():
            continue
        size = re.search(r'sizes=["\'](\d+)', tag, re.I)
        score = int(size.group(1)) if size else (180 if "apple" in rel.group(1).lower() else 32)
        found.append((score, urljoin(base, html.unescape(href.group(1)))))
    found.sort(reverse=True)
    return [u for _, u in found] + [urljoin(base, "/favicon.ico")]


# Hand-picked image sources where the automatic choice was poor. None = no image
# (the page shows the category icon instead).
OVERRIDES = {
    "http://microsoft.github.io/AI-For-Beginners": "https://opengraph.githubassets.com/1/microsoft/AI-For-Beginners",
    "https://microsoft.github.io/IoT-For-Beginners/#/": "https://opengraph.githubassets.com/1/microsoft/IoT-For-Beginners",
    "http://microsoft.github.io/ML-For-Beginners/#/": "https://opengraph.githubassets.com/1/microsoft/ML-For-Beginners",
    "http://microsoft.github.io/Data-Science-For-Beginners/#/": "https://opengraph.githubassets.com/1/microsoft/Data-Science-For-Beginners",
    "https://sleepdata.org/": None,
    "https://physionet.org": None,
}


def candidates(url: str) -> list[tuple[str, str]]:
    """Return [(kind, image_url)] to try in order."""
    if url in OVERRIDES:
        return [("cover", OVERRIDES[url])] if OVERRIDES[url] else []
    if url.startswith("https://console.paperspace.com/"):
        return []  # notebook launcher pages only expose a generic texture
    u = urlparse(url)
    host = u.netloc.lower().removeprefix("www.")
    yt = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", url)
    if yt and ("youtube.com" in host or host == "youtu.be"):
        return [("cover", f"https://i.ytimg.com/vi/{yt.group(1)}/hqdefault.jpg")]
    gh = re.match(r"/([^/]+)/([^/#?]+)", u.path)
    if host == "github.com" and gh:
        return [("cover", f"https://opengraph.githubassets.com/1/{gh.group(1)}/{gh.group(2)}")]
    out = []
    try:
        body, ctype, final = get(url, 600_000)
        if "html" in ctype:
            text = body.decode("utf-8", "replace")
            og = meta(text, "og:image", "og:image:url", "twitter:image", "twitter:image:src")
            if og:
                out.append(("cover", urljoin(final, og)))
            out += [("icon", i) for i in icon_links(text, final)]
            return out + [fallback_icon(url)]
    except Exception:
        pass
    return [("icon", f"{u.scheme}://{u.netloc}/favicon.ico"), fallback_icon(url)]


def render(data: bytes, kind: str) -> tuple[Image.Image, str] | None:
    im = Image.open(io.BytesIO(data))
    if getattr(im, "n_frames", 1) > 1:
        im.seek(0)
    im = im.convert("RGBA")
    if kind == "cover":
        if im.width < 200 or im.height < 100:  # tiny "cover" is really a logo
            kind = "icon"
        else:
            canvas = Image.new("RGB", im.size, BG)
            canvas.paste(im, mask=im.split()[3])
            return ImageOps.fit(canvas, (W, H), Image.LANCZOS, centering=(0.5, 0.4)), "cover"
    if im.width < 16:
        return None
    side = min(96, max(48, im.width)) if im.width >= 48 else 48
    icon = im.resize((side, side), Image.LANCZOS) if im.width != side else im
    canvas = Image.new("RGB", (W, H), BG)
    canvas.paste(icon, ((W - side) // 2, (H - side) // 2), icon)
    return canvas, "icon"


def thumb(url: str) -> tuple[str, str | None, str | None]:
    name = hashlib.sha1(url.encode()).hexdigest()[:16] + ".webp"
    for kind, img_url in candidates(url):
        try:
            data, ctype, _ = get(img_url)
            if "svg" in ctype or img_url.lower().endswith(".svg"):
                continue
            out = render(data, kind)
            if out is None:
                continue
            im, used = out
            im.save(OUT_DIR / name, "WEBP", quality=72, method=6)
            return url, used, name
        except Exception:
            continue
    return url, None, None


def main() -> None:
    force = "--force" in sys.argv
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    todo = sorted({r["url"] for r in rows if r.get("category") not in SKIP
                   and (force or not r.get("image") or not (OUT_DIR / r["image"]["file"]).exists())})
    print(f"fetching {len(todo)} thumbnails…")
    with cf.ThreadPoolExecutor(4) as ex:
        results = {u: (k, f) for u, k, f in ex.map(thumb, todo)}
    for r in rows:
        if r["url"] in results:
            kind, f = results[r["url"]]
            r["image"] = {"kind": kind, "file": f} if f else None
    SRC.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    got = [v for v in results.values() if v[1]]
    print(f"{len(got)} thumbnails ({sum(1 for k, _ in got if k == 'cover')} covers, "
          f"{sum(1 for k, _ in got if k == 'icon')} icons), {len(results) - len(got)} without image")


if __name__ == "__main__":
    main()
