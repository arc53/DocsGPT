/** Tier-B · public agent-image capability endpoint. */

import { createHmac } from 'node:crypto';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..', '..', '..');
const IMAGE_USER = 'e2e-images';
const IMAGES_DIR = resolve(
  REPO_ROOT,
  '.e2e-tmp',
  'inputs',
  IMAGE_USER,
  'attachments',
);
const STORAGE_PREFIX = `.e2e-tmp/inputs/${IMAGE_USER}/attachments`;
const API_URL = process.env.API_URL ?? 'http://127.0.0.1:7099';
const IMAGE_SECRET =
  process.env.JWT_SECRET_KEY ?? 'e2e-fixed-secret-never-use-in-prod';

const TINY_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  'base64',
);

function imageCapability(
  agentId: string,
  imagePath: string,
  userId = IMAGE_USER,
): string {
  const payload = `docsgpt-agent-image-v1\0${agentId}\0${userId}\0${imagePath}`;
  return createHmac('sha256', IMAGE_SECRET).update(payload).digest('hex');
}

async function seedAgentImage(
  filename: string,
  data: Buffer = TINY_PNG,
): Promise<{ agentId: string; imagePath: string; url: string }> {
  await mkdir(IMAGES_DIR, { recursive: true });
  await writeFile(resolve(IMAGES_DIR, filename), data);
  const imagePath = `${STORAGE_PREFIX}/${filename}`;
  const { rows } = await pg.query<{ id: string }>(
    `INSERT INTO agents (user_id, name, status, image)
     VALUES ($1, 'image-capability-e2e', 'draft', $2)
     RETURNING id::text AS id`,
    [IMAGE_USER, imagePath],
  );
  const agentId = rows[0]?.id;
  if (!agentId) throw new Error('Failed to seed image agent');
  const capability = imageCapability(agentId, imagePath);
  return {
    agentId,
    imagePath,
    url: `/api/images/${agentId}/${capability}`,
  };
}

test.describe('tier-b · agent image capabilities', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test.afterAll(async () => {
    await rm(resolve(IMAGES_DIR, '..'), { recursive: true, force: true });
  });

  test('valid capability serves exact PNG bytes with hardened headers', async () => {
    const api = await playwright.request.newContext({ baseURL: API_URL });
    try {
      const seeded = await seedAgentImage('served.png');
      const res = await api.get(seeded.url);
      expect(res.status()).toBe(200);
      expect(res.headers()['content-type']).toBe('image/png');
      expect(res.headers()['cache-control']).toMatch(/max-age=\d+/);
      expect(res.headers()['x-content-type-options']).toBe('nosniff');
      expect((await res.body()).equals(TINY_PNG)).toBe(true);
    } finally {
      await api.dispose();
    }
  });

  test('raw storage paths are no longer accepted', async () => {
    const api = await playwright.request.newContext({ baseURL: API_URL });
    try {
      const res = await api.get('/api/images/.env');
      expect(res.status()).toBe(404);
    } finally {
      await api.dispose();
    }
  });

  test('forged capability is rejected before storage access', async () => {
    const api = await playwright.request.newContext({ baseURL: API_URL });
    try {
      const seeded = await seedAgentImage('forged.png');
      const res = await api.get(`/api/images/${seeded.agentId}/${'0'.repeat(64)}`);
      expect(res.status()).toBe(404);
    } finally {
      await api.dispose();
    }
  });

  test('even a signed poisoned database path is rejected', async () => {
    const api = await playwright.request.newContext({ baseURL: API_URL });
    try {
      const { rows } = await pg.query<{ id: string }>(
        `INSERT INTO agents (user_id, name, status, image)
         VALUES ($1, 'poisoned-image-e2e', 'draft', '.env')
         RETURNING id::text AS id`,
        [IMAGE_USER],
      );
      const agentId = rows[0]?.id;
      if (!agentId) throw new Error('Failed to seed poisoned image agent');
      const capability = imageCapability(agentId, '.env');
      const res = await api.get(`/api/images/${agentId}/${capability}`);
      expect(res.status()).toBe(404);
    } finally {
      await api.dispose();
    }
  });

  test('jpg uses image/jpeg while non-image extensions fail closed', async () => {
    const api = await playwright.request.newContext({ baseURL: API_URL });
    try {
      const jpg = await seedAgentImage(
        'aliased.jpg',
        Buffer.from([0xff, 0xd8, 0xff, 0xe0]),
      );
      const jpgRes = await api.get(jpg.url);
      expect(jpgRes.status()).toBe(200);
      expect(jpgRes.headers()['content-type']).toBe('image/jpeg');

      const text = await seedAgentImage('not-an-image.txt', Buffer.from('secret'));
      const textRes = await api.get(text.url);
      expect(textRes.status()).toBe(404);
    } finally {
      await api.dispose();
    }
  });
});
