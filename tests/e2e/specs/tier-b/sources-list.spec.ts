/**
 * Phase 3 Tier-B · sources-list (B2) — list / paginate / search / delete /
 * directory-structure.
 *
 * Exercises the read-side endpoints the UI calls from
 * `frontend/src/settings/Sources.tsx`:
 *
 *   - GET /api/sources                 → legacy combined JSON (always
 *                                         includes a "Default" entry first)
 *   - GET /api/sources/paginated       → page + rows + search + sort
 *   - GET /api/delete_old              → vector + file + row tear-down
 *   - GET /api/directory_structure     → returns {directory_structure,
 *                                         base_path, provider}
 *
 * Sources are seeded directly via SQL (see `helpers/uploads.ts::seedSource`) —
 * cheaper than /api/upload and orthogonal to the ingest pipeline this
 * cluster is NOT testing. The schema used by the INSERT is locked by
 * alembic 0001_initial.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';
import { seedSource } from '../../helpers/uploads.js';

type SourcesListItem = {
  name: string;
  id?: string;
  date: string;
  location: string;
  type?: string;
  retriever?: string;
};

type PaginatedResponse = {
  total: number;
  totalPages: number;
  currentPage: number;
  paginated: Array<{
    id: string;
    name: string;
    type: string;
    retriever: string;
    isNested: boolean;
  }>;
};

test.describe('tier-b · sources list / paginated / delete', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('GET /api/sources returns the Default entry plus each seeded source owned by the caller', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const id = await seedSource(sub, {
        name: 'my-alpha-source',
        filePath: '.e2e-tmp/inputs/my-alpha-source',
      });

      const res = await api.get('/api/sources');
      expect(res.status()).toBe(200);
      const body = (await res.json()) as SourcesListItem[];
      // "Default" is always prepended — the widget pulls from /api/sources
      // when chunks=0 is selected, and that remote default row is required.
      expect(body[0].name).toBe('Default');
      expect(body[0].location).toBe('remote');

      const mine = body.find((item) => item.id === id);
      expect(mine, `seeded source ${id} missing from /api/sources`).toBeDefined();
      expect(mine!.name).toBe('my-alpha-source');
      expect(mine!.location).toBe('local');
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('GET /api/sources/paginated respects page, rows, and search', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      // Three sources with distinguishable names; one contains "needle".
      const a = await seedSource(sub, { name: 'alpha-needle-haystack' });
      const b = await seedSource(sub, { name: 'beta-plain' });
      const c = await seedSource(sub, { name: 'gamma-plain' });

      // Full list, page 1, rows 10 — all three returned.
      const full = await api.get('/api/sources/paginated?page=1&rows=10');
      expect(full.status()).toBe(200);
      const fullBody = (await full.json()) as PaginatedResponse;
      expect(fullBody.total).toBe(3);
      expect(fullBody.paginated.map((d) => d.id).sort()).toEqual(
        [a, b, c].sort(),
      );

      // Page 1, rows=1 → only one result, totalPages=3.
      const paged = await api.get('/api/sources/paginated?page=1&rows=1');
      expect(paged.status()).toBe(200);
      const pagedBody = (await paged.json()) as PaginatedResponse;
      expect(pagedBody.total).toBe(3);
      expect(pagedBody.totalPages).toBe(3);
      expect(pagedBody.paginated).toHaveLength(1);

      // Search for the substring "needle" — only `a` matches, and the
      // match is case-insensitive per sources/routes.py:110-115.
      const searched = await api.get(
        '/api/sources/paginated?page=1&rows=10&search=NEEDLE',
      );
      expect(searched.status()).toBe(200);
      const searchedBody = (await searched.json()) as PaginatedResponse;
      expect(searchedBody.total).toBe(1);
      expect(searchedBody.paginated[0].id).toBe(a);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('GET /api/delete_old removes the sources row (filesystem cleanup is best-effort)', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const id = await seedSource(sub, {
        name: 'doomed-source',
        filePath: '.e2e-tmp/inputs/doomed-source',
      });

      const before = await pg.query<{ n: string }>(
        'SELECT count(*)::text AS n FROM sources WHERE id = CAST($1 AS uuid)',
        [id],
      );
      expect(Number(before.rows[0]?.n ?? 0)).toBe(1);

      const res = await api.get(`/api/delete_old?source_id=${id}`);
      expect(res.status()).toBe(200);
      const body = (await res.json()) as { success: boolean };
      expect(body.success).toBe(true);

      // DB-level invariant: row is gone. We do NOT assert filesystem state
      // — the LocalStorage base_dir on this dev machine points at the
      // repo root (see helpers/uploads.ts caveat), and the storage tear-down
      // silently swallows FileNotFoundError for missing faiss/pkl, so the
      // endpoint can return success even when the on-disk artifacts were
      // never materialised (as is the case for a seeded source).
      const after = await pg.query<{ n: string }>(
        'SELECT count(*)::text AS n FROM sources WHERE id = CAST($1 AS uuid)',
        [id],
      );
      expect(Number(after.rows[0]?.n ?? 0)).toBe(0);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('GET /api/delete_old returns 404 when the source_id is absent from the caller tenant', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      // Seed a source for ANOTHER user; user `sub` must not see it.
      const otherSub = `other-${Date.now()}`;
      const foreignId = await seedSource(otherSub, { name: 'foreign' });

      const res = await api.get(`/api/delete_old?source_id=${foreignId}`);
      expect(res.status()).toBe(404);

      // Foreign row untouched.
      const { rows } = await pg.query<{ n: string }>(
        'SELECT count(*)::text AS n FROM sources WHERE id = CAST($1 AS uuid)',
        [foreignId],
      );
      expect(Number(rows[0]?.n ?? 0)).toBe(1);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('GET /api/directory_structure returns {directory_structure, base_path, provider} for an owned source', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const id = await seedSource(sub, {
        name: 'dir-struct-source',
        filePath: '.e2e-tmp/inputs/dir-struct-source',
        directoryStructure: {
          'notes.txt': { type: 'text/plain', size_bytes: 120 },
          subdir: { 'nested.md': { type: 'text/markdown' } },
        },
      });

      const res = await api.get(`/api/directory_structure?id=${id}`);
      expect(res.status()).toBe(200);
      const body = (await res.json()) as {
        success: boolean;
        directory_structure: Record<string, unknown>;
        base_path: string;
        provider: string | null;
      };
      expect(body.success).toBe(true);
      // `toHaveProperty` treats dotted strings as paths — pass literal keys
      // as arrays to avoid "notes.txt" being interpreted as .notes.txt.
      expect(body.directory_structure).toHaveProperty(['notes.txt']);
      expect(body.directory_structure).toHaveProperty(['subdir']);
      expect(body.base_path).toBe('.e2e-tmp/inputs/dir-struct-source');
      // No remote_data was seeded — provider should be null.
      expect(body.provider).toBeNull();
    } finally {
      await api.dispose();
      await context.close();
    }
  });
});
