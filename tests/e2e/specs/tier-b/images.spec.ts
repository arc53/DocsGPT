// Phase 3 Tier-B · B17 image serve endpoint.
/**
 * Exercises `GET /api/images/<path:image_path>` in
 * `application/api/user/attachments/routes.py` — the static-ish endpoint
 * that fronts `storage.get_file()` for user-uploaded agent images and
 * anything else the UI references via `generate_image_url(...)`. The route
 * is not authenticated (no `@token_required` wrapping) by design — the
 * image URLs are shared publicly e.g. in the agents marketplace — so we
 * don't set up a `newUserContext` here, unlike every other Tier-B spec.
 *
 * Storage contract gotcha: `LocalStorage.__init__` sets `base_dir` to the
 * repo root (three `os.path.dirname()` calls up from
 * `application/storage/local.py`). The e2e env sets `UPLOAD_FOLDER=.e2e-tmp/inputs`
 * but that is the directory the upload handlers write INTO; it is not the
 * storage base. So an image request for `/api/images/foo/bar.png` resolves
 * to `<repo_root>/foo/bar.png`. The tests below write their fixture files
 * under `<repo_root>/.e2e-tmp/inputs/e2e-images/<filename>` and request
 * `/api/images/.e2e-tmp/inputs/e2e-images/<filename>` — the `.` prefix is
 * NOT `..` so it passes the route's literal-substring guard.
 *
 * Covered:
 *   1. served file: write a small PNG under storage, GET returns bytes +
 *      correct Content-Type + Cache-Control header.
 *   2. path traversal: `/api/images/../../etc/passwd` — rejected 400 before
 *      hitting storage. Also URL-encoded %2E%2E variant.
 *   3. missing file: GET against a known-absent path → 404.
 *   4. non-image extensions serve with a predictable content-type (the
 *      route trusts the extension and returns `image/<ext>`).
 *   5. jpg alias: extension `.jpg` is served as `image/jpeg` (not `image/jpg`).
 */

import { mkdir, rm, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

const HERE = dirname(fileURLToPath(import.meta.url));
// Repo root = tests/e2e/specs/tier-b/ → up 4 = repo root.
const REPO_ROOT = resolve(HERE, '..', '..', '..', '..');
// Scratch dir we own — writes go here, TRUNCATE doesn't touch the filesystem.
const IMAGES_DIR = resolve(REPO_ROOT, '.e2e-tmp', 'inputs', 'e2e-images');
// Path used in URLs — relative-to-repo-root, matches what `storage.get_file`
// will resolve via its `base_dir` join.
const IMAGES_URL_PREFIX = '.e2e-tmp/inputs/e2e-images';

const API_URL = process.env.API_URL ?? 'http://127.0.0.1:7099';

// Minimal valid PNG — 1x1 transparent pixel. Borrowed from the commonly-
// reproduced public-domain snippet; it's a real PNG that decoders accept.
// Using a real PNG (vs. a fake 8-byte header) means a future test that
// actually tries to render it won't break.
const TINY_PNG_BASE64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';

async function seedImage(
  relName: string,
  data: Buffer = Buffer.from(TINY_PNG_BASE64, 'base64'),
): Promise<string> {
  await mkdir(IMAGES_DIR, { recursive: true });
  const fullPath = resolve(IMAGES_DIR, relName);
  await writeFile(fullPath, data);
  return `${IMAGES_URL_PREFIX}/${relName}`;
}

test.describe('tier-b · images (public image serve)', () => {
  // Filesystem is shared across tests in this file; each test writes under
  // a unique filename to avoid collision. After the suite we clean the dir.
  test.afterAll(async () => {
    await rm(IMAGES_DIR, { recursive: true, force: true });
  });

  test('serves a seeded PNG with correct content-type and cache header', async () => {
    const api = await playwright.request.newContext({ baseURL: API_URL });
    try {
      const imagePath = await seedImage('served.png');
      const res = await api.get(`/api/images/${imagePath}`);
      expect(res.status()).toBe(200);

      const headers = res.headers();
      expect(headers['content-type']).toBe('image/png');

      // The route sets `Cache-Control: max-age=86400`. Spec asserts presence
      // (don't pin the specific value — a future 1h/1d swap shouldn't fail).
      const cacheControl = headers['cache-control'];
      expect(cacheControl, 'Cache-Control header should be present').toBeTruthy();
      expect(cacheControl).toMatch(/max-age=\d+/);

      // Body is the exact bytes we wrote.
      const expected = Buffer.from(TINY_PNG_BASE64, 'base64');
      const body = await res.body();
      expect(body.equals(expected)).toBe(true);
    } finally {
      await api.dispose();
    }
  });

  test('path traversal rejected (literal ..) → 400', async () => {
    // Playwright's APIRequestContext resolves URLs through the WHATWG URL
    // parser which collapses `..` segments before sending. To actually hit
    // Flask with `..` in the path we must URL-encode the dots so Playwright
    // passes them through unmodified — Werkzeug decodes them back to `..`
    // and the route's substring guard then triggers 400.
    const api = await playwright.request.newContext({ baseURL: API_URL });
    try {
      const encoded = await api.get(
        '/api/images/%2e%2e%2f%2e%2e%2fetc%2fpasswd',
      );
      expect(encoded.status()).toBe(400);
      const body = (await encoded.json()) as { success: boolean; message?: string };
      expect(body.success).toBe(false);
      expect(body.message ?? '').toMatch(/invalid/i);

      // Also the mixed-path traversal case where the literal `..` sits
      // inside the trailing path (no leading-slash collapse because of the
      // non-dot first segment). Encoded so Playwright can't normalise it away.
      const encoded2 = await api.get(
        '/api/images/e2e-images/%2e%2e%2fbadfile',
      );
      expect(encoded2.status()).toBe(400);
    } finally {
      await api.dispose();
    }
  });

  test('missing file returns 404', async () => {
    const api = await playwright.request.newContext({ baseURL: API_URL });
    try {
      // Ensure the directory exists (so the error is truly "file not found",
      // not a directory-missing surfaced as FileNotFoundError from a missing
      // intermediate segment).
      await mkdir(IMAGES_DIR, { recursive: true });
      const res = await api.get(
        `/api/images/${IMAGES_URL_PREFIX}/definitely-not-here-${Date.now()}.png`,
      );
      expect(res.status()).toBe(404);
      const body = (await res.json()) as { success: boolean; message?: string };
      expect(body.success).toBe(false);
    } finally {
      await api.dispose();
    }
  });

  test('non-image extension is served with image/<ext> content-type (route trusts the extension)', async () => {
    // The handler does not inspect bytes — it splits the path by `.` and
    // returns `image/<ext>`. This is a deliberate contract (legacy agents
    // may reference `.webp`, `.gif`, etc.) but a weird one: `.txt` would
    // also be served as `image/txt`. Pin that behaviour so a future MIME-
    // sniffer refactor trips this test loudly rather than silently changing
    // what browsers see.
    const api = await playwright.request.newContext({ baseURL: API_URL });
    try {
      const imagePath = await seedImage(
        'not-really.webp',
        Buffer.from('RIFFxxxxWEBP', 'utf8'),
      );
      const res = await api.get(`/api/images/${imagePath}`);
      expect(res.status()).toBe(200);
      expect(res.headers()['content-type']).toBe('image/webp');
    } finally {
      await api.dispose();
    }
  });

  test('jpg extension is aliased to image/jpeg', async () => {
    const api = await playwright.request.newContext({ baseURL: API_URL });
    try {
      const imagePath = await seedImage(
        'aliased.jpg',
        Buffer.from('not-a-real-jpeg-just-bytes', 'utf8'),
      );
      const res = await api.get(`/api/images/${imagePath}`);
      expect(res.status()).toBe(200);
      // The route explicitly branches `jpg -> image/jpeg` — verifying here
      // so a refactor to a generic mime-type map can't quietly regress to
      // `image/jpg` (which Safari rejects).
      expect(res.headers()['content-type']).toBe('image/jpeg');
    } finally {
      await api.dispose();
    }
  });
});
