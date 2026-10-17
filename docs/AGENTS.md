# AGENTS.md (docs site)

Guidance for coding agents working in `docs/`, the source of
[docs.docsgpt.cloud](https://docs.docsgpt.cloud). The repository-wide rules in `../AGENTS.md`
still apply; [README.md](README.md) explains the layout and how to run the site.

## Every page's frontmatter

Each page under `content/` opens with three fields:

```yaml
---
title: GitHub Connector
description: One sentence on what the page covers; it becomes the meta description and the llms.txt note.
lastUpdated: 2026-10-01
---
```

### `lastUpdated`

`lastUpdated` is the date a reader would say the page last changed. It is shown at the
bottom of the page ("Last updated on …") and becomes the sitemap's `<lastmod>` and the
page's JSON-LD `dateModified`, so search engines and AI answer engines read it as a
freshness signal. It is set by hand, never from git.

- **Bump it** (to today, `YYYY-MM-DD`) when you change what the page tells the reader:
  new or changed steps, settings, defaults, behavior, examples, or a section added or
  removed.
- **Leave it** for edits a reader would not notice: typos, wording polish, formatting, a
  link target renamed across many pages.
- **New pages** get today's date.
- Two generated pages date themselves, so don't edit their date by hand:
  `content/Deploying/Settings-Reference.mdx` (`python -m docsgpt.core.settings.reference --write`
  keeps the date while the content is unchanged and sets today's date when it changes) and
  `content/API/reference.mdx` (`python -m docsgpt.api.reference --write` sets today's date when
  the Swagger snapshot changes).

`npm run dates:check` fails on a missing, malformed or future date. In CI on a pull
request it also warns about pages whose content changed while `lastUpdated` did not;
treat that warning as a question to answer, not something to silence.

## Before you finish

From `docs/`:

```bash
npm run llms           # after adding, moving or removing a page, or changing a description
npm run dates:check    # every page has a valid lastUpdated
npm run build          # fails on broken MDX
node scripts/check-links.mjs   # after the build: internal links and #anchors
```

- Moving or deleting a page: add a permanent redirect from the old URL in
  `next.config.js`, and update the folder's `_meta.js`.
- Don't hand-edit generated files: `public/llms.txt`, `data/swagger.json`,
  `content/Deploying/Settings-Reference.mdx`.
- Prose follows the Vale rules in `../.github/styles`; run `vale --minAlertLevel=error docs`
  from the repository root when Vale is installed.

## Page metadata

`page-meta.js` builds each page's canonical URL, Open Graph and Twitter card, and JSON-LD
(`TechArticle` and `BreadcrumbList`; `WebSite` on the home page). `app/sitemap.js` serves
`/sitemap.xml` from the page map, `public/robots.txt` allows every crawler and points at
the sitemap, and `public/og/default.png` is the share image. They read only the
frontmatter above, so a page with a good `title`, `description` and an honest
`lastUpdated` needs nothing else.
