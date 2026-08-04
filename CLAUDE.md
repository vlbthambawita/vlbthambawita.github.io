# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Personal academic website for Vajira Lasantha Thambawita, served at **vajira.info** (see `CNAME`) via GitHub Pages. Plain Jekyll — no Gemfile, no `package.json`, no build tooling beyond what GitHub Pages runs by default.

## Commands

There is no Gemfile, so there is nothing to `bundle install`. Use a system/rbenv Jekyll (or add `gem "github-pages", group: :jekyll_plugins` if you want to pin the GH Pages toolchain):

```bash
jekyll serve --livereload    # local preview at http://127.0.0.1:4000
jekyll build                 # write _site/
```

`_site/` and `.jekyll-cache/` are in `.gitignore`, but ~50 stale `_site/` files were committed before that rule existed and are still tracked. Don't treat committed `_site/` output as current — it predates `publications.html` and `deepsearch.html`. Never hand-edit `_site/`.

The only CI is `.github/workflows/update_scholar.yml` (weekly Sunday 03:00 UTC + `workflow_dispatch`), which runs `scripts/fetch_scholar.py` and commits `_data/scholar_stats.yml`. To test locally:

```bash
pip install scholarly pyyaml && python scripts/fetch_scholar.py
```

The script tries the `scholarly` scraper first, falls back to the Semantic Scholar REST API, and exits non-zero if both fail (the workflow then skips the commit). `SCHOLAR_ID` is hardcoded at the top of the script.

## Branches

**`master_modern` is the branch GitHub Pages builds and serves** — it is the live site, and it is where all work belongs. `master` is the repo's *default* branch but is stale (`master_modern` is 61 commits ahead / 4 behind): the redesigned `card`/`section` CSS system, `publications.html`, and the scholar workflow exist only on `master_modern`. Open PRs against `master_modern`, not `master`, and check which branch you're on before assuming a file exists.

## Content architecture

Everything is data-driven — pages are thin Liquid templates over `_data/` or collections. To change site content, edit data files, not HTML.

### Two parallel publication sources (important)

| Source | Rows | Consumed by |
|---|---|---|
| `_papers/` collection (25 `.md` files, one per paper) | 25 | `papers.html`, `search.json`, `_layouts/paper.html` detail pages at `/papers/<slug>` |
| `_data/my_papers.csv` (Google Scholar CSV export) | 96 | `publications.html` (the maintained page), `papers_v2.html` |

They are not synced. `_papers/*.md` front matter uses `paper_title` / `paper_authors` / `pdf_link` / `published`; the CSV uses capitalized `Authors,Title,Publication,Volume,Number,Pages,Year,Publisher` and Liquid accesses them as `paper.Title`, `paper.Year`, etc. `publications.html` groups the CSV by `Year` and layers `_data/scholar_stats.yml` metrics on top.

Similarly for projects: `_projects/` holds only `test_project_*.md` placeholders (`show: False`); the live Projects page reads **`_data/project_links.yml`**, whose header comments document the supported keys (`title`, `link`, `icon`, `abstract`, `status`, `tags`, optional `logo`).

### Data files

- `_data/myself.yml` — name, degree, bio, photo/icon paths, and the social `links` list (each with a FontAwesome `fa-class` and a numeric `order` used for sorting in `_includes/social-icons.html`).
- `_data/navigation.yml` — drives the nav. Most entries are commented out; only **Home** and **Projects** are live. Existing pages (`about`, `papers`, `blog`, `publications`, `students`, `staff`, `deepsearch`) are reachable by URL but intentionally unlinked.
- `_data/my_experience.yml` — `exps:` list rendered as the timeline on `index.html` and `about.html`; both `reverse` it, so keep entries in chronological order. `present: True` adds the "Present" badge.
- `_data/scholar_stats.yml` — machine-written by the workflow; `auto_updated: false` + zeroed `stats` means the workflow hasn't successfully run yet and the page falls back to em-dashes. Hand-authored keys (`highlights`, the `top_cited` titles/authors/venues) are preserved on sync — only `stats`, `citations`, `last_updated`, `auto_updated` are overwritten.

### Layouts and includes

`_layouts/default.html` is the shell for everything: `data-bs-theme="dark"`, Space Grotesk from Google Fonts, particles background, nav, `{{ content }}`, footer, then FontAwesome kit + lunr CDN scripts and the inline mobile nav toggle. Other layouts (`paper`, `project`, `author`, `post`, `students`) all wrap it.

`_includes/booking-button.html` lazily mounts the Google Calendar scheduling button and takes `id`, `label`, `url`, `color` params — always pass a unique `id` when a page uses more than one.

### Styling

**All CSS lives in `assets/css/styles.scss`** (~1390 lines, front-matter dashes at the top so Jekyll compiles it). It's flat CSS with custom properties on `:root` — `--brand: #ff9f1c`, dark `--bg-*`, `--radius-lg`, `--max-width` — not nested SCSS. `_sass/main.scss` is a 7-line vestige that nothing imports. There is no Bootstrap on the page despite Bootstrap-ish class names (`btn`, `badge-soft`, `data-bs-*`) in older templates; add the utilities you need to `styles.scss`.

## Known-broken things (don't mistake these for working patterns)

- `papers.html` and `blog.html` are **missing the opening `---`** of their front matter, so Jekyll treats them as static files and copies raw Liquid to `_site/`. Adding the leading `---` fixes both.
- `_layouts/project.html` and the `_projects` detail pages reference `{{ project.project_title }}` / `{{ project.status }}` — should be `page.`, so they render empty.
- `_layouts/students.html` reads `site.data.students.people`, but `_data/students.yml` does not exist; the page renders empty grids.
- `_config.yml` maps `path: "search"` to a `search` layout that doesn't exist, and `_includes/search.html` (jQuery, filters `search.json` by title/author) is not included by any page. `lunr.js` is loaded globally but unused.
- `_config.yml` defines no `title`, `url`, or `baseurl`; templates use `site.data.myself.name` for the title and `relative_url` throughout.
