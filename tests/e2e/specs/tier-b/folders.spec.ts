/**
 * Phase 3 Tier-B · agent folders CRUD + nesting + move/bulk-move
 *
 * Covers B10: create/list/rename/delete folders, nest via parent_id, cycle
 * prevention, and single/bulk agent-move into folders. API-only — folder
 * state has no dedicated landing UI, and the DB row shape (agent_folders,
 * agents.folder_id) is the load-bearing contract.
 *
 * Contract notes discovered while writing this spec:
 *   - `POST /api/agents/folders/` requires the TRAILING SLASH — the
 *     non-slashed URL 301-redirects and Playwright's APIRequestContext
 *     does not follow POST→GET redirects for mutating verbs. Same for GET.
 *   - DELETE on a folder clears `folder_id` for its agents (via
 *     AgentsRepository.clear_folder_for_all) — this matches the spec brief's
 *     "FK cascade behavior" shorthand (it's an app-level clear, not an
 *     ON DELETE SET NULL; the on-agents FK is SET NULL but the explicit
 *     clear runs first inside the same db_session).
 *   - Self-parent cycle is rejected with 400; deeper cycles are not
 *     guarded against by the current API (only the immediate self-parent
 *     guard exists in folders.py:207-232). We test the self-parent case
 *     only — that's the documented guard.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

interface FolderRow {
  id: string;
  user_id: string;
  name: string;
  parent_id: string | null;
}

async function fetchFolder(folderId: string): Promise<FolderRow | null> {
  const { rows } = await pg.query<FolderRow>(
    `SELECT id::text AS id, user_id, name,
            parent_id::text AS parent_id
       FROM agent_folders
      WHERE id = CAST($1 AS uuid)`,
    [folderId],
  );
  return rows[0] ?? null;
}

async function createAgentRow(userId: string, name: string): Promise<string> {
  const { rows } = await pg.query<{ id: string }>(
    `INSERT INTO agents (user_id, name, status, retriever)
     VALUES ($1, $2, 'draft', 'classic')
     RETURNING id::text AS id`,
    [userId, name],
  );
  const id = rows[0]?.id;
  if (!id) throw new Error(`createAgentRow failed for ${name}`);
  return id;
}

async function getAgentFolderId(agentId: string): Promise<string | null> {
  const { rows } = await pg.query<{ folder_id: string | null }>(
    `SELECT folder_id::text AS folder_id
       FROM agents WHERE id = CAST($1 AS uuid)`,
    [agentId],
  );
  return rows[0]?.folder_id ?? null;
}

test.describe('tier-b · agent folders', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('create + list: POST writes an agent_folders row and GET returns it', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const res = await api.post('/api/agents/folders/', {
        data: { name: 'My Folder' },
      });
      expect(
        res.status(),
        `POST /api/agents/folders/ expected 201, got ${res.status()} ${await res.text()}`,
      ).toBe(201);
      const body = (await res.json()) as { id: string; name: string; parent_id: string | null };
      expect(body.name).toBe('My Folder');
      expect(body.parent_id).toBeNull();

      // DB row exists and is owned by this user.
      const row = await fetchFolder(body.id);
      expect(row).not.toBeNull();
      expect(row!.user_id).toBe(sub);
      expect(row!.name).toBe('My Folder');
      expect(row!.parent_id).toBeNull();

      // GET lists it back. Endpoint is `/api/agents/folders/` with the
      // trailing slash; the wrapper returns `{folders: [...]}`.
      const listRes = await api.get('/api/agents/folders/');
      expect(listRes.status()).toBe(200);
      const listBody = (await listRes.json()) as { folders: Array<{ id: string; name: string }> };
      expect(Array.isArray(listBody.folders)).toBe(true);
      expect(listBody.folders.map((f) => f.id)).toContain(body.id);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('rename: PUT /api/agents/folders/:id updates the name column', async ({
    browser,
  }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const createRes = await api.post('/api/agents/folders/', {
        data: { name: 'before rename' },
      });
      expect(createRes.status()).toBe(201);
      const { id } = (await createRes.json()) as { id: string };

      const putRes = await api.put(`/api/agents/folders/${id}`, {
        data: { name: 'after rename' },
      });
      expect(
        putRes.status(),
        `PUT expected 200, got ${putRes.status()} ${await putRes.text()}`,
      ).toBe(200);

      const row = await fetchFolder(id);
      expect(row!.name).toBe('after rename');
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('delete: DELETE removes the row and clears folder_id on enclosed agents', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const createRes = await api.post('/api/agents/folders/', {
        data: { name: 'doomed' },
      });
      const { id: folderId } = (await createRes.json()) as { id: string };

      // Put an agent inside.
      const agentId = await createAgentRow(sub, 'enclosed');
      const moveRes = await api.post('/api/agents/folders/move_agent', {
        data: { agent_id: agentId, folder_id: folderId },
      });
      expect(moveRes.status()).toBe(200);
      expect(await getAgentFolderId(agentId)).toBe(folderId);

      // Now delete the folder.
      const delRes = await api.delete(`/api/agents/folders/${folderId}`);
      expect(delRes.status()).toBe(200);

      // Row is gone.
      expect(await fetchFolder(folderId)).toBeNull();

      // Agent's folder_id has been cleared (app-level clear_folder_for_all
      // runs before the DELETE — the FK's ON DELETE SET NULL is a
      // belt-and-braces backstop, but we only care that the column is
      // NULL post-delete).
      expect(await getAgentFolderId(agentId)).toBeNull();
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('nested folder: child references parent via parent_id', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      // Parent.
      const parentRes = await api.post('/api/agents/folders/', {
        data: { name: 'parent' },
      });
      expect(parentRes.status()).toBe(201);
      const { id: parentId } = (await parentRes.json()) as { id: string };

      // Child.
      const childRes = await api.post('/api/agents/folders/', {
        data: { name: 'child', parent_id: parentId },
      });
      expect(
        childRes.status(),
        `child create expected 201, got ${childRes.status()} ${await childRes.text()}`,
      ).toBe(201);
      const { id: childId, parent_id: childParentId } = (await childRes.json()) as {
        id: string;
        parent_id: string;
      };
      expect(childParentId).toBe(parentId);

      // DB: the child row really has parent_id = parentId, and both rows
      // belong to the user.
      const childRow = await fetchFolder(childId);
      expect(childRow!.parent_id).toBe(parentId);
      expect(childRow!.user_id).toBe(sub);

      // List at the root level returns both (the list endpoint is flat —
      // hierarchy is client-side via parent_id).
      const listRes = await api.get('/api/agents/folders/');
      expect(listRes.status()).toBe(200);
      const listBody = (await listRes.json()) as {
        folders: Array<{ id: string; parent_id: string | null }>;
      };
      const ids = listBody.folders.map((f) => f.id);
      expect(ids).toContain(parentId);
      expect(ids).toContain(childId);
      const childInList = listBody.folders.find((f) => f.id === childId);
      expect(childInList!.parent_id).toBe(parentId);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test("cycle prevention: setting a folder's own id as parent returns 400", async ({
    browser,
  }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const createRes = await api.post('/api/agents/folders/', {
        data: { name: 'self-cycle' },
      });
      const { id } = (await createRes.json()) as { id: string };

      const putRes = await api.put(`/api/agents/folders/${id}`, {
        data: { parent_id: id },
      });
      expect(putRes.status()).toBe(400);
      const body = (await putRes.json()) as { success: boolean; message?: string };
      expect(body.success).toBe(false);

      // DB invariant: parent_id remains NULL (the PUT aborted before any write).
      const row = await fetchFolder(id);
      expect(row!.parent_id).toBeNull();
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('move_agent: POST /api/agents/folders/move_agent updates agents.folder_id', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const folderRes = await api.post('/api/agents/folders/', {
        data: { name: 'move target' },
      });
      const { id: folderId } = (await folderRes.json()) as { id: string };

      const agentId = await createAgentRow(sub, 'movee');
      expect(await getAgentFolderId(agentId)).toBeNull();

      const moveRes = await api.post('/api/agents/folders/move_agent', {
        data: { agent_id: agentId, folder_id: folderId },
      });
      expect(moveRes.status()).toBe(200);
      expect(await getAgentFolderId(agentId)).toBe(folderId);

      // Move back out: folder_id = null clears.
      const clearRes = await api.post('/api/agents/folders/move_agent', {
        data: { agent_id: agentId, folder_id: null },
      });
      expect(clearRes.status()).toBe(200);
      expect(await getAgentFolderId(agentId)).toBeNull();
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('bulk_move: POST /api/agents/folders/bulk_move moves N agents into a folder', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const folderRes = await api.post('/api/agents/folders/', {
        data: { name: 'bulk target' },
      });
      const { id: folderId } = (await folderRes.json()) as { id: string };

      const agentIds = await Promise.all([
        createAgentRow(sub, 'bulk-1'),
        createAgentRow(sub, 'bulk-2'),
        createAgentRow(sub, 'bulk-3'),
      ]);

      const res = await api.post('/api/agents/folders/bulk_move', {
        data: { agent_ids: agentIds, folder_id: folderId },
      });
      expect(
        res.status(),
        `bulk_move expected 200, got ${res.status()} ${await res.text()}`,
      ).toBe(200);

      for (const id of agentIds) {
        expect(await getAgentFolderId(id)).toBe(folderId);
      }
    } finally {
      await api.dispose();
      await context.close();
    }
  });
});
