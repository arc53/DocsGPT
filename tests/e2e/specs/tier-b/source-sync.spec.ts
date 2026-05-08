/**
 * Phase 3 Tier-B · source-sync (B4) — sync frequency + manual sync.
 *
 * Two endpoints:
 *
 *   - POST /api/manage_sync      writes `sources.sync_frequency` (never,
 *                                 daily, weekly, monthly).
 *   - POST /api/sync_source      kicks off a Celery `sync_source` task if
 *                                 the source is syncable (has remote_data
 *                                 and is NOT a connector).
 *
 * Notable contract:
 *   - File-based sources (no `remote_data`) cannot be manually synced —
 *     they return 400 "Source is not syncable". This contradicts the
 *     subagent brief, which assumed file sources accepted sync_source.
 *     Documenting the correction here; the test asserts the observed 400.
 *   - Connector sources (`type` starts with "connector") are rejected
 *     with a message pointing to /api/connectors/sync. This is a
 *     cleaner affordance than silently queuing a bad Celery job.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';
import { seedSource } from '../../helpers/uploads.js';

async function readSyncFrequency(sourceId: string): Promise<string | null> {
  const { rows } = await pg.query<{ sync_frequency: string | null }>(
    'SELECT sync_frequency FROM sources WHERE id = CAST($1 AS uuid)',
    [sourceId],
  );
  return rows[0]?.sync_frequency ?? null;
}

test.describe('tier-b · source-sync', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('POST /api/manage_sync writes each valid frequency (never/daily/weekly/monthly) back to the row', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const sourceId = await seedSource(sub, { name: 'sync-target' });

      for (const frequency of ['daily', 'weekly', 'monthly', 'never']) {
        const res = await api.post('/api/manage_sync', {
          data: { source_id: sourceId, sync_frequency: frequency },
        });
        expect(
          res.status(),
          `manage_sync(${frequency}) failed ${res.status()}: ${await res.text()}`,
        ).toBe(200);
        const body = (await res.json()) as { success: boolean };
        expect(body.success).toBe(true);

        const stored = await readSyncFrequency(sourceId);
        expect(stored).toBe(frequency);
      }
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('POST /api/manage_sync with an invalid frequency → 400 and row unchanged', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const sourceId = await seedSource(sub, {
        name: 'sync-target-invalid',
        syncFrequency: 'weekly',
      });

      const res = await api.post('/api/manage_sync', {
        data: { source_id: sourceId, sync_frequency: 'every-solstice' },
      });
      expect(res.status()).toBe(400);

      // `weekly` must be untouched — an invalid frequency should never
      // propagate to the sources row.
      expect(await readSyncFrequency(sourceId)).toBe('weekly');
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('POST /api/sync_source on a remote-backed source returns a task_id', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      // `sync_source` requires `remote_data` to be present AND the source
      // type to NOT start with "connector". Anything else returns 400
      // (see sources/routes.py:317-332).
      const sourceId = await seedSource(sub, {
        name: 'remote-url-src',
        type: 'url',
        remoteData: { url: 'http://127.0.0.1:7099/api/config' },
        syncFrequency: 'daily',
      });

      const res = await api.post('/api/sync_source', {
        data: { source_id: sourceId },
      });
      expect(
        res.status(),
        `sync_source failed ${res.status()}: ${await res.text()}`,
      ).toBe(200);
      const body = (await res.json()) as { success: boolean; task_id: string };
      expect(body.success).toBe(true);
      expect(body.task_id).toMatch(/^[0-9a-f-]{36}$/i);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('POST /api/sync_source on a connector source → 4xx and points the caller at /api/connectors/sync', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const sourceId = await seedSource(sub, {
        name: 'connector-src',
        type: 'connector:google_drive',
        remoteData: { provider: 'google_drive' },
      });

      const res = await api.post('/api/sync_source', {
        data: { source_id: sourceId },
      });
      expect(res.status()).toBe(400);
      const body = (await res.json()) as { success: boolean; message: string };
      expect(body.success).toBe(false);
      expect(body.message.toLowerCase()).toContain('/api/connectors/sync');
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('POST /api/sync_source on a file-only source → 400 "not syncable" (no remote_data)', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      // File-based sources (type=local, no remote_data) are rejected as
      // unsyncable — this documents the backend's intended affordance,
      // not a regression. The subagent brief guessed wrong here; this
      // test pins the actual contract.
      const sourceId = await seedSource(sub, {
        name: 'file-only-src',
        type: 'local',
        filePath: '.e2e-tmp/inputs/file-only-src',
      });

      const res = await api.post('/api/sync_source', {
        data: { source_id: sourceId },
      });
      expect(res.status()).toBe(400);
      const body = (await res.json()) as { success: boolean; message: string };
      expect(body.success).toBe(false);
      expect(body.message.toLowerCase()).toContain('not syncable');
    } finally {
      await api.dispose();
      await context.close();
    }
  });
});
