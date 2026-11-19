# DocsGPT documentation site

The source of [docs.docsgpt.cloud](https://docs.docsgpt.cloud). It is a
[Nextra 4](https://nextra.site) site on the Next.js App Router, installed with npm.

## Run it locally

You need Node.js 20.9 or newer (Next.js 16's minimum); Node 22, the version the frontend
uses, works.

```bash
git clone https://github.com/arc53/DocsGPT.git
cd DocsGPT/docs
npm install
npm run dev      # http://localhost:3000, reloads as you edit
```

Search is turned off in the dev server. To check a change the way it ships, build the
site:

```bash
npm run build    # next build, then pagefind indexes the output for search
npm run start    # serve the production build
node scripts/check-links.mjs   # after a build: check internal links and #anchors, offline
```

Run `npm run build` before opening a PR that touches the docs: it fails on broken MDX. The
[docs workflow](../.github/workflows/docs.yml) runs the same build on pull requests that change
`docs/`, checks the internal links in the built pages, checks every page's `lastUpdated` date, and
fails a pull request that changes a [generated file](#generated-pages) or the date of a page
that already exists.

## Where things live

- `content/`: the pages, as `.mdx` (or `.md`) files. A file's path is its URL:
  `content/Deploying/Docker-Deploying.mdx` is served at `/Deploying/Docker-Deploying`.
- `content/**/_meta.js`: the sidebar order and titles of each folder. Add an entry when you
  add a page so it lands where you want it.
- `app/layout.jsx`: the navbar, the footer and the page head.
  `app/[[...mdxPath]]/page.jsx` renders every page.
- `theme.config.jsx`: the Nextra theme options that `app/layout.jsx` passes on (edit links,
  sidebar, table of contents).
- `content/API/`: the API section: an overview, DocsGPT's MCP server, and the REST API reference
  (`reference.mdx`), which renders every endpoint from the snapshot below.
- `data/swagger.json`: a generated snapshot of the REST API's flask-restx Swagger document, rendered by
  `components/ApiReference.jsx`. Don't edit it by hand; see [Generated pages](#generated-pages).
- `mdx-components.jsx` and `components/`: React components available to the pages.
- `public/`: images and other static files, served from the site root. `public/llms.txt`
  lists the pages for LLM readers and is generated; see [Generated pages](#generated-pages).
- `scripts/generate-llms.mjs`: the generator for `public/llms.txt`.
- `next.config.js`: the Next.js config, including `redirects()`. When you move or delete a
  page, add a permanent redirect from the old URL there.
- `page-meta.js`: each page's canonical URL, share card and JSON-LD, built from its frontmatter.
  `app/sitemap.js` serves `/sitemap.xml` from the same data; `public/robots.txt` and the share
  image `public/og/default.png` are static files.
- `data/mcp-presets.json`: the curated MCP connector presets, generated from
  `docsgpt/connectors/presets/mcp/` and rendered by `components/McpPresets.jsx`.
- `scripts/check-dates.mjs`: checks every page's `lastUpdated` date (`npm run dates:check`).
- `scripts/sync-dates.mjs`: dates the pages whose content changed on `main` (`npm run dates:sync`).
- `scripts/check-generated.mjs`: fails when a pull request changes a generated file.

## Page frontmatter

Every page sets `title`, `description` and `lastUpdated` (`YYYY-MM-DD`). `lastUpdated` is
shown at the bottom of the page and becomes the sitemap's `lastmod`. A new page gets today's
date. On a page that already exists you leave it alone: after your change merges, the
"Generated docs" workflow dates the page with the day its content changed. For a change a
reader would not notice, such as a typo, put `[keep-date]` in the pull request title or in the
subject line of every commit that changes the page. [AGENTS.md](AGENTS.md) has the full rule.
CI fails on a missing, malformed or future date and, on pull requests, on an existing page
whose date was changed; it notes, without failing, each page that will be re-dated:

```bash
npm run dates:check
```

## Generated pages

Four files are generated, and so are the `lastUpdated` dates above. The
["Generated docs" workflow](../.github/workflows/generated-docs.yml) rebuilds them on `main`
after every merge and opens a pull request with the result, so **don't change them in your
own pull request**: CI fails if you do (`npm run generated:check -- --base origin/main` is the
same check). They stay in the
repository because the site builds on Vercel without the backend.

| File | Generated from | Command |
| --- | --- | --- |
| `content/Deploying/Settings-Reference.mdx` | the settings definitions in `docsgpt/core/settings/` | `python -m docsgpt.core.settings.reference --write` |
| `data/swagger.json` | the backend's routes | `python -m docsgpt.api.reference --write` |
| `data/mcp-presets.json` | the preset files in `docsgpt/connectors/presets/mcp/` | `python -m docsgpt.connectors.reference --write` |
| `public/llms.txt` | the sidebar (`content/**/_meta.js`) and each page's `description` | `npm run llms` |

The Python commands run from the repository root with the backend environment active.
Without `--write` they print the result, which is how you preview it. The two generated pages
date themselves: the settings reference keeps its `lastUpdated` while its content is
unchanged, and a changed Swagger snapshot sets `content/API/reference.mdx`'s date to today.

## Style

Prose is checked by [Vale](https://vale.sh) with the rules in `.github/styles`. CI runs it on
pull requests that change Markdown and fails on errors. If you have Vale installed, run the same
check from the repository root:

```bash
vale --minAlertLevel=error docs
```
