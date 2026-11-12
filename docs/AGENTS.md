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
freshness signal.

- **New pages** get today's date (`YYYY-MM-DD`).
- **Leave it alone on a page that already exists**, whatever you changed. The "Generated
  docs" workflow (`../.github/workflows/generated-docs.yml`) runs `scripts/sync-dates.mjs` on
  `main` after the merge and dates the page with the day its content changed. Only the body
  counts, and whitespace in it does not: a change to the frontmatter (`title`,
  `description`) or one that only reflows lines leaves the date alone by itself. Two pull
  requests that each bumped the same page used to conflict on this one line; `npm run
  dates:check` now fails a pull request that changes it.
- **For an edit a reader would not notice** (a typo, wording polish, a link target renamed
  across many pages), put `[keep-date]` in the pull request title, or in the subject line
  (the first line) of every commit that changes the page. A commit body does not count. With
  a squash merge of several commits only the pull request title counts: the squash commit's
  body lists every commit, so one commit's marker cannot speak for the rest. A rebase merge
  leaves no pull request title on `main`, so there only the commit subjects count.

`npm run dates:check` fails on a missing, malformed or future date, and in CI on a pull
request on an existing page whose date changed. On a pull request it also lists, as a notice
that never fails, each existing page whose body changed without the marker: the page will be
dated with the day of the merge. `npm run dates:check -- --base "$(git merge-base HEAD origin/main)"`
shows the same notices locally (it reads the commit subjects; set `PR_TITLE` to include the
title).

## Generated files

Don't change these in a pull request; CI fails if you do (`npm run generated:check -- --base origin/main` is the same check). The
"Generated docs" workflow rebuilds them on `main` after the merge and opens its own pull
request, which is the only place they change:

- `data/swagger.json` (`python -m docsgpt.api.reference --write`)
- `data/mcp-presets.json` (`python -m docsgpt.connectors.reference --write`, which also moves
  `content/Sources/Connectors/index.mdx`'s `lastUpdated` to today when the list changes)
- `content/Deploying/Settings-Reference.mdx` (`python -m docsgpt.core.settings.reference --write`)
- `public/llms.txt` (`npm run llms`)

If one shows up in your diff, restore it: `git checkout origin/main -- <file>`. Run a
command without `--write` (or `npm run llms -- --print`) to preview its output.

## Before you finish

From `docs/`:

```bash
npm test               # the docs scripts' own tests
npm run dates:check    # every page has a valid lastUpdated
npm run build          # fails on broken MDX
node scripts/check-links.mjs   # after the build: internal links and #anchors
```

- Moving or deleting a page: add a permanent redirect from the old URL in
  `next.config.js`, and update the folder's `_meta.js`.
- Prose follows the Vale rules in `../.github/styles`; run `vale --minAlertLevel=error docs`
  from the repository root when Vale is installed.

## Page metadata

`page-meta.js` builds each page's canonical URL, Open Graph and Twitter card, and JSON-LD
(`TechArticle` and `BreadcrumbList`; `WebSite` on the home page). `app/sitemap.js` serves
`/sitemap.xml` from the page map, `public/robots.txt` allows every crawler and points at
the sitemap, and `public/og/default.png` is the share image. They read only the
frontmatter above, so a page with a good `title`, `description` and an honest
`lastUpdated` needs nothing else.
