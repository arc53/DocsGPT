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
```

Run `npm run build` before opening a PR that touches the docs: it fails on broken MDX. The
[docs workflow](../.github/workflows/docs.yml) runs the same build on pull requests that change
`docs/`, checks the internal links in the built pages, and checks that `public/llms.txt` is
current.

## Where things live

- `content/`: the pages, as `.mdx` (or `.md`) files. A file's path is its URL:
  `content/Deploying/Docker-Deploying.mdx` is served at `/Deploying/Docker-Deploying`.
- `content/**/_meta.js`: the sidebar order and titles of each folder. Add an entry when you
  add a page so it lands where you want it.
- `app/layout.jsx`: the navbar, the banner, the footer and the page head.
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
- `runbooks/`: operator notes that are not part of the site.

## Generated pages

`content/Deploying/Settings-Reference.mdx` is generated from the settings definitions in
`docsgpt/core/settings/`. Don't edit it by hand. From the repository root, with the backend
environment active:

```bash
python -m docsgpt.core.settings.reference --write
```

`data/swagger.json` is generated from the backend's routes. After adding or changing a route,
regenerate it from the repository root (CI fails while it is stale):

```bash
python -m docsgpt.api.reference --write
```

`public/llms.txt` is generated from the sidebar: the `content/**/_meta.js` files give the
sections, the order and the link titles, and each page's frontmatter `description` gives its
note. Hidden entries are left out. After adding, moving or removing a page, or changing its
`description`, regenerate it from `docs/` (CI fails while it is stale):

```bash
npm run llms          # rewrite public/llms.txt
npm run llms:check    # what CI runs: fails if the committed file is out of date
```

## Style

Prose is checked by [Vale](https://vale.sh) with the rules in `.github/styles`. CI runs it on
pull requests that change Markdown and fails on errors. If you have Vale installed, run the same
check from the repository root:

```bash
vale --minAlertLevel=error docs
```
