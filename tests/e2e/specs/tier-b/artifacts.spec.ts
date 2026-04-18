// Phase 3 Tier-B · B15 artifact sidebar (todos / notes / memory) + legacy fallback.
/**
 * The UI's artifact sidebar (`frontend/src/components/ArtifactSidebar.tsx`)
 * opens on a question that triggered a tool call that wrote a `note` or a
 * `todo_list` and reads from `GET /api/artifact/<artifact_id>` (see
 * `application/api/user/tools/routes.py` — `GetArtifact`). The route is
 * also exercised on reload of an older conversation whose stored artifact id
 * is a legacy Mongo ObjectId — the todos repository has a `get_by_legacy_id`
 * fallback explicitly for that case.
 *
 * Rather than drive a full tool end-to-end (which pulls in Celery-scheduled
 * tool execution), we insert fixture rows into `notes` / `todos` / `memories`
 * directly — the shape is locked by alembic 0001_initial and the route reads
 * straight off those tables via the repository layer.
 *
 * Covered:
 *   1. notes: `GET /api/artifact/<note-uuid>` returns artifact_type=note
 *      with the note content and line_count.
 *   2. todos: `GET /api/artifact/<todo-uuid>` returns artifact_type=todo_list
 *      with all todos in the owning user_tool and open/completed counts.
 *   3. legacy fallback: a todo row inserted with `legacy_mongo_id` set to an
 *      ObjectId-shaped hex string resolves via `GET /api/artifact/<legacy-id>`.
 *   4. cross-tenant: user B's request for user A's note 404s (repositories
 *      are user-scoped, and the legacy fallback additionally re-checks the
 *      owning user_id before returning).
 *   5. cascade delete: dropping the owning `user_tools` row cascades the
 *      artifact rows (notes/todos FK ON DELETE CASCADE). Asserted via SQL.
 *   6. memories: route does not (yet) serve memory artifacts — asserted
 *      here as a 404 so a future route extension flips this test loudly.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { countRows, pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

/**
 * Insert a minimal `user_tools` row owned by `userId`. The artifact tables
 * (`notes`, `todos`, `memories`) all `REFERENCES user_tools(id) ON DELETE CASCADE`
 * so every fixture artifact needs a parent tool.
 */
async function insertUserTool(userId: string, customName: string): Promise<string> {
  const { rows } = await pg.query<{ id: string }>(
    `INSERT INTO user_tools (user_id, name, custom_name, display_name, description)
     VALUES ($1, 'notes', $2, 'Notes (fixture)', 'e2e fixture')
     RETURNING id::text AS id`,
    [userId, customName],
  );
  const id = rows[0]?.id;
  if (!id) throw new Error('insertUserTool: no id returned');
  return id;
}

async function insertNote(
  userId: string,
  toolId: string,
  title: string,
  content: string,
): Promise<string> {
  const { rows } = await pg.query<{ id: string }>(
    `INSERT INTO notes (user_id, tool_id, title, content)
     VALUES ($1, CAST($2 AS uuid), $3, $4)
     RETURNING id::text AS id`,
    [userId, toolId, title, content],
  );
  const id = rows[0]?.id;
  if (!id) throw new Error('insertNote: no id returned');
  return id;
}

/**
 * Insert a todo row. `todoId` is the per-tool monotonic integer the LLM uses
 * as its handle (see `todos_tool_todo_id_uidx`). `legacyMongoId` is optional
 * — set it to exercise the `get_by_legacy_id` fallback path.
 */
async function insertTodo(
  userId: string,
  toolId: string,
  todoId: number,
  title: string,
  opts: { completed?: boolean; legacyMongoId?: string | null } = {},
): Promise<string> {
  const { rows } = await pg.query<{ id: string }>(
    `INSERT INTO todos (user_id, tool_id, todo_id, title, completed, legacy_mongo_id)
     VALUES ($1, CAST($2 AS uuid), $3, $4, $5, $6)
     RETURNING id::text AS id`,
    [
      userId,
      toolId,
      todoId,
      title,
      opts.completed ?? false,
      opts.legacyMongoId ?? null,
    ],
  );
  const id = rows[0]?.id;
  if (!id) throw new Error('insertTodo: no id returned');
  return id;
}

async function insertMemory(
  userId: string,
  toolId: string,
  path: string,
  content: string,
): Promise<string> {
  const { rows } = await pg.query<{ id: string }>(
    `INSERT INTO memories (user_id, tool_id, path, content)
     VALUES ($1, CAST($2 AS uuid), $3, $4)
     RETURNING id::text AS id`,
    [userId, toolId, path, content],
  );
  const id = rows[0]?.id;
  if (!id) throw new Error('insertMemory: no id returned');
  return id;
}

test.describe('tier-b · artifacts (todo/note sidebar)', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('GET /api/artifact/<note-uuid> returns a shaped note artifact', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const toolId = await insertUserTool(sub, 'notes-fixture');
      const content = 'line one\nline two\nline three';
      const noteId = await insertNote(sub, toolId, 'Meeting notes', content);

      const res = await api.get(`/api/artifact/${noteId}`);
      expect(res.status()).toBe(200);
      const body = (await res.json()) as {
        success: boolean;
        artifact: {
          artifact_type: string;
          data: { content: string; line_count: number; updated_at?: string };
        };
      };
      expect(body.success).toBe(true);
      expect(body.artifact.artifact_type).toBe('note');
      expect(body.artifact.data.content).toBe(content);
      expect(body.artifact.data.line_count).toBe(3);
      // updated_at is NOT NULL (DB default now()); it should come back as an
      // ISO-ish string and not `null`.
      expect(body.artifact.data.updated_at ?? '').not.toBe('');
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('GET /api/artifact/<todo-uuid> returns todo_list with all sibling todos', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const toolId = await insertUserTool(sub, 'todos-fixture');
      // Three siblings: two open, one completed. The requested todo is #2,
      // but the artifact response returns the whole list.
      const aId = await insertTodo(sub, toolId, 1, 'write tests');
      void aId;
      const bId = await insertTodo(sub, toolId, 2, 'ship feature');
      const cId = await insertTodo(sub, toolId, 3, 'celebrate', {
        completed: true,
      });
      void cId;

      const res = await api.get(`/api/artifact/${bId}`);
      expect(res.status()).toBe(200);
      const body = (await res.json()) as {
        success: boolean;
        artifact: {
          artifact_type: string;
          data: {
            items: Array<{ todo_id: number; title: string; status: string }>;
            total_count: number;
            open_count: number;
            completed_count: number;
          };
        };
      };
      expect(body.success).toBe(true);
      expect(body.artifact.artifact_type).toBe('todo_list');
      expect(body.artifact.data.total_count).toBe(3);
      expect(body.artifact.data.open_count).toBe(2);
      expect(body.artifact.data.completed_count).toBe(1);

      // The route sorts by todo_id (nulls last, then created_at) per
      // TodosRepository.list_for_tool — assert that ordering.
      const titles = body.artifact.data.items.map((t) => t.title);
      expect(titles).toEqual(['write tests', 'ship feature', 'celebrate']);
      const statuses = body.artifact.data.items.map((t) => t.status);
      expect(statuses).toEqual(['open', 'open', 'completed']);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('legacy fallback: UUID-shaped legacy_mongo_id resolves via get_by_legacy_id', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const toolId = await insertUserTool(sub, 'legacy-todo-fixture');
      // Using a UUID-shaped string as the stored `legacy_mongo_id` to
      // exercise the get_by_legacy_id branch. The ObjectId-shaped case
      // (24 hex chars) is covered by the separately-fixmed test below
      // which documents the known backend bug.
      const legacyId = 'aaaabbbb-cccc-dddd-eeee-ffff00001111';
      const pgUuid = await insertTodo(sub, toolId, 1, 'legacy-referenced', {
        legacyMongoId: legacyId,
      });

      // Requesting by the legacy id should resolve to the same row via the
      // repo's `get_by_legacy_id` fallback. The preceding `notes.get` +
      // `todos.get` both miss cleanly (UUID cast is valid, just no row)
      // so the SQLAlchemy transaction stays healthy into the fallback.
      const res = await api.get(`/api/artifact/${legacyId}`);
      expect(res.status()).toBe(200);
      const body = (await res.json()) as {
        success: boolean;
        artifact: {
          artifact_type: string;
          data: { items: Array<{ todo_id: number; title: string }> };
        };
      };
      expect(body.success).toBe(true);
      expect(body.artifact.artifact_type).toBe('todo_list');
      expect(body.artifact.data.items).toHaveLength(1);
      expect(body.artifact.data.items[0].title).toBe('legacy-referenced');

      // And the canonical PG id still works too — fallback doesn't mask it.
      const pgRes = await api.get(`/api/artifact/${pgUuid}`);
      expect(pgRes.status()).toBe(200);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test(
    'legacy fallback: non-UUID ObjectId-shaped legacy_mongo_id resolves via get_by_legacy_id',
    async ({ browser }) => {
      const { context, sub, token } = await newUserContext(browser);
      const api = await authedRequest(playwright, token);
      try {
        const toolId = await insertUserTool(sub, 'legacy-objectid-fixture');
        const legacyId = '6123456789abcdef01234567';
        await insertTodo(sub, toolId, 1, 'legacy-objectid', {
          legacyMongoId: legacyId,
        });
        const res = await api.get(`/api/artifact/${legacyId}`);
        expect(res.status()).toBe(200);
      } finally {
        await api.dispose();
        await context.close();
      }
    },
  );

  test('cross-tenant: user B cannot fetch user A artifact (note → 404)', async ({
    browser,
  }) => {
    const userA = await newUserContext(browser, { sub: 'e2e-artifact-user-a' });
    const userB = await newUserContext(browser, { sub: 'e2e-artifact-user-b' });
    const apiA = await authedRequest(playwright, userA.token);
    const apiB = await authedRequest(playwright, userB.token);
    try {
      const toolA = await insertUserTool(userA.sub, 'a-notes');
      const noteA = await insertNote(
        userA.sub,
        toolA,
        'A private',
        'secret stuff',
      );

      // User A gets a 200.
      const resA = await apiA.get(`/api/artifact/${noteA}`);
      expect(resA.status()).toBe(200);

      // User B must NOT see it. The repo's `.get(id, user_id)` filters on
      // user_id, so the lookup misses and the route returns 404.
      const resB = await apiB.get(`/api/artifact/${noteA}`);
      expect(resB.status()).toBe(404);
      const body = (await resB.json()) as { success: boolean };
      expect(body.success).toBe(false);
    } finally {
      await apiA.dispose();
      await apiB.dispose();
      await userA.context.close();
      await userB.context.close();
    }
  });

  test('cascade: deleting the owning user_tools row removes every artifact for that tool', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const toolId = await insertUserTool(sub, 'cascade-fixture');
      const noteId = await insertNote(sub, toolId, 'Note', 'hi');
      const todoId = await insertTodo(sub, toolId, 1, 'Todo A');
      const memoryId = await insertMemory(sub, toolId, '/root/a', 'mem body');

      // Precondition: all rows exist and the route serves the note/todo.
      expect(
        await countRows('notes', {
          sql: 'tool_id = CAST($1 AS uuid)',
          params: [toolId],
        }),
      ).toBe(1);
      expect(
        await countRows('todos', {
          sql: 'tool_id = CAST($1 AS uuid)',
          params: [toolId],
        }),
      ).toBe(1);
      expect(
        await countRows('memories', {
          sql: 'tool_id = CAST($1 AS uuid)',
          params: [toolId],
        }),
      ).toBe(1);
      const precheck = await api.get(`/api/artifact/${noteId}`);
      expect(precheck.status()).toBe(200);

      // Nuke the parent. ON DELETE CASCADE must reap children.
      const del = await pg.query<{ id: string }>(
        'DELETE FROM user_tools WHERE id = CAST($1 AS uuid) RETURNING id::text AS id',
        [toolId],
      );
      expect(del.rows).toHaveLength(1);

      // All child artifact rows gone.
      expect(
        await countRows('notes', {
          sql: 'tool_id = CAST($1 AS uuid)',
          params: [toolId],
        }),
      ).toBe(0);
      expect(
        await countRows('todos', {
          sql: 'tool_id = CAST($1 AS uuid)',
          params: [toolId],
        }),
      ).toBe(0);
      expect(
        await countRows('memories', {
          sql: 'tool_id = CAST($1 AS uuid)',
          params: [toolId],
        }),
      ).toBe(0);
      // Also verify by PK lookup — in case some future patch widens the
      // tool_id index and the tool_id filter stops matching.
      expect(
        await countRows('notes', { sql: 'id = CAST($1 AS uuid)', params: [noteId] }),
      ).toBe(0);
      expect(
        await countRows('todos', { sql: 'id = CAST($1 AS uuid)', params: [todoId] }),
      ).toBe(0);
      expect(
        await countRows('memories', {
          sql: 'id = CAST($1 AS uuid)',
          params: [memoryId],
        }),
      ).toBe(0);

      // The route now 404s — artifact doesn't exist post-cascade.
      const postcheck = await api.get(`/api/artifact/${noteId}`);
      expect(postcheck.status()).toBe(404);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('memory artifact ids are not served by /api/artifact/ (route only handles note/todo)', async ({
    browser,
  }) => {
    // The route in routes.py returns 404 for anything that isn't a note or
    // todo — memories don't have an artifact presenter yet. Pin this today so
    // if/when the route starts serving memory artifacts, this test flips RED
    // and a maintainer has to revisit the frontend sidebar contract.
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const toolId = await insertUserTool(sub, 'memory-fixture');
      const memoryId = await insertMemory(sub, toolId, '/remember/this', 'mem');

      const res = await api.get(`/api/artifact/${memoryId}`);
      expect(res.status()).toBe(404);
    } finally {
      await api.dispose();
      await context.close();
    }
  });
});
