/**
 * P2-03 · Tools CRUD + encrypted secrets.
 *
 * Writes to the `user_tools` table via the `/api/create_tool`,
 * `/api/update_tool`, `/api/update_tool_status`, and `/api/delete_tool`
 * endpoints (the same calls the UI issues from `frontend/src/settings/Tools.tsx`
 * + `ToolConfig.tsx` + `AddToolModal.tsx` + `ConfigToolModal.tsx`). Each test
 * provisions its own user via `newUserContext` and resets the DB in
 * `beforeEach`.
 *
 * Brave Search is a connector-backed tool: with ENCRYPTION_SECRET_KEY set (the
 * e2e env sets it), `/api/create_tool` stores the pasted secret encrypted on a
 * `connector_sessions` row (a "connection") and the `user_tools` row only
 * points at it through `connection_id`. The tool's own `config` keeps the
 * non-secret keys. The specs below follow the secret to the connection.
 *
 * // Silent-break covered: blank-secret update merges, does not wipe the
 *    secret. The UI's `buildConfigToSave` strips blank secret fields, so an
 *    edit that doesn't re-enter the token sends a config without it.
 *    `_update_connection_secrets` in docsgpt/api/user/tools/routes.py only
 *    rewrites the connection when the request carries a secret, so after a
 *    blank-secret update the encrypted blob must be byte-for-byte unchanged
 *    and /api/get_tools must still report `has_encrypted_credentials: true`.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { APIRequestContext } from '@playwright/test';

import { authedRequest } from '../../helpers/api.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';
import { newUserContext } from '../../helpers/auth.js';

// Brave Search has the simplest required-secret schema on the server:
// exactly one required + secret string field called `token` (see
// docsgpt/agents/tools/brave.py:get_config_requirements).
const BRAVE_TOOL_NAME = 'brave';
const BRAVE_DISPLAY_NAME = 'Brave Search';
const BRAVE_DESCRIPTION =
  'A tool for performing web and image searches using the Brave Search API.';
const INITIAL_SECRET = 'brave-secret-initial-abc123';
const REPLACEMENT_SECRET = 'brave-secret-rotated-xyz789';

interface UserToolRow {
  id: string;
  user_id: string;
  name: string;
  custom_name: string | null;
  display_name: string | null;
  description: string | null;
  // pg parses JSONB to JS values
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  config: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  config_requirements: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  actions: any;
  status: boolean;
  connection_id: string | null;
}

async function fetchToolRow(toolId: string): Promise<UserToolRow | null> {
  const { rows } = await pg.query<UserToolRow>(
    `SELECT id::text AS id, user_id, name, custom_name, display_name,
            description, config, config_requirements, actions, status,
            connection_id::text AS connection_id
     FROM user_tools WHERE id = CAST($1 AS uuid)`,
    [toolId],
  );
  return rows[0] ?? null;
}

/** The encrypted secret blob on the connection the tool points at, or null. */
async function fetchConnectionSecret(toolId: string): Promise<string | null> {
  const { rows } = await pg.query<{ encrypted_credentials: string | null }>(
    `SELECT c.encrypted_credentials
     FROM user_tools t JOIN connector_sessions c ON c.id = t.connection_id
     WHERE t.id = CAST($1 AS uuid)`,
    [toolId],
  );
  return rows[0]?.encrypted_credentials ?? null;
}

async function createBraveTool(
  api: APIRequestContext,
  secret: string = INITIAL_SECRET,
  customName: string = 'my-brave-initial',
): Promise<string> {
  const createRes = await api.post('/api/create_tool', {
    data: {
      name: BRAVE_TOOL_NAME,
      displayName: BRAVE_DISPLAY_NAME,
      description: BRAVE_DESCRIPTION,
      config: { token: secret },
      customName,
      status: true,
    },
  });
  expect(createRes.status()).toBe(200);
  const body = (await createRes.json()) as { id: string };
  expect(body.id).toBeTruthy();
  return body.id;
}

test.describe('tier-a · user_tools CRUD', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('create brave_search tool with required secret — row persists and encrypted_credentials is non-null', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      // Drive the UI at least once: open the Tools settings page so we exercise
      // the real render path (list fetch, empty-state, etc.) before flipping to
      // API-direct for the encrypted-credentials assertion. The full modal-ful
      // creation flow is not feasible under our serial-timeout budget, so the
      // actual write goes through the same POST /api/create_tool endpoint that
      // AddToolModal.tsx + ConfigToolModal.tsx ultimately call.
      const page = await context.newPage();
      await page.goto('/settings/tools');
      await expect(page).toHaveURL(/\/settings\/tools$/);

      // Confirm the available_tools catalog served by the backend offers brave_search.
      const availableRes = await api.get('/api/available_tools');
      expect(availableRes.status()).toBe(200);
      const available = (await availableRes.json()) as {
        success: boolean;
        data: Array<{ name: string }>;
      };
      expect(available.success).toBe(true);
      expect(available.data.some((t) => t.name === BRAVE_TOOL_NAME)).toBe(true);

      const toolId = await createBraveTool(api);

      // DB-level: one user_tools row for this user.
      const { rows: countRows } = await pg.query<{ n: string }>(
        'SELECT count(*)::text AS n FROM user_tools WHERE user_id = $1',
        [sub],
      );
      expect(Number(countRows[0]?.n ?? 0)).toBe(1);

      const row = await fetchToolRow(toolId);
      expect(row).not.toBeNull();
      const persisted = row!;
      expect(persisted.user_id).toBe(sub);
      expect(persisted.name).toBe(BRAVE_TOOL_NAME);
      // A connection-backed tool is shown under the name the user gave it.
      expect(persisted.display_name).toBe('my-brave-initial');
      expect(persisted.custom_name).toBe('my-brave-initial');
      expect(persisted.status).toBe(true);
      expect(persisted.connection_id).toBeTruthy();

      // Neither the plaintext secret nor a copy of it lands in the tool config.
      expect(persisted.config).toBeTruthy();
      expect(persisted.config.token).toBeUndefined();
      expect(persisted.config.encrypted_credentials).toBeUndefined();

      // The secret lives encrypted on the connection.
      const secret = await fetchConnectionSecret(toolId);
      expect(typeof secret).toBe('string');
      expect(secret!.length).toBeGreaterThan(0);
      expect(secret).not.toContain(INITIAL_SECRET);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('update non-secret config with blank secret field preserves encrypted_credentials byte-for-byte (silent-break)', async ({
    browser,
  }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const toolId = await createBraveTool(api);
      const encryptedBefore = await fetchConnectionSecret(toolId);
      expect(encryptedBefore).toBeTruthy();

      // Mirror what ToolConfig.tsx + buildConfigToSave() send on a display-name
      // edit with no secret re-entry: the `config` payload contains ONLY
      // non-secret keys (the secret `token` is stripped entirely because it's
      // blank). This is the exact shape that routes through
      // `_merge_secrets_on_update` — the silent-break surface.
      const updateRes = await api.post('/api/update_tool', {
        data: {
          id: toolId,
          name: BRAVE_TOOL_NAME,
          displayName: BRAVE_DISPLAY_NAME,
          customName: 'my-brave-renamed',
          description: BRAVE_DESCRIPTION,
          config: {}, // no secret, no other keys — the canonical blank-secret case
          actions: [],
          status: true,
        },
      });
      expect(updateRes.status()).toBe(200);

      const after = await fetchToolRow(toolId);
      expect(after).not.toBeNull();
      // Non-secret update landed.
      expect(after!.custom_name).toBe('my-brave-renamed');
      // THE silent-break assertion: a blank-secret update leaves the
      // connection's encrypted blob untouched, byte for byte.
      expect(await fetchConnectionSecret(toolId)).toBe(encryptedBefore);
      expect(after!.config.token).toBeUndefined();
      // API surface must continue to report the secret is there.
      const listRes = await api.get('/api/get_tools');
      expect(listRes.status()).toBe(200);
      const listBody = (await listRes.json()) as {
        success: boolean;
        tools: Array<{ id: string; config: Record<string, unknown> }>;
      };
      const tool = listBody.tools.find((t) => t.id === toolId);
      expect(tool).toBeDefined();
      expect(tool!.config.has_encrypted_credentials).toBe(true);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('update tool supplying a new secret rotates encrypted_credentials', async ({
    browser,
  }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const toolId = await createBraveTool(api);
      const encryptedBefore = await fetchConnectionSecret(toolId);
      expect(encryptedBefore).toBeTruthy();

      const updateRes = await api.post('/api/update_tool', {
        data: {
          id: toolId,
          name: BRAVE_TOOL_NAME,
          displayName: BRAVE_DISPLAY_NAME,
          customName: 'my-brave-initial',
          description: BRAVE_DESCRIPTION,
          config: { token: REPLACEMENT_SECRET },
          actions: [],
          status: true,
        },
      });
      expect(updateRes.status()).toBe(200);

      const after = await fetchToolRow(toolId);
      const encryptedAfter = await fetchConnectionSecret(toolId);
      expect(encryptedAfter).toBeTruthy();
      // New blob must differ from the old one and must not contain plaintext.
      expect(encryptedAfter).not.toBe(encryptedBefore);
      expect(encryptedAfter).not.toContain(REPLACEMENT_SECRET);
      // Plaintext must not bleed into the stored config.
      expect(after!.config.token).toBeUndefined();
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('toggle tool status off then on — status column flips each time', async ({
    browser,
  }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const toolId = await createBraveTool(api);

      const offRes = await api.post('/api/update_tool_status', {
        data: { id: toolId, status: false },
      });
      expect(offRes.status()).toBe(200);

      let row = await fetchToolRow(toolId);
      expect(row!.status).toBe(false);
      // Secrets unaffected by a pure status flip.
      expect(typeof (await fetchConnectionSecret(toolId))).toBe('string');

      const onRes = await api.post('/api/update_tool_status', {
        data: { id: toolId, status: true },
      });
      expect(onRes.status()).toBe(200);

      row = await fetchToolRow(toolId);
      expect(row!.status).toBe(true);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('delete tool — row is gone from user_tools', async ({ browser }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const toolId = await createBraveTool(api);

      const delRes = await api.post('/api/delete_tool', {
        data: { id: toolId },
      });
      expect(delRes.status()).toBe(200);

      const row = await fetchToolRow(toolId);
      expect(row).toBeNull();

      const { rows: countRows } = await pg.query<{ n: string }>(
        'SELECT count(*)::text AS n FROM user_tools WHERE user_id = $1',
        [sub],
      );
      expect(Number(countRows[0]?.n ?? 0)).toBe(0);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('cross-tenant isolation — user B cannot read, update, or delete user A tool', async ({
    browser,
  }) => {
    const userA = await newUserContext(browser, { sub: 'e2e-tools-user-a' });
    const userB = await newUserContext(browser, { sub: 'e2e-tools-user-b' });
    const apiA = await authedRequest(playwright, userA.token);
    const apiB = await authedRequest(playwright, userB.token);
    try {
      const toolId = await createBraveTool(apiA);

      // User B's /api/get_tools must NOT include user A's tool.
      const listB = await apiB.get('/api/get_tools');
      expect(listB.status()).toBe(200);
      const listBody = (await listB.json()) as {
        success: boolean;
        tools: Array<{ id: string }>;
      };
      expect(listBody.success).toBe(true);
      expect(listBody.tools.find((t) => t.id === toolId)).toBeUndefined();

      // User B cannot flip the status — scoped get_any returns nothing →
      // endpoint returns the documented 404 {success:false, message:"Tool not found"}.
      const statusRes = await apiB.post('/api/update_tool_status', {
        data: { id: toolId, status: false },
      });
      expect(statusRes.status()).toBe(404);
      expect(await statusRes.json()).toEqual({
        success: false,
        message: 'Tool not found',
      });

      // And cannot delete.
      const delRes = await apiB.post('/api/delete_tool', {
        data: { id: toolId },
      });
      expect(delRes.status()).toBe(404);
      expect(await delRes.json()).toEqual({
        success: false,
        message: 'Tool not found',
      });

      // DB-level proof: the row is still owned by user A, untouched.
      const row = await fetchToolRow(toolId);
      expect(row).not.toBeNull();
      expect(row!.user_id).toBe(userA.sub);
      expect(row!.status).toBe(true);
    } finally {
      await apiA.dispose();
      await apiB.dispose();
      await userA.context.close();
      await userB.context.close();
    }
  });
});
