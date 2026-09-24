/**
 * Execution traces — a chat turn's steps are stored and shown in the Logs UI.
 *
 * One `/stream` turn with a tool call writes a `request_traces` row holding
 * the agent run, every LLM call and the tool call. The Logs row links to it
 * through `request_id` (stamped into `user_logs.data`), carries a trace
 * summary, and "View trace" opens the waterfall.
 *
 * // Silent-break covered: the Logs row loses its trace link. If the
 *    request id stops reaching `user_logs` (or the stored trace), the row
 *    silently renders without the "View trace" button and nothing errors.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';
import {
  multipartContext,
  postUpload,
  waitForTask,
} from '../../helpers/uploads.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const README_MD = resolve(HERE, '..', '..', 'fixtures', 'docs', 'readme.md');

/** `memory_view` ships in DEFAULT_CHAT_TOOLS, so every user can run it. */
const TOOL_DIRECTIVE = '[[MOCK_LLM_TOOLCALL:memory_view:once]]';

interface TraceRow {
  source: string;
  status: string;
  request_id: string | null;
  message_id: string | null;
  // pg parses JSONB to JS values
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  spans: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  summary: any;
}

async function tracesFor(userId: string): Promise<TraceRow[]> {
  const { rows } = await pg.query<TraceRow>(
    `SELECT source, status, request_id, message_id::text AS message_id, spans, summary
       FROM request_traces WHERE user_id = $1 ORDER BY started_at`,
    [userId],
  );
  return rows;
}

test.describe('tier-a · execution traces', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('a chat turn with a tool call is traced and opens from the Logs page', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const res = await api.post('/stream', {
        data: {
          question: `what do you remember about me? ${TOOL_DIRECTIVE}`,
          save_conversation: true,
        },
        timeout: 180_000,
      });
      expect(res.ok()).toBeTruthy();
      expect(await res.text()).toContain('"type": "end"');

      // Stored trace: one row for the turn, linked to its message. It is
      // written just after the stream closes, so wait for it.
      await expect.poll(async () => (await tracesFor(sub)).length).toBe(1);
      const traces = await tracesFor(sub);
      const [trace] = traces;
      expect(trace.source).toBe('stream');
      expect(trace.request_id).toBeTruthy();
      expect(trace.message_id).toBeTruthy();
      const kinds = new Set(trace.spans.map((s) => s.kind));
      expect(kinds.has('agent')).toBe(true);
      expect(kinds.has('llm')).toBe(true);
      expect(kinds.has('tool')).toBe(true);
      expect(trace.summary.llm_calls).toBeGreaterThan(0);
      const tool = trace.spans.find((s) => s.kind === 'tool');
      expect(tool.attributes['gen_ai.tool.name']).toBe('memory_view');

      // The Logs API links the row to the trace.
      const logsRes = await api.post('/api/get_user_logs', {
        data: { page: 1, page_size: 10, event_type: 'chat' },
      });
      const logs = (await logsRes.json()).logs;
      expect(logs[0].request_id).toBe(trace.request_id);
      expect(logs[0].trace.ref).toEqual({
        field: 'request_id',
        value: trace.request_id,
      });

      // And the UI opens it.
      const page = await context.newPage();
      await page.goto('/settings/logs');
      await page.getByText('what do you remember about me?').first().click();
      await page.getByRole('button', { name: 'View trace' }).click();
      const sheet = page.getByRole('dialog', { name: 'Execution trace' });
      await expect(sheet).toBeVisible();
      await expect(sheet.getByText('execute_tool memory_view').first()).toBeVisible();
      await sheet.getByText('execute_tool memory_view').first().click();
      await expect(sheet.getByText('Arguments')).toBeVisible();
      if (process.env.TRACE_SCREENSHOT) {
        await page.screenshot({ path: process.env.TRACE_SCREENSHOT, fullPage: false });
      }

      // Closing returns focus to the button that opened the drawer.
      await page.keyboard.press('Escape');
      await expect(sheet).toBeHidden();
      await expect(page.getByRole('button', { name: 'View trace' })).toBeFocused();
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('a RAG turn records the retrieval, its query embedding and each source search', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    const multi = await multipartContext(token);
    try {
      const taskId = await postUpload(multi, README_MD, {
        user: sub,
        name: 'trace-docs',
        mimeType: 'text/markdown',
      });
      expect((await waitForTask(api, taskId, 120_000)).status).toBe('SUCCESS');
      const { rows } = await pg.query<{ id: string }>(
        `SELECT id::text AS id FROM sources WHERE user_id = $1 ORDER BY date DESC LIMIT 1`,
        [sub],
      );
      const sourceId = rows[0].id;

      const res = await api.post('/stream', {
        data: {
          question: 'how do I get started?',
          active_docs: sourceId,
          save_conversation: true,
        },
        timeout: 180_000,
      });
      expect(await res.text()).toContain('"type": "end"');

      await expect.poll(async () => (await tracesFor(sub)).length).toBe(1);
      const [trace] = await tracesFor(sub);
      const byKind = (kind: string) => trace.spans.filter((s) => s.kind === kind);
      const retrieval = byKind('retrieval');
      expect(retrieval.length).toBeGreaterThan(0);
      expect(byKind('embedding').length).toBeGreaterThan(0);
      const searches = byKind('search');
      expect(searches.map((s) => s.attributes['gen_ai.data_source.id'])).toContain(sourceId);
      // Retrieval ran before the agent answered, inside the same trace.
      const agent = byKind('agent')[0];
      expect(retrieval[0].offset_ms).toBeLessThan(agent.offset_ms);
      expect(trace.summary.retrieval_calls).toBeGreaterThan(0);

      const page = await context.newPage();
      await page.goto('/settings/logs');
      await page.getByText('how do I get started?').first().click();
      await page.getByRole('button', { name: 'View trace' }).click();
      const sheet = page.getByRole('dialog', { name: 'Execution trace' });
      await expect(sheet).toBeVisible();
      await sheet.getByText(/^retrieval/).first().click();
      await expect(sheet.getByText('Retrieved chunks')).toBeVisible();
      if (process.env.TRACE_SCREENSHOT_RAG) {
        await page.screenshot({ path: process.env.TRACE_SCREENSHOT_RAG, fullPage: false });
      }
    } finally {
      await multi.dispose();
      await api.dispose();
      await context.close();
    }
  });
});
