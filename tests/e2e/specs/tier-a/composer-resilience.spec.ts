/**
 * Composer resilience: the composer must never silently discard a file
 * or a send.
 *
 * Two silent-failure paths pinned here:
 *
 *   1. Stream POST failure. A failed /stream request must surface a
 *      visible error bubble with a working Retry — never a send that
 *      evaporates. (fetchAnswer.rejected → per-row error → Retry.)
 *
 *   2. Send while an attachment is still uploading/parsing. The composer
 *      "arms" the send (visible "Will send when … " banner), holds the
 *      message, and auto-flushes once the attachment completes — so the
 *      file arrives bound to the turn (`conversation_messages.attachments[]`)
 *      instead of being silently dropped from the payload.
 *
 * UI-driven on purpose: the surface under test IS the composer. The
 * attachments spec avoids the file picker for API-direct upload tests;
 * here `setInputFiles` on the dropzone input is the point.
 */

import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { Page } from '@playwright/test';

import { newUserContext } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES_DIR = resolve(HERE, '..', '..', 'fixtures', 'docs');
const SMALL_FIXTURE_PATH = resolve(FIXTURES_DIR, 'notes.txt');

async function openComposer(page: Page): Promise<void> {
  await page.goto('/');
  await expect(page.locator('#message-input')).toBeVisible();
}

test.describe('tier-a · composer resilience', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('failed /stream surfaces a visible error and Retry re-sends successfully', async ({
    browser,
  }) => {
    const { context, sub } = await newUserContext(browser);
    try {
      const page = await context.newPage();
      await openComposer(page);

      // Force the stream POST to die at the network layer — the shape of
      // an outage the frontend cannot see an HTTP status for.
      await page.route('**/stream', (route) => route.abort('failed'));

      const textarea = page.locator('#message-input');
      await textarea.fill('resilience probe — e2e-composer-retry');
      await textarea.press('Enter');

      // Visible failure, not a silent drop: the error bubble and a
      // usable Retry control.
      await expect(page.getByText('Something went wrong')).toBeVisible({
        timeout: 15_000,
      });
      const retryButton = page.getByRole('button', { name: /retry/i });
      await expect(retryButton).toBeEnabled();

      // Network heals; Retry must complete the SAME turn.
      await page.unroute('**/stream');
      const streamDone = page.waitForResponse(
        (r) => r.url().includes('/stream') && r.request().method() === 'POST',
        { timeout: 45_000 },
      );
      await retryButton.click();
      const streamRes = await streamDone;
      expect(streamRes.status()).toBe(200);

      await expect(page.getByText('Something went wrong')).toBeHidden({
        timeout: 15_000,
      });

      // The turn landed: one message row, prompt AND response populated.
      const { rows } = await pg.query<{
        prompt: string | null;
        response: string | null;
      }>(
        `SELECT cm.prompt, cm.response
           FROM conversation_messages cm
           JOIN conversations c ON c.id = cm.conversation_id
          WHERE c.user_id = $1`,
        [sub],
      );
      expect(rows).toHaveLength(1);
      expect(rows[0].prompt).toBe('resilience probe — e2e-composer-retry');
      expect(rows[0].response).toBeTruthy();
    } finally {
      await context.close();
    }
  });

  test('send while a file is still processing arms, waits, and flushes with the file bound to the turn', async ({
    browser,
  }) => {
    const { context, sub } = await newUserContext(browser);
    try {
      const page = await context.newPage();
      await openComposer(page);

      // Track /stream POSTs so we can prove the send was HELD.
      const streamPosts: string[] = [];
      page.on('request', (req) => {
        if (req.url().includes('/stream') && req.method() === 'POST') {
          streamPosts.push(req.postData() ?? '');
        }
      });

      // Hold the upload response long enough to press Enter while the
      // attachment is still visibly 'uploading'.
      await page.route('**/api/store_attachment', async (route) => {
        await new Promise((r) => setTimeout(r, 2_000));
        await route.continue();
      });

      // The dropzone input is the first file input MessageInput renders
      // (the second is the audio-capture input).
      await page
        .locator('input[type="file"]')
        .first()
        .setInputFiles(SMALL_FIXTURE_PATH);

      const textarea = page.locator('#message-input');
      await textarea.fill('what is in the attached file? e2e-armed-send');
      await textarea.press('Enter');

      // The send is armed, not fired: banner visible, no /stream yet,
      // and the prompt is still in the composer.
      await expect(
        page.getByText(/will send when 1 file finishes processing/i),
      ).toBeVisible({ timeout: 5_000 });
      expect(streamPosts).toHaveLength(0);
      await expect(textarea).toHaveValue(
        'what is in the attached file? e2e-armed-send',
      );

      // Upload completes → Celery parses → attachment.completed lands via
      // SSE → the armed send auto-flushes. notes.txt parses in seconds.
      const streamDone = page.waitForResponse(
        (r) => r.url().includes('/stream') && r.request().method() === 'POST',
        { timeout: 60_000 },
      );
      const streamRes = await streamDone;
      expect(streamRes.status()).toBe(200);

      // The flushed payload carried exactly one attachment id.
      expect(streamPosts).toHaveLength(1);
      const payload = JSON.parse(streamPosts[0]) as {
        attachments?: string[];
      };
      expect(payload.attachments).toHaveLength(1);

      // Banner cleared, composer emptied by the flush.
      await expect(
        page.getByText(/will send when/i),
      ).toBeHidden({ timeout: 15_000 });
      await expect(textarea).toHaveValue('');

      // The invariant that motivated all of this: the file is BOUND to
      // the turn — conversation_messages.attachments[] holds one PG PK
      // that resolves to this user's attachments row.
      const { rows } = await pg.query<{
        prompt: string | null;
        attachment_count: number | string | null;
        resolved: number | string | null;
      }>(
        `SELECT cm.prompt,
                COALESCE(array_length(cm.attachments, 1), 0) AS attachment_count,
                (SELECT count(*) FROM attachments a
                  WHERE a.id = ANY(cm.attachments)) AS resolved
           FROM conversation_messages cm
           JOIN conversations c ON c.id = cm.conversation_id
          WHERE c.user_id = $1`,
        [sub],
      );
      expect(rows).toHaveLength(1);
      expect(rows[0].prompt).toBe(
        'what is in the attached file? e2e-armed-send',
      );
      expect(Number(rows[0].attachment_count)).toBe(1);
      expect(Number(rows[0].resolved)).toBe(1);
    } finally {
      await context.close();
    }
  });
});
