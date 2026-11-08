/**
 * Tier-B · folders for agents and knowledge: CRUD, nesting, filing, aliases
 *
 * Covers B10 on the shared folder model (migration 0063): one `folders`
 * table with a `resource_type` (`agent` | `source`) and personal filing in
 * `folder_items` (one filing per item per user, never touching the item's
 * row). API-only — the DB row shape is the load-bearing contract.
 *
 * Contract notes:
 *   - `/api/folders` (no trailing slash) is the API; `type` is required on
 *     list, create and filing. The old `/api/agents/folders/*` routes stay
 *     as aliases with `type=agent` — they keep the TRAILING SLASH on the
 *     collection URL (the non-slashed one 301-redirects, and Playwright's
 *     APIRequestContext doesn't follow POST redirects).
 *   - Errors are `{success: false, error: <code>, message}`:
 *     `folder_name_taken` (409), `folder_too_deep` / `folder_cycle` (400),
 *     `folder_not_found` (404).
 *   - Deleting a folder moves its child folders and its items to its parent
 *     (top level / unfiled without one) and answers with the counts.
 *   - Folders nest at most 3 levels deep.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

type FolderType = 'agent' | 'source';

interface FolderRow {
  id: string;
  user_id: string;
  name: string;
  parent_id: string | null;
  resource_type: FolderType;
}

interface FolderBody {
  id: string;
  name: string;
  parent_id: string | null;
  type: FolderType;
}

type Api = Awaited<ReturnType<typeof authedRequest>>;

async function fetchFolder(folderId: string): Promise<FolderRow | null> {
  const { rows } = await pg.query<FolderRow>(
    `SELECT id::text AS id, user_id, name, parent_id::text AS parent_id, resource_type
       FROM folders
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

async function createSourceRow(userId: string, name: string): Promise<string> {
  const { rows } = await pg.query<{ id: string }>(
    `INSERT INTO sources (user_id, name, date, retriever)
     VALUES ($1, $2, now(), 'classic')
     RETURNING id::text AS id`,
    [userId, name],
  );
  const id = rows[0]?.id;
  if (!id) throw new Error(`createSourceRow failed for ${name}`);
  return id;
}

/** The folder `userId` filed one item into (their own filing), or null. */
async function filing(userId: string, type: FolderType, resourceId: string): Promise<string | null> {
  const { rows } = await pg.query<{ folder_id: string }>(
    `SELECT folder_id::text AS folder_id
       FROM folder_items
      WHERE user_id = $1 AND resource_type = $2 AND resource_id = CAST($3 AS uuid)`,
    [userId, type, resourceId],
  );
  return rows[0]?.folder_id ?? null;
}

async function createFolder(
  api: Api,
  type: FolderType,
  name: string,
  parentId?: string,
): Promise<FolderBody> {
  const res = await api.post('/api/folders', {
    data: { type, name, ...(parentId ? { parent_id: parentId } : {}) },
  });
  expect(res.status(), `POST /api/folders expected 201, got ${res.status()} ${await res.text()}`).toBe(201);
  return (await res.json()) as FolderBody;
}

test.describe('tier-b · folders', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('create + list: a folder of each type, listed only under its type', async ({ browser }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const agentFolder = await createFolder(api, 'agent', 'My agents');
      const sourceFolder = await createFolder(api, 'source', 'Carriers');
      expect(agentFolder.type).toBe('agent');
      expect(sourceFolder.parent_id).toBeNull();

      const row = await fetchFolder(sourceFolder.id);
      expect(row).toMatchObject({ user_id: sub, name: 'Carriers', parent_id: null, resource_type: 'source' });

      const listRes = await api.get('/api/folders?type=source');
      expect(listRes.status()).toBe(200);
      const listBody = (await listRes.json()) as {
        folders: Array<{ id: string; item_count: number; folder_count: number; used_by?: unknown }>;
      };
      expect(listBody.folders.map((f) => f.id)).toEqual([sourceFolder.id]);
      expect(listBody.folders[0]).toMatchObject({ item_count: 0, folder_count: 0 });
      expect(listBody.folders[0].used_by).toEqual({ agents: [], others: 0 });

      // The alias lists agent folders only.
      const aliasRes = await api.get('/api/agents/folders/');
      expect(aliasRes.status()).toBe(200);
      const aliasBody = (await aliasRes.json()) as { folders: Array<{ id: string }> };
      expect(aliasBody.folders.map((f) => f.id)).toEqual([agentFolder.id]);

      // A sibling name is taken ignoring case.
      const dupe = await api.post('/api/folders', { data: { type: 'source', name: 'carriers' } });
      expect(dupe.status()).toBe(409);
      expect(((await dupe.json()) as { error: string }).error).toBe('folder_name_taken');
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('rename: PUT /api/folders/:id updates the name column', async ({ browser }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const { id } = await createFolder(api, 'source', 'before rename');
      const putRes = await api.put(`/api/folders/${id}`, { data: { name: 'after rename' } });
      expect(putRes.status(), `PUT expected 200, got ${putRes.status()} ${await putRes.text()}`).toBe(200);
      expect((await fetchFolder(id))!.name).toBe('after rename');
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('nesting: three levels at most, children listed flat with parent_id', async ({ browser }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const one = await createFolder(api, 'source', 'one');
      const two = await createFolder(api, 'source', 'two', one.id);
      const three = await createFolder(api, 'source', 'three', two.id);
      expect(three.parent_id).toBe(two.id);

      const tooDeep = await api.post('/api/folders', {
        data: { type: 'source', name: 'four', parent_id: three.id },
      });
      expect(tooDeep.status()).toBe(400);
      expect(((await tooDeep.json()) as { error: string }).error).toBe('folder_too_deep');

      const listRes = await api.get('/api/folders?type=source');
      const listBody = (await listRes.json()) as {
        folders: Array<{ id: string; parent_id: string | null; folder_count: number }>;
      };
      expect(listBody.folders.map((f) => f.id).sort()).toEqual([one.id, two.id, three.id].sort());
      expect(listBody.folders.find((f) => f.id === one.id)!.folder_count).toBe(1);
      expect(listBody.folders.find((f) => f.id === three.id)!.parent_id).toBe(two.id);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('cycle prevention: a folder cannot move into itself or one of its folders', async ({ browser }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const parent = await createFolder(api, 'agent', 'parent');
      const child = await createFolder(api, 'agent', 'child', parent.id);

      for (const target of [parent.id, child.id]) {
        const putRes = await api.put(`/api/folders/${parent.id}`, { data: { parent_id: target } });
        expect(putRes.status()).toBe(400);
        const body = (await putRes.json()) as { success: boolean; error: string };
        expect(body).toMatchObject({ success: false, error: 'folder_cycle' });
      }
      expect((await fetchFolder(parent.id))!.parent_id).toBeNull();
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('filing: POST /api/folders/items files and unfiles items for the caller only', async ({ browser }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const folder = await createFolder(api, 'source', 'Carriers');
      const mine = await createSourceRow(sub, 'mine');
      const theirs = await createSourceRow('someone-else', 'theirs');

      const res = await api.post('/api/folders/items', {
        data: { type: 'source', folder_id: folder.id, ids: [mine, theirs] },
      });
      expect(res.status(), `filing expected 200, got ${res.status()} ${await res.text()}`).toBe(200);
      // A source the caller can't see is skipped, not filed.
      expect(await res.json()).toMatchObject({ moved: [mine], skipped: [theirs] });
      expect(await filing(sub, 'source', mine)).toBe(folder.id);
      expect(await filing(sub, 'source', theirs)).toBeNull();

      // The listing counts it.
      const listBody = (await (await api.get('/api/folders?type=source')).json()) as {
        folders: Array<{ id: string; item_count: number }>;
      };
      expect(listBody.folders[0].item_count).toBe(1);

      const unfile = await api.post('/api/folders/items', {
        data: { type: 'source', folder_id: null, ids: [mine] },
      });
      expect(unfile.status()).toBe(200);
      expect(await filing(sub, 'source', mine)).toBeNull();

      // An agent folder doesn't take sources.
      const agentFolder = await createFolder(api, 'agent', 'Agents');
      const wrongType = await api.post('/api/folders/items', {
        data: { type: 'source', folder_id: agentFolder.id, ids: [mine] },
      });
      expect(wrongType.status()).toBe(404);
      expect(((await wrongType.json()) as { error: string }).error).toBe('folder_not_found');
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('delete: contents move to the parent and nothing else is deleted', async ({ browser }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const parent = await createFolder(api, 'agent', 'parent');
      const doomed = await createFolder(api, 'agent', 'doomed', parent.id);
      const inner = await createFolder(api, 'agent', 'inner', doomed.id);
      const agentId = await createAgentRow(sub, 'enclosed');
      const fileRes = await api.post('/api/folders/items', {
        data: { type: 'agent', folder_id: doomed.id, ids: [agentId] },
      });
      expect(fileRes.status()).toBe(200);

      const delRes = await api.delete(`/api/folders/${doomed.id}`);
      expect(delRes.status()).toBe(200);
      expect(await delRes.json()).toMatchObject({ success: true, moved_items: 1, moved_folders: 1 });

      expect(await fetchFolder(doomed.id)).toBeNull();
      expect((await fetchFolder(inner.id))!.parent_id).toBe(parent.id);
      expect(await filing(sub, 'agent', agentId)).toBe(parent.id);

      // A top-level folder's items end up unfiled.
      const delParent = await api.delete(`/api/folders/${parent.id}`);
      expect(delParent.status()).toBe(200);
      expect(await filing(sub, 'agent', agentId)).toBeNull();
      expect((await fetchFolder(inner.id))!.parent_id).toBeNull();
      const { rows } = await pg.query(`SELECT 1 FROM agents WHERE id = CAST($1 AS uuid)`, [agentId]);
      expect(rows).toHaveLength(1);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('aliases: move_agent and bulk_move write the caller\'s filing', async ({ browser }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const folderRes = await api.post('/api/agents/folders/', { data: { name: 'move target' } });
      expect(folderRes.status()).toBe(201);
      const { id: folderId } = (await folderRes.json()) as { id: string };
      expect((await fetchFolder(folderId))!.resource_type).toBe('agent');

      const movee = await createAgentRow(sub, 'movee');
      const moveRes = await api.post('/api/agents/folders/move_agent', {
        data: { agent_id: movee, folder_id: folderId },
      });
      expect(moveRes.status()).toBe(200);
      expect(await filing(sub, 'agent', movee)).toBe(folderId);

      const clearRes = await api.post('/api/agents/folders/move_agent', {
        data: { agent_id: movee, folder_id: null },
      });
      expect(clearRes.status()).toBe(200);
      expect(await filing(sub, 'agent', movee)).toBeNull();

      const agentIds = await Promise.all([
        createAgentRow(sub, 'bulk-1'),
        createAgentRow(sub, 'bulk-2'),
        createAgentRow(sub, 'bulk-3'),
      ]);
      const bulkRes = await api.post('/api/agents/folders/bulk_move', {
        data: { agent_ids: agentIds, folder_id: folderId },
      });
      expect(bulkRes.status(), `bulk_move expected 200, got ${bulkRes.status()} ${await bulkRes.text()}`).toBe(
        200,
      );
      for (const id of agentIds) {
        expect(await filing(sub, 'agent', id)).toBe(folderId);
      }

      // get_agent reports the caller's filing.
      const agentRes = await api.get(`/api/get_agent?id=${movee}`);
      expect(((await agentRes.json()) as { folder_id: string | null }).folder_id).toBeNull();
      const bulkAgent = await api.get(`/api/get_agent?id=${agentIds[0]}`);
      expect(((await bulkAgent.json()) as { folder_id: string | null }).folder_id).toBe(folderId);
    } finally {
      await api.dispose();
      await context.close();
    }
  });
});
