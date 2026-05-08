/**
 * Phase 3 Tier-B · source-files (B5) — POST /api/manage_source_files.
 *
 * Exercises the three `operation` branches in
 * `application/api/user/sources/upload.py::ManageSourceFiles`:
 *
 *   - operation=add              → storage.save_file + file_name_map merge
 *                                  + reingest task
 *   - operation=remove           → storage.delete_file + file_name_map
 *                                  pop + reingest task
 *   - operation=remove_directory → storage.remove_directory + prefix-pop
 *                                  of file_name_map + reingest task
 *
 * Plus the two path-traversal guards (the route has explicit defences at
 * lines 363-368, 462-472, 522-533 of the upstream route file).
 *
 * All variants trigger `reingest_source_task` — which in turn tries to
 * re-embed via the stubbed mock LLM. We do NOT wait for that reingest to
 * finish: the response `reingest_task_id` is the acknowledgement that
 * matters for this contract, and asserting the `file_name_map` / DB write
 * separately is faster and less flaky than coupling to Celery again.
 */

import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { APIRequestContext } from '@playwright/test';

import { newUserContext } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';
import { multipartContext, seedSource } from '../../helpers/uploads.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const NOTES_TXT = resolve(HERE, '..', '..', 'fixtures', 'docs', 'notes.txt');

async function readFileNameMap(
  sourceId: string,
): Promise<Record<string, string> | null> {
  const { rows } = await pg.query<{ file_name_map: Record<string, string> | null }>(
    'SELECT file_name_map FROM sources WHERE id = CAST($1 AS uuid)',
    [sourceId],
  );
  return rows[0]?.file_name_map ?? null;
}

async function addFile(
  multi: APIRequestContext,
  sourceId: string,
  fileBuf: Buffer,
  opts: { parentDir?: string; filename?: string } = {},
): Promise<{ reingestTaskId: string }> {
  const fields: Record<string, unknown> = {
    source_id: sourceId,
    operation: 'add',
    file: {
      name: opts.filename ?? 'notes.txt',
      mimeType: 'text/plain',
      buffer: fileBuf,
    },
  };
  if (opts.parentDir) fields.parent_dir = opts.parentDir;
  const res = await multi.post('/api/manage_source_files', {
    multipart: fields as Record<
      string,
      string | number | boolean | { name: string; mimeType: string; buffer: Buffer }
    >,
  });
  if (res.status() !== 200) {
    throw new Error(
      `manage_source_files add failed ${res.status()}: ${await res.text()}`,
    );
  }
  const body = (await res.json()) as {
    success: boolean;
    reingest_task_id: string;
  };
  return { reingestTaskId: body.reingest_task_id };
}

test.describe('tier-b · manage_source_files', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('operation=add inserts the file into file_name_map and returns a reingest task_id', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const multi = await multipartContext(token);
    try {
      const sourceId = await seedSource(sub, {
        name: 'sf-add',
        type: 'local',
        filePath: '.e2e-tmp/inputs/sf-add',
        fileNameMap: {},
      });

      const buffer = await readFile(NOTES_TXT);
      const { reingestTaskId } = await addFile(multi, sourceId, buffer, {
        filename: 'notes.txt',
      });
      expect(reingestTaskId).toMatch(/^[0-9a-f-]{36}$/i);

      const map = await readFileNameMap(sourceId);
      // Safe filename == original for "notes.txt" (no special chars).
      expect(map).toMatchObject({ 'notes.txt': 'notes.txt' });
    } finally {
      await multi.dispose();
      await context.close();
    }
  });

  test('operation=remove pops file_name_map entry and returns a reingest task_id', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const multi = await multipartContext(token);
    try {
      const sourceId = await seedSource(sub, {
        name: 'sf-remove',
        type: 'local',
        filePath: '.e2e-tmp/inputs/sf-remove',
        fileNameMap: {},
      });

      // First add — materialises the storage file + file_name_map key.
      const buffer = await readFile(NOTES_TXT);
      await addFile(multi, sourceId, buffer, { filename: 'notes.txt' });
      expect(await readFileNameMap(sourceId)).toMatchObject({
        'notes.txt': 'notes.txt',
      });

      // Then remove.
      const res = await multi.post('/api/manage_source_files', {
        multipart: {
          source_id: sourceId,
          operation: 'remove',
          file_paths: JSON.stringify(['notes.txt']),
        },
      });
      expect(res.status()).toBe(200);
      const body = (await res.json()) as {
        success: boolean;
        removed_files: string[];
        reingest_task_id: string;
      };
      expect(body.success).toBe(true);
      expect(body.removed_files).toEqual(['notes.txt']);
      expect(body.reingest_task_id).toMatch(/^[0-9a-f-]{36}$/i);

      const map = await readFileNameMap(sourceId);
      expect(map).toEqual({});
    } finally {
      await multi.dispose();
      await context.close();
    }
  });

  test('operation=remove with ".." in the path → 400 (path-traversal guard)', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const multi = await multipartContext(token);
    try {
      const sourceId = await seedSource(sub, {
        name: 'sf-traversal-rel',
        type: 'local',
        filePath: '.e2e-tmp/inputs/sf-traversal-rel',
      });

      const res = await multi.post('/api/manage_source_files', {
        multipart: {
          source_id: sourceId,
          operation: 'remove',
          file_paths: JSON.stringify(['../etc/passwd']),
        },
      });
      expect(res.status()).toBe(400);
      const body = (await res.json()) as { message: string };
      expect(body.message.toLowerCase()).toContain('invalid file path');
    } finally {
      await multi.dispose();
      await context.close();
    }
  });

  test('operation=add with absolute `parent_dir` → 400 (parent_dir guard)', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const multi = await multipartContext(token);
    try {
      const sourceId = await seedSource(sub, {
        name: 'sf-traversal-abs',
        type: 'local',
        filePath: '.e2e-tmp/inputs/sf-traversal-abs',
      });

      const buffer = await readFile(NOTES_TXT);
      const res = await multi.post('/api/manage_source_files', {
        multipart: {
          source_id: sourceId,
          operation: 'add',
          parent_dir: '/etc',
          file: {
            name: 'notes.txt',
            mimeType: 'text/plain',
            buffer,
          },
        },
      });
      expect(res.status()).toBe(400);
      const body = (await res.json()) as { message: string };
      expect(body.message.toLowerCase()).toContain(
        'invalid parent directory',
      );
    } finally {
      await multi.dispose();
      await context.close();
    }
  });

  test('operation=remove_directory clears nested entries from file_name_map', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const multi = await multipartContext(token);
    try {
      // Use a per-test file_path so concurrent tests can't stomp each
      // other (they shouldn't — workers=1 — but belt-and-braces).
      const subDir = `.e2e-tmp/inputs/sf-remdir-${Date.now()}`;
      const sourceId = await seedSource(sub, {
        name: 'sf-remdir',
        type: 'local',
        filePath: subDir,
        fileNameMap: {},
      });

      // Seed a nested file via the add operation so both the on-disk
      // directory and the DB `file_name_map` exist before we remove.
      const buffer = await readFile(NOTES_TXT);
      await addFile(multi, sourceId, buffer, {
        parentDir: 'nested',
        filename: 'inner.txt',
      });
      const afterAdd = await readFileNameMap(sourceId);
      expect(afterAdd).toMatchObject({ 'nested/inner.txt': 'inner.txt' });

      const res = await multi.post('/api/manage_source_files', {
        multipart: {
          source_id: sourceId,
          operation: 'remove_directory',
          directory_path: 'nested',
        },
      });
      expect(
        res.status(),
        `remove_directory failed: ${await res.text()}`,
      ).toBe(200);
      const body = (await res.json()) as {
        success: boolean;
        removed_directory: string;
        reingest_task_id: string;
      };
      expect(body.success).toBe(true);
      expect(body.removed_directory).toBe('nested');
      expect(body.reingest_task_id).toMatch(/^[0-9a-f-]{36}$/i);

      const map = await readFileNameMap(sourceId);
      expect(map).toEqual({});
    } finally {
      await multi.dispose();
      await context.close();
    }
  });
});
