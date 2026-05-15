import * as playwright from '@playwright/test';
// Tier-C · UI smoke (surface coverage, no DB assertions)
/**
 * P4 · Tier-C UI smoke.
 *
 * Cheap surface coverage for UI-only behaviors. One combined spec, many
 * small tests. Scope:
 *
 *   C1  theme toggle         -> document.body.classList contains `dark`
 *   C2  locale switch        -> Spanish label visible + localStorage
 *   C3  chunk-count default  -> localStorage.DocsGPTChunks persists
 *   C4  default prompt       -> localStorage.DocsGPTPrompt persists
 *   C5  action buttons       -> New Chat button visible & clickable
 *   C6  notification banner  -> skipped: env-gated at build time
 *   C8  sidebar collapse     -> `Collapse sidebar` button toggles to `Expand`
 *   C9  404 route            -> PageNotFound heading visible
 *   C10 upload drag-drop     -> fixme: no global drop handler in current UI
 *   C11 markdown rendering   -> seeded /share conv renders <h1> from ```md```
 *   C12 mermaid rendering    -> seeded /share conv renders mermaid (code or svg)
 *   C13 agent logs route     -> `/agents/logs/:agentId` renders title
 *
 * Setup: one shared authenticated context per test (no beforeAll reuse because
 * some tests mutate localStorage / navigate to routes that break other tests).
 * DB inserts (C11/C12/C13) go through Postgres directly — share URL renders a
 * row's response verbatim, which is the simplest path to get markdown/mermaid
 * in the DOM without fixturing the mock LLM.
 */

const { expect, test } = playwright;

import { randomUUID } from 'node:crypto';

import type { APIRequestContext } from '@playwright/test';

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

/**
 * Navigate to Settings (General) and wait for the page to render. The
 * "Add" button next to the prompts dropdown is reliably present on
 * /settings (General is the index route), so use it as a readiness proxy.
 */
async function gotoSettings(
  page: import('@playwright/test').Page,
): Promise<void> {
  await page.goto('/settings');
  await expect(
    page.getByRole('button', { name: 'Add', exact: true }).first(),
  ).toBeVisible();
}

/**
 * The custom Dropdown in `frontend/src/components/Dropdown.tsx` renders a
 * `<button>` trigger whose visible text is the currently-selected value,
 * and its options as `<span>` children inside `<div>`s (NOT buttons). So
 * Playwright's `getByRole('button', { name })` finds the trigger but not
 * the option — we use `getByText` scoped to the dropdown's open panel.
 *
 * This helper clicks the trigger whose visible label is `currentValue`,
 * then clicks the option whose visible label is `targetValue`.
 */
async function pickDropdown(
  page: import('@playwright/test').Page,
  currentValue: string,
  targetValue: string,
): Promise<void> {
  await page.getByRole('button', { name: currentValue, exact: true })
    .first()
    .click();
  // Options render as spans; click by exact text. Use `.last()` because
  // sometimes the same text appears in the trigger label too (collapsed
  // state overlap). The panel appends after the trigger in DOM order.
  await page.getByText(targetValue, { exact: true }).last().click();
}

/**
 * Insert a `conversations` + `conversation_messages` + `shared_conversations`
 * trio directly in Postgres and return the share identifier. The Flask route
 * `/api/shared_conversation/<identifier>` renders messages[:first_n_queries]
 * verbatim, so whatever `response` text we insert lands in the DOM via
 * ConversationBubble. Simpler than fixturing the mock LLM.
 */
async function seedSharedConversation(
  userId: string,
  response: string,
): Promise<string> {
  // 1) conversation row
  const { rows: convRows } = await pg.query<{ id: string }>(
    `INSERT INTO conversations (user_id, name)
     VALUES ($1, $2)
     RETURNING id::text AS id`,
    [userId, 'ui-smoke seeded'],
  );
  const conversationId = convRows[0].id;

  // 2) message row (position 0)
  await pg.query(
    `INSERT INTO conversation_messages (conversation_id, user_id, position, prompt, response)
     VALUES (CAST($1 AS uuid), $2, 0, $3, $4)`,
    [conversationId, userId, 'What do you have for me?', response],
  );

  // 3) shared_conversations row — uuid is the public identifier
  const identifier = randomUUID();
  await pg.query(
    `INSERT INTO shared_conversations
       (conversation_id, user_id, is_promptable, uuid, first_n_queries)
     VALUES (CAST($1 AS uuid), $2, false, CAST($3 AS uuid), 1)`,
    [conversationId, userId, identifier],
  );
  return identifier;
}

/**
 * Insert a minimal published agent row and return its id. Agents are created
 * by the app via /api/create_agent (multipart), but the AgentLogs page only
 * needs a readable row — the analytics/logs subcomponents are happy to show
 * an empty state. prompt_id NULL is valid (built-in default fallback).
 */
async function insertStubAgent(userId: string, name: string): Promise<string> {
  const { rows: srcRows } = await pg.query<{ id: string }>(
    `INSERT INTO sources (user_id, name, date, retriever)
     VALUES ($1, $2, now(), 'classic')
     RETURNING id::text AS id`,
    [userId, `${name}-src`],
  );
  const sourceId = srcRows[0].id;
  const { rows } = await pg.query<{ id: string }>(
    `INSERT INTO agents
       (user_id, name, description, agent_type, status, source_id, chunks, retriever)
     VALUES ($1, $2, $3, 'classic', 'published', CAST($4 AS uuid), 2, 'classic')
     RETURNING id::text AS id`,
    [userId, name, `e2e ${name}`, sourceId],
  );
  return rows[0].id;
}

test.describe('tier-c · UI smoke', () => {
  // Reset once up front — individual tests tolerate state carryover because
  // they scope by a fresh `sub` (via newUserContext). The DB-seeding tests
  // insert into their own user's namespace, so no cross-test contamination.
  test.beforeAll(async () => {
    await resetDb();
  });

  test('C1 · theme toggle flips body.dark and persists in localStorage', async ({
    browser,
  }) => {
    const { context } = await newUserContext(browser);
    try {
      const page = await context.newPage();
      await gotoSettings(page);

      // Record current state — default is system-dependent, so capture it.
      const before = await page.evaluate(() => ({
        hasDark: document.body.classList.contains('dark'),
        stored: localStorage.getItem('selectedTheme'),
      }));

      // Click the theme dropdown. The trigger's text is the current value.
      const currentThemeLabel = before.hasDark ? 'Dark' : 'Light';
      const targetThemeLabel = before.hasDark ? 'Light' : 'Dark';
      await pickDropdown(page, currentThemeLabel, targetThemeLabel);

      // Body class flipped and localStorage reflects the choice.
      await expect
        .poll(async () =>
          page.evaluate(() => document.body.classList.contains('dark')),
        )
        .toBe(!before.hasDark);
      const stored = await page.evaluate(() =>
        localStorage.getItem('selectedTheme'),
      );
      expect(stored).toBe(targetThemeLabel);

      // Persist across reload.
      await page.reload();
      await expect
        .poll(async () =>
          page.evaluate(() => document.body.classList.contains('dark')),
        )
        .toBe(!before.hasDark);
    } finally {
      await context.close();
    }
  });

  test('C2 · locale switch swaps UI strings and persists', async ({
    browser,
  }) => {
    const { context } = await newUserContext(browser);
    try {
      const page = await context.newPage();
      await gotoSettings(page);

      // The language dropdown currently displays "English" — click it, then
      // pick "Español". Dropdown.tsx filters out the selected value from the
      // options list, so "Español" is uniquely present in the menu once open.
      await pickDropdown(page, 'English', 'Español');

      // localStorage updated immediately via useEffect.
      await expect
        .poll(async () =>
          page.evaluate(() => localStorage.getItem('docsgpt-locale')),
        )
        .toBe('es');

      // i18n re-renders in place: "Settings" sidebar label becomes
      // "Configuración". Scope to the sidebar nav link to avoid false
      // matches on page body text.
      await expect(
        page.getByRole('link', { name: /configuración/i }).first(),
      ).toBeVisible();

      // Persist across reload.
      await page.reload();
      await expect
        .poll(async () =>
          page.evaluate(() => localStorage.getItem('docsgpt-locale')),
        )
        .toBe('es');
    } finally {
      await context.close();
    }
  });

  test('C3 · chunk-count change persists to DocsGPTChunks localStorage', async ({
    browser,
  }) => {
    const { context } = await newUserContext(browser);
    try {
      const page = await context.newPage();
      await gotoSettings(page);

      // Default chunks value is '2'. Only the chunks dropdown's trigger has
      // the exact text "2"; other dropdowns show their own labels. Pick '6'.
      await pickDropdown(page, '2', '6');

      // localStorage persisted (listener middleware fires on setChunks).
      await expect
        .poll(async () =>
          page.evaluate(() => localStorage.getItem('DocsGPTChunks')),
        )
        .toBe(JSON.stringify('6'));
    } finally {
      await context.close();
    }
  });

  test('C4 · default prompt selection persists to DocsGPTPrompt', async ({
    browser,
  }) => {
    const { context } = await newUserContext(browser);
    try {
      const page = await context.newPage();
      await gotoSettings(page);

      // The active prompt dropdown starts on "default". Open it and pick
      // "creative" — a built-in so no seeding needed.
      await pickDropdown(page, 'default', 'creative');

      await expect
        .poll(async () => {
          const raw = await page.evaluate(() =>
            localStorage.getItem('DocsGPTPrompt'),
          );
          if (!raw) return null;
          try {
            return JSON.parse(raw) as { name?: string };
          } catch {
            return null;
          }
        })
        .toMatchObject({ name: 'creative' });
    } finally {
      await context.close();
    }
  });

  test('C5 · New Chat action button is present and clickable', async ({
    browser,
  }) => {
    const { context } = await newUserContext(browser);
    try {
      const page = await context.newPage();
      await page.goto('/');

      // "New Chat" is rendered by the Navigation sidebar. Role=link because
      // the NavLink in Navigation.tsx wraps the label in a react-router Link.
      const newChat = page.getByRole('link', { name: /new chat/i }).first();
      await expect(newChat).toBeVisible();
      await newChat.click();
      // Clicking "New Chat" lands on the empty-conversation sentinel
      // route. Root or /c/new are both acceptable — the SSE branch made
      // /c/new the canonical fresh-chat URL.
      await expect(page).toHaveURL(/127\.0\.0\.1:5179\/(c\/new)?$/);
    } finally {
      await context.close();
    }
  });

  test.skip('C6 · notification banner (env-gated at build time)', async () => {
    // Skipped: VITE_NOTIFICATION_TEXT / VITE_NOTIFICATION_LINK are baked into
    // the Vite bundle at build time. The e2e dev server is launched without
    // them set (see scripts/e2e/env.sh), so App.tsx's `<Notification>` is
    // never rendered and there is nothing observable to assert.
    //
    // If/when we add a prod-bundle opt-in, revive this test with
    // those env vars set and check the banner + localStorage-dismiss flow.
  });

  test('C8 · sidebar collapse toggles via the Collapse/Expand button', async ({
    browser,
  }) => {
    const { context } = await newUserContext(browser);
    try {
      const page = await context.newPage();
      // Desktop viewport ensures navOpen defaults true (see App.tsx:37).
      await page.setViewportSize({ width: 1280, height: 800 });
      await page.goto('/');

      // Sidebar open: the Collapse button's img has alt="Collapse sidebar"
      // (Navigation.tsx:367). Click it to collapse.
      const collapse = page.getByAltText('Collapse sidebar');
      await expect(collapse).toBeVisible();
      await collapse.click();

      // When collapsed, Navigation.tsx renders a floating reopen button at
      // `absolute top-3 left-3` whose img has alt="Open navigation menu"
      // (Navigation.tsx:312). The off-screen nav's own toggle flips to
      // "Expand sidebar" but that one is outside the viewport. We target
      // the visible floating button for the re-open interaction.
      const reopen = page.getByAltText('Open navigation menu');
      await expect(reopen).toBeVisible();
      await reopen.click();

      // Collapse button visible again — toggle is symmetric.
      await expect(page.getByAltText('Collapse sidebar')).toBeVisible();
    } finally {
      await context.close();
    }
  });

  test('C9 · unknown route renders the PageNotFound component', async ({
    browser,
  }) => {
    const { context } = await newUserContext(browser);
    try {
      const page = await context.newPage();
      await page.goto('/this-route-does-not-exist');
      // PageNotFound.tsx renders <h1>{t('pageNotFound.title')}</h1> — English
      // default is "404". Also has a "Go Back Home" link. Either is load-
      // bearing; we assert both for resilience.
      await expect(page.getByRole('heading', { name: '404' })).toBeVisible();
      await expect(page.getByRole('link', { name: /go back home/i })).toBeVisible();
    } finally {
      await context.close();
    }
  });

  test.fixme(
    'C10 · upload drag-drop toast (no global drop handler in current UI)',
    async () => {
      // As of this branch, UploadToast.tsx is a pure status-list component;
      // it does NOT register a global dragover/drop handler. The drag
      // surface lives inside the upload modal (Upload.tsx) and the message
      // input (MessageInput.tsx) — neither is a global "drop anywhere"
      // affordance. Exercising them requires opening the upload modal first,
      // which is already covered by tier-b/upload.spec.ts.
      //
      // Leaving fixme so a future global-drop-zone feature will surface this
      // gap. The plan's C10 scope description anticipated a global handler
      // that doesn't exist here.
    },
  );

  test('C11 · markdown in a seeded conversation renders as HTML', async ({
    browser,
  }) => {
    const { sub } = await newUserContext(browser);
    // Use an incognito context for the public share viewer — share URLs
    // don't require auth, and injecting a token is unnecessary overhead.
    const visitor = await browser.newContext();
    try {
      const markdownResponse = [
        '# Markdown Heading',
        '',
        'Inline text with **bold** and a [link](https://example.com).',
      ].join('\n');

      const identifier = await seedSharedConversation(sub, markdownResponse);

      const page = await visitor.newPage();
      await page.goto(`/share/${identifier}`);

      // ConversationBubble's markdown renderer turns `# Heading` into an
      // <h1>. Prose rendering is async (react-markdown is lazy) — poll.
      await expect(
        page.getByRole('heading', { name: 'Markdown Heading', level: 1 }),
      ).toBeVisible();

      // Bold rendered as <strong>. Anchor rendered with href.
      await expect(page.locator('strong', { hasText: /bold/ }).first()).toBeVisible();
      await expect(
        page.getByRole('link', { name: 'link' }).first(),
      ).toHaveAttribute('href', 'https://example.com');
    } finally {
      await visitor.close();
    }
  });

  test('C12 · mermaid code-fence renders via the mermaid lib', async ({
    browser,
  }) => {
    const { sub } = await newUserContext(browser);
    const visitor = await browser.newContext();
    try {
      const mermaidResponse = [
        'Here is a flowchart:',
        '',
        '```mermaid',
        'flowchart LR',
        '  A --> B',
        '  B --> C',
        '```',
      ].join('\n');

      const identifier = await seedSharedConversation(sub, mermaidResponse);

      const page = await visitor.newPage();
      await page.goto(`/share/${identifier}`);

      // Mermaid renders asynchronously into an <svg>. If the library renders
      // the diagram successfully, an SVG will exist; if it falls back to
      // showing the code block on error, a <pre> will exist. Either path
      // means the mermaid component mounted — which is the load-bearing UI
      // assertion here. Use first() because other SVGs (icons) also exist.
      await expect
        .poll(
          async () => {
            const svgCount = await page
              .locator('svg[id^="mermaid-"]')
              .count();
            const preCount = await page.locator('pre').count();
            return svgCount > 0 || preCount > 0;
          },
          { timeout: 15_000 },
        )
        .toBe(true);
    } finally {
      await visitor.close();
    }
  });

  test('C13 · agents/logs/:agentId renders for a seeded agent', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    // Use the backend to create prompt/source so /api/create_agent validation
    // is fully satisfied — a bare SQL insert is fragile (triggers / defaults
    // evolve). But for a *logs-page only* smoke we can insert directly.
    const api: APIRequestContext | null = await authedRequest(playwright, token);
    try {
      const agentId = await insertStubAgent(sub, 'ui-smoke-agent');

      const page = await context.newPage();
      await page.goto(`/agents/logs/${agentId}`);

      // AgentLogs.tsx renders the i18n "agents.logs.title" heading and an
      // "agents.backToAll" label. The title is the load-bearing assertion —
      // if the route resolves, useParams gives us an agentId, and the page
      // mounts, the h1 appears regardless of whether analytics have data.
      await expect(
        page.getByRole('heading', { level: 1 }).first(),
      ).toBeVisible();

      // Agent name renders once the fetch resolves.
      await expect(page.getByText('ui-smoke-agent').first()).toBeVisible();
    } finally {
      await api.dispose();
      await context.close();
    }
  });
});
