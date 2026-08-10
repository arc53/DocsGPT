/**
 * tier-b · the guardrail activity panel on /agents/logs/:agentId.
 *
 * Silent break covered: the audit journal existed for a while with no UI and
 * no caller — `userService.getGuardrailEvents` had zero references — so a
 * flagged turn was only discoverable via psql. An owner who cannot see which
 * control fired cannot tune it, and "auditability" is the main thing this
 * feature claims to buy. These specs assert the panel actually renders real
 * rows produced by a real turn, not fixtures.
 *
 * The second thing covered is the four-way totals split. Blocked / redacted /
 * flagged / not-evaluated are different product problems: "we refused",
 * "we masked something", "we noticed", and "the check never ran". Collapsing
 * them into one "violations" number is the mistake most vendors make, and
 * `not_evaluated` in particular is how a silently-broken detector shows up.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { APIRequestContext } from '@playwright/test';

import { multipartAuthedRequest } from '../../helpers/agents.js';
import { authedRequest } from '../../helpers/api.js';
import { newUserContext, signJwt } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import {
  emitDirective,
  publishGuardrailAgent,
} from '../../helpers/guardrails.js';
import { resetDb } from '../../helpers/reset.js';
import { streamFrames } from '../../helpers/streaming.js';

const BANNED = 'zebrafish-protocol';

/** An agent that blocks one term on input and flags emails on output. */
function config() {
  return {
    enabled: true,
    mode: 'scan_all' as const,
    fail_open: true,
    timeout_ms: 2000,
    block_message: 'Blocked by the e2e panel policy.',
    controls: [
      {
        check: 'denylist',
        stage: 'input',
        action: 'block',
        enabled: true,
        settings: { terms: [BANNED], match: 'word', case_sensitive: false },
      },
      {
        check: 'pii',
        stage: 'output',
        action: 'flag',
        enabled: true,
        settings: { entities: ['EMAIL'] },
      },
    ],
  };
}

/** A turn whose question trips the input denylist. */
function runBlockedTurn(api: APIRequestContext, agentId: string) {
  return streamFrames(api, {
    question: `tell me about the ${BANNED} please`,
    agent_id: agentId,
    history: '[]',
    isNoneDoc: true,
  });
}

/** A turn whose answer carries an email, tripping the output pii flag. */
function runFlaggedTurn(api: APIRequestContext, agentId: string) {
  return streamFrames(api, {
    question: `summarise this ${emitDirective(
      'You can reach the team at ada@example.com any time you like.',
    )}`,
    agent_id: agentId,
    history: '[]',
    isNoneDoc: true,
  });
}

test.describe('tier-b · guardrail activity panel', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('a blocked turn and a flagged turn both appear in the panel with the right totals', async ({
    browser,
  }) => {
    const sub = `e2e-gr-panel-${Date.now()}`;
    const token = signJwt(sub);
    const json = await authedRequest(playwright, token);
    const multipart = await multipartAuthedRequest(token);

    try {
      const { id: agentId } = await publishGuardrailAgent(
        json,
        multipart,
        sub,
        'panel agent',
        config(),
      );

      await runBlockedTurn(json, agentId);
      await runFlaggedTurn(json, agentId);

      // The journal is the source of truth the panel reads; assert it first so
      // a UI failure below is unambiguously a UI failure.
      const { rows } = await pg.query<{ action: string; outcome: string }>(
        `SELECT action, outcome FROM guardrail_events
         WHERE agent_id = $1::uuid ORDER BY created_at`,
        [agentId],
      );
      expect(
        rows.length,
        `expected journal rows for two triggering turns, got ${JSON.stringify(rows)}`,
      ).toBeGreaterThanOrEqual(2);

      const { context } = await newUserContext(browser, { sub });
      const page = await context.newPage();
      await page.goto(`/agents/logs/${agentId}`);

      const panel = page.getByTestId('guardrail-events');
      await expect(panel).toBeVisible();

      // Four separate tiles, not one aggregate count.
      await expect(page.getByTestId('guardrail-stat-blocked')).toContainText(
        '1',
      );
      await expect(page.getByTestId('guardrail-stat-flagged')).toContainText(
        '1',
      );
      await expect(
        page.getByTestId('guardrail-stat-not-evaluated'),
      ).toContainText('0');

      // Both decisions listed, and the check that fired is named.
      const table = page.getByTestId('guardrail-events-rows');
      await expect(table.locator('tr')).toHaveCount(rows.length);
      await expect(table).toContainText('denylist');
      await expect(table).toContainText('pii');

      // Per-check breakdown is what tells an operator which control to tune.
      await expect(page.getByTestId('guardrail-by-check')).toBeVisible();

      await context.close();
    } finally {
      await json.dispose();
      await multipart.dispose();
    }
  });

  test('the check filter narrows the table to a single control', async ({
    browser,
  }) => {
    const sub = `e2e-gr-filter-${Date.now()}`;
    const token = signJwt(sub);
    const json = await authedRequest(playwright, token);
    const multipart = await multipartAuthedRequest(token);

    try {
      const { id: agentId } = await publishGuardrailAgent(
        json,
        multipart,
        sub,
        'filter agent',
        config(),
      );
      await runBlockedTurn(json, agentId);
      await runFlaggedTurn(json, agentId);

      const { context } = await newUserContext(browser, { sub });
      const page = await context.newPage();
      await page.goto(`/agents/logs/${agentId}`);

      const table = page.getByTestId('guardrail-events-rows');
      await expect(table).toContainText('denylist');
      await expect(table).toContainText('pii');

      await page.getByTestId('guardrail-events-check-filter').click();
      await page.getByRole('option', { name: 'denylist' }).click();

      await expect(table).toContainText('denylist');
      await expect(table).not.toContainText('pii');

      await context.close();
    } finally {
      await json.dispose();
      await multipart.dispose();
    }
  });

  test('an agent that has never tripped a guardrail shows an explicit empty state', async ({
    browser,
  }) => {
    const sub = `e2e-gr-empty-${Date.now()}`;
    const token = signJwt(sub);
    const json = await authedRequest(playwright, token);
    const multipart = await multipartAuthedRequest(token);

    try {
      const { id: agentId } = await publishGuardrailAgent(
        json,
        multipart,
        sub,
        'quiet agent',
        config(),
      );

      const { context } = await newUserContext(browser, { sub });
      const page = await context.newPage();
      await page.goto(`/agents/logs/${agentId}`);

      await expect(page.getByTestId('guardrail-events-empty')).toBeVisible();
      await expect(page.getByTestId('guardrail-stat-blocked')).toContainText(
        '0',
      );

      await context.close();
    } finally {
      await json.dispose();
      await multipart.dispose();
    }
  });

  test('the panel is scoped to one agent — another agent’s decisions do not appear', async ({
    browser,
  }) => {
    const sub = `e2e-gr-scope-${Date.now()}`;
    const token = signJwt(sub);
    const json = await authedRequest(playwright, token);
    const multipart = await multipartAuthedRequest(token);

    try {
      const noisy = await publishGuardrailAgent(
        json,
        multipart,
        sub,
        'noisy agent',
        config(),
      );
      const quiet = await publishGuardrailAgent(
        json,
        multipart,
        sub,
        'quiet agent',
        config(),
      );
      await runBlockedTurn(json, noisy.id);

      const { context } = await newUserContext(browser, { sub });
      const page = await context.newPage();
      await page.goto(`/agents/logs/${quiet.id}`);

      await expect(page.getByTestId('guardrail-stat-blocked')).toContainText(
        '0',
        {
          timeout: 10_000,
        },
      );
      await expect(page.getByTestId('guardrail-events-empty')).toBeVisible();

      await context.close();
    } finally {
      await json.dispose();
      await multipart.dispose();
    }
  });
});
