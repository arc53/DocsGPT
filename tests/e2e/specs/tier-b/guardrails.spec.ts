/**
 * Tier-B · agent guardrails: config contract, catalog, and builder UI.
 *
 * Guardrails are a *configuration* feature before they are a runtime one: an
 * operator ticks boxes in the agent builder and trusts that what they saw is
 * what the engine will run. Everything between that click and
 * `GuardrailEngine.evaluate` is silent — `GuardrailsConfig.parse` is
 * deliberately lenient on read (`application/guardrails/config.py:141-149`)
 * and falls back to an all-defaults, **disabled** config rather than raising.
 * That is the right call for a hot streaming path, and it is exactly what
 * makes a bad write invisible: a control that failed to persist, or persisted
 * in a shape the parser rejects, does not error at run time — it silently
 * protects nothing, forever, while the builder keeps rendering the checkbox
 * as ticked.
 *
 * // Silent-break covered #1: a guardrail control that round-trips through
 * // /api/create_agent → agents.config → /api/get_agent in a shape the
 * // runtime parser then discards. Asserted against the JSONB column itself,
 * // not just the API echo, because the API echo and the runtime read the
 * // same row through different code paths.
 *
 * // Silent-break covered #2: a malformed control accepted with a 200. Every
 * // rejection case below is a configuration an operator could plausibly
 * // write and reasonably believe was enforcing something —
 * // `redact` on a check that reports no spans, a duplicate control that
 * // shadows the stricter twin, a typo'd key. Each must 400 AND leave no row
 * // behind — and the 400 must not echo the validator's own text back.
 *
 * // Silent-break covered #3: the builder writes state the backend then
 * // normalises away, so a reload shows the operator something different
 * // from what they saved.
 *
 * Runtime behaviour (blocking, redaction over a live SSE stream, the audit
 * journal) lives in `guardrails-runtime.spec.ts`.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { APIRequestContext } from '@playwright/test';

import { multipartAuthedRequest } from '../../helpers/agents.js';
import { authedRequest } from '../../helpers/api.js';
import { newUserContext, signJwt } from '../../helpers/auth.js';
import { countRows, pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

/** Every registry key `application/guardrails/checks/__init__.py` registers. */
const EXPECTED_CHECKS = [
  'denylist',
  'groundedness',
  'injection',
  'pii',
  'policy',
  'secrets',
  'url',
];

const VALID_STAGES = ['input', 'retrieval', 'tool_result', 'output'];

/**
 * Defaults `GuardrailsConfig` fills in for anything the caller omitted
 * (`application/guardrails/config.py`). Asserted by exact deep-equality
 * below rather than `toMatchObject`, because what ends up in the JSONB
 * column IS the contract: a field silently appearing, disappearing, or
 * changing default is a change to every stored agent's behaviour, and it
 * should cost one deliberate edit here to acknowledge it.
 */
const CONFIG_DEFAULTS = {
  enabled: false,
  mode: 'monitor_only',
  fail_open: true,
  timeout_ms: 2000,
  block_message: "Sorry, I can't help with that request.",
  controls: [] as unknown[],
};

/** Read the raw `agents.config` JSONB straight out of Postgres. */
async function dbAgentConfig(
  agentId: string,
): Promise<Record<string, unknown> | null> {
  const { rows } = await pg.query<{ config: Record<string, unknown> | null }>(
    'SELECT config FROM agents WHERE id = CAST($1 AS uuid)',
    [agentId],
  );
  return rows[0]?.config ?? null;
}

/**
 * Create a draft classic agent carrying `config`, via the multipart form
 * path the builder actually uses (`NewAgent.tsx` appends `config` to a
 * FormData). Returns the raw response so rejection tests can assert on it.
 */
function createAgentWithConfig(
  ctx: APIRequestContext,
  name: string,
  config: unknown,
) {
  return ctx.post('/api/create_agent', {
    multipart: {
      name,
      status: 'draft',
      agent_type: 'classic',
      chunks: '2',
      config: JSON.stringify(config),
    },
  });
}

test.describe('tier-b · guardrails config contract', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('config round-trips create → get_agent → agents.config JSONB, and update_agent replaces it wholesale', async () => {
    const sub = `e2e-guardrails-roundtrip-${Date.now()}`;
    const token = signJwt(sub);
    const multipart = await multipartAuthedRequest(token);
    const json = await authedRequest(playwright, token);
    try {
      // A deliberately PARTIAL config: only the fields an operator would
      // actually set. Everything else must come back filled with the
      // Pydantic defaults, and the denylist settings must come back
      // normalised (deduped terms, `match`/`case_sensitive` materialised) —
      // that normalisation is what makes a stored control self-describing.
      const createRes = await createAgentWithConfig(multipart, 'roundtrip', {
        guardrails: {
          enabled: true,
          mode: 'scan_all',
          block_message: 'Not allowed here.',
          controls: [
            {
              check: 'denylist',
              stage: 'input',
              action: 'block',
              settings: { terms: ['alpha', 'beta', 'alpha'] },
            },
            { check: 'secrets', stage: 'output', action: 'redact' },
          ],
        },
      });
      expect(
        createRes.status(),
        `create_agent with guardrails should be 201, got ${createRes.status()} ${await createRes.text()}`,
      ).toBe(201);
      const agentId = ((await createRes.json()) as { id: string }).id;

      const expectedAfterCreate = {
        guardrails: {
          ...CONFIG_DEFAULTS,
          enabled: true,
          mode: 'scan_all',
          block_message: 'Not allowed here.',
          controls: [
            {
              check: 'denylist',
              stage: 'input',
              action: 'block',
              enabled: true,
              settings: {
                terms: ['alpha', 'beta'],
                match: 'word',
                case_sensitive: false,
              },
            },
            {
              check: 'secrets',
              stage: 'output',
              action: 'redact',
              enabled: true,
              settings: {},
            },
          ],
        },
      };

      // The API echo...
      const getRes = await json.get(`/api/get_agent?id=${agentId}`);
      expect(getRes.status()).toBe(200);
      const fetched = (await getRes.json()) as { config: unknown };
      expect(
        fetched.config,
        'GET /api/get_agent must echo the normalized guardrails config',
      ).toEqual(expectedAfterCreate);

      // ...and the column the runtime actually reads. These are different
      // code paths (`_format_agent_output` vs `StreamProcessor`), so both
      // are asserted.
      expect(
        await dbAgentConfig(agentId),
        'agents.config JSONB must hold the normalized guardrails config',
      ).toEqual(expectedAfterCreate);

      // ---- update replaces, it does not merge -------------------------
      // Drop the denylist control entirely, flip the mode down to
      // monitor_only, and tighten fail_open. A merge-instead-of-replace bug
      // would leave the removed control in place — the operator thinks they
      // turned a block off and it is still blocking.
      const updateRes = await json.put(`/api/update_agent/${agentId}`, {
        data: {
          config: {
            guardrails: {
              enabled: true,
              mode: 'monitor_only',
              fail_open: false,
              timeout_ms: 5000,
              controls: [
                { check: 'secrets', stage: 'output', action: 'redact' },
              ],
            },
          },
        },
      });
      expect(
        updateRes.status(),
        `update_agent with guardrails should be 200, got ${updateRes.status()} ${await updateRes.text()}`,
      ).toBe(200);

      const expectedAfterUpdate = {
        guardrails: {
          ...CONFIG_DEFAULTS,
          enabled: true,
          mode: 'monitor_only',
          fail_open: false,
          timeout_ms: 5000,
          // `block_message` was not supplied on update, so it falls back to
          // the Pydantic default rather than the previously-stored value —
          // config is a document, not a patch.
          controls: [
            {
              check: 'secrets',
              stage: 'output',
              action: 'redact',
              enabled: true,
              settings: {},
            },
          ],
        },
      };

      expect(
        await dbAgentConfig(agentId),
        'update_agent must replace agents.config wholesale, not merge into it',
      ).toEqual(expectedAfterUpdate);

      const getAfter = await json.get(`/api/get_agent?id=${agentId}`);
      expect(getAfter.status()).toBe(200);
      expect(
        ((await getAfter.json()) as { config: unknown }).config,
        'get_agent must reflect the updated config',
      ).toEqual(expectedAfterUpdate);
    } finally {
      await multipart.dispose();
      await json.dispose();
    }
  });

  test('an agent created without a config gets an empty JSONB object, not NULL', async () => {
    const sub = `e2e-guardrails-noconfig-${Date.now()}`;
    const token = signJwt(sub);
    const multipart = await multipartAuthedRequest(token);
    const json = await authedRequest(playwright, token);
    try {
      const res = await multipart.post('/api/create_agent', {
        multipart: {
          name: 'no config at all',
          status: 'draft',
          agent_type: 'classic',
          chunks: '2',
        },
      });
      expect(res.status()).toBe(201);
      const agentId = ((await res.json()) as { id: string }).id;

      // `agents.config` is NOT NULL DEFAULT '{}'::jsonb (alembic
      // 0029_agent_guardrails). A NULL here would make every read path do
      // `or {}` gymnastics and would break `AgentConfig.parse`'s isinstance
      // check in a way that is invisible until a control is added.
      expect(
        await dbAgentConfig(agentId),
        'agents.config must default to {} so existing agents parse as guardrails-disabled',
      ).toEqual({});

      const getRes = await json.get(`/api/get_agent?id=${agentId}`);
      expect(getRes.status()).toBe(200);
      expect(((await getRes.json()) as { config: unknown }).config).toEqual({});
    } finally {
      await multipart.dispose();
      await json.dispose();
    }
  });

  test('an empty-string config is treated as "not supplied" and leaves the column at {}', async () => {
    const sub = `e2e-guardrails-emptystr-${Date.now()}`;
    const token = signJwt(sub);
    const multipart = await multipartAuthedRequest(token);
    try {
      // The builder sends `config` on every save. An older client, or a
      // form field that never got populated, sends "". That must not be a
      // 400 — `normalize_agent_config` returns None and the field is
      // dropped (`application/api/user/agents/routes.py:384-385`).
      const res = await multipart.post('/api/create_agent', {
        multipart: {
          name: 'empty string config',
          status: 'draft',
          agent_type: 'classic',
          chunks: '2',
          config: '',
        },
      });
      expect(
        res.status(),
        `empty config string must be accepted, got ${res.status()} ${await res.text()}`,
      ).toBe(201);
      const agentId = ((await res.json()) as { id: string }).id;
      expect(await dbAgentConfig(agentId)).toEqual({});
    } finally {
      await multipart.dispose();
    }
  });
});

test.describe('tier-b · guardrails strict validation on write', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  /**
   * Each case is a config an operator could plausibly write and believe was
   * protecting them. `expectedMessage` is asserted as a substring so the
   * test pins the *diagnosis*, not just the status code — a 400 that says
   * "invalid" teaches nobody which box to untick.
   */
  const REJECTIONS: Array<{
    label: string;
    config: unknown;
    /** Validator text that must appear in the SERVER LOG, never the body. */
    internalHint: string;
  }> = [
    {
      label: 'unknown check name',
      config: {
        guardrails: {
          enabled: true,
          controls: [{ check: 'no_such_check', stage: 'input', action: 'flag' }],
        },
      },
      internalHint: "unknown check 'no_such_check'",
    },
    {
      label: 'redact on a check that reports no spans (groundedness)',
      config: {
        guardrails: {
          enabled: true,
          controls: [
            { check: 'groundedness', stage: 'output', action: 'redact' },
          ],
        },
      },
      internalHint: "check 'groundedness' cannot redact",
    },
    {
      label: 'a check bound to a stage it does not support',
      config: {
        guardrails: {
          enabled: true,
          controls: [
            { check: 'groundedness', stage: 'input', action: 'flag' },
          ],
        },
      },
      internalHint:
        "check 'groundedness' does not support stage 'input'",
    },
    {
      label: 'duplicate control for the same check+stage',
      config: {
        guardrails: {
          enabled: true,
          controls: [
            {
              check: 'denylist',
              stage: 'input',
              action: 'flag',
              settings: { terms: ['a'] },
            },
            {
              check: 'denylist',
              stage: 'input',
              action: 'block',
              settings: { terms: ['b'] },
            },
          ],
        },
      },
      internalHint:
        "duplicate control for check 'denylist' at stage 'input'",
    },
    {
      label: 'denylist with an empty term list',
      config: {
        guardrails: {
          enabled: true,
          controls: [
            {
              check: 'denylist',
              stage: 'input',
              action: 'flag',
              settings: { terms: [] },
            },
          ],
        },
      },
      internalHint: 'terms must be a non-empty list',
    },
    {
      label: 'pii with an entity the detector has no pattern for',
      config: {
        guardrails: {
          enabled: true,
          controls: [
            {
              check: 'pii',
              stage: 'output',
              action: 'redact',
              settings: { entities: ['NOT_A_THING'] },
            },
          ],
        },
      },
      internalHint: 'unknown PII entities: NOT_A_THING',
    },
    {
      label: 'url policy with neither an allow nor a block list',
      config: {
        guardrails: {
          enabled: true,
          controls: [
            { check: 'url', stage: 'output', action: 'redact', settings: {} },
          ],
        },
      },
      internalHint: 'provide allow_hosts or block_hosts',
    },
    {
      label: 'an unknown enforcement mode',
      config: { guardrails: { enabled: true, mode: 'yolo' } },
      internalHint: 'mode must be one of',
    },
    {
      label: 'a timeout below the floor',
      config: { guardrails: { enabled: true, timeout_ms: 5 } },
      internalHint: 'must be >= 100',
    },
    {
      label: 'a typo\'d key at the top level of config',
      config: { guardrails: { enabled: true }, guardrail: {} },
      internalHint: 'Extra inputs are not permitted',
    },
    {
      label: 'a typo\'d key inside a control',
      config: {
        guardrails: {
          enabled: true,
          controls: [
            {
              check: 'secrets',
              stage: 'output',
              action: 'flag',
              setttings: {},
            },
          ],
        },
      },
      internalHint: 'Extra inputs are not permitted',
    },
    {
      label: 'config that is not a JSON object at all',
      config: ['not', 'an', 'object'],
      internalHint: 'config must be a JSON object',
    },
  ];

  for (const { label, config, internalHint } of REJECTIONS) {
    test(`create_agent rejects ${label} with a 400 and writes no row`, async () => {
      const sub = `e2e-guardrails-reject-${Date.now()}-${Math.random()
        .toString(36)
        .slice(2, 8)}`;
      const token = signJwt(sub);
      const ctx = await multipartAuthedRequest(token);
      try {
        const res = await createAgentWithConfig(ctx, `reject ${label}`, config);
        const body = await res.text();
        expect(res.status(), `expected 400 for ${label}, body: ${body}`).toBe(
          400,
        );
        // The body is deliberately static — CodeQL flagged returning
        // validator text, and `api/user/sources/routes.py` set the precedent
        // of a fixed message with the detail logged instead. So assert the
        // stable contract AND that the internals did not escape with it.
        expect(
          body,
          `the 400 for "${label}" must carry the static message; got: ${body}`,
        ).toContain('Invalid config');
        expect(
          body,
          `the 400 for "${label}" must not leak validator internals (${internalHint})`,
        ).not.toContain(internalHint);

        // Nothing may persist. A rejected config that still creates the
        // agent (minus its guardrails) is the worst outcome: the operator
        // sees an agent, assumes the save worked, and it is unguarded.
        expect(
          await countRows('agents', { sql: 'user_id = $1', params: [sub] }),
          `rejected create for "${label}" must not leave an agents row behind`,
        ).toBe(0);
      } finally {
        await ctx.dispose();
      }
    });
  }

  test('a rejected update_agent leaves the previously-stored config untouched', async () => {
    const sub = `e2e-guardrails-badupdate-${Date.now()}`;
    const token = signJwt(sub);
    const multipart = await multipartAuthedRequest(token);
    const json = await authedRequest(playwright, token);
    try {
      const createRes = await createAgentWithConfig(multipart, 'good then bad', {
        guardrails: {
          enabled: true,
          mode: 'scan_all',
          controls: [{ check: 'secrets', stage: 'output', action: 'block' }],
        },
      });
      expect(createRes.status()).toBe(201);
      const agentId = ((await createRes.json()) as { id: string }).id;
      const before = await dbAgentConfig(agentId);
      expect(before).not.toBeNull();

      const badUpdate = await json.put(`/api/update_agent/${agentId}`, {
        data: {
          config: {
            guardrails: {
              enabled: true,
              controls: [
                { check: 'no_such_check', stage: 'input', action: 'flag' },
              ],
            },
          },
        },
      });
      expect(badUpdate.status()).toBe(400);

      // The pre-existing block control must survive a failed save. If the
      // route wrote `{}` before validating, an operator's typo would quietly
      // disarm a working guardrail.
      expect(
        await dbAgentConfig(agentId),
        'a 400 on update must not clobber the stored guardrails config',
      ).toEqual(before);
    } finally {
      await multipart.dispose();
      await json.dispose();
    }
  });
});

test.describe('tier-b · guardrails catalog endpoint', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('GET /api/guardrails/catalog describes every registered check with the metadata the builder renders', async () => {
    const sub = `e2e-guardrails-catalog-${Date.now()}`;
    const token = signJwt(sub);
    const api = await authedRequest(playwright, token);
    try {
      const res = await api.get('/api/guardrails/catalog');
      expect(res.status()).toBe(200);
      const body = (await res.json()) as {
        success: boolean;
        enabled: boolean;
        checks: Array<{
          name: string;
          label: string;
          description: string;
          stages: string[];
          supports_redaction: boolean;
          latency_hint_ms: number;
          remote: boolean;
          available: boolean;
        }>;
        stages: string[];
        modes: string[];
        actions_by_stage: Record<string, string[]>;
        default_block_message: string;
        pii_entities: string[];
        default_pii_entities: string[];
        floor: unknown;
      };

      expect(body.success).toBe(true);
      expect(body.enabled).toBe(true);
      expect(
        body.checks.map((c) => c.name).sort(),
        'every registered check must be advertised — a check missing from the ' +
          'catalog is a check no operator can ever switch on',
      ).toEqual(EXPECTED_CHECKS);

      for (const check of body.checks) {
        expect(
          typeof check.latency_hint_ms,
          `${check.name}.latency_hint_ms must be a number so the builder can ` +
            'price the check before it is enabled',
        ).toBe('number');
        expect(check.latency_hint_ms).toBeGreaterThan(0);
        expect(typeof check.supports_redaction).toBe('boolean');
        expect(typeof check.available).toBe('boolean');
        expect(typeof check.remote).toBe('boolean');
        expect(check.label.length).toBeGreaterThan(0);
        expect(check.description.length).toBeGreaterThan(0);
        expect(
          Array.isArray(check.stages) && check.stages.length > 0,
          `${check.name}.stages must be a non-empty list`,
        ).toBe(true);
        for (const stage of check.stages) {
          expect(
            VALID_STAGES,
            `${check.name} advertises unknown stage ${stage}`,
          ).toContain(stage);
        }
      }

      // The builder filters the action dropdown by `supports_redaction`
      // (GuardrailsSection.tsx:511-515); if the catalog lied, the UI would
      // offer `redact` on a span-less check and the save would 400.
      const byName = Object.fromEntries(body.checks.map((c) => [c.name, c]));
      expect(byName.secrets.supports_redaction).toBe(true);
      expect(byName.pii.supports_redaction).toBe(true);
      expect(byName.denylist.supports_redaction).toBe(true);
      expect(byName.groundedness.supports_redaction).toBe(false);
      expect(byName.injection.supports_redaction).toBe(false);

      // Local pattern checks must not be advertised as remote — a false
      // `remote` flips `StreamingOutputGuard` into sentence-segmented mode
      // and changes when text is released.
      expect(byName.secrets.remote).toBe(false);
      expect(byName.pii.remote).toBe(false);
      // The judge is the only check that leaves the process.
      expect(byName.policy.remote).toBe(true);

      expect(byName.groundedness.stages).toEqual(['output']);

      expect(body.stages).toEqual(VALID_STAGES);
      expect(body.modes).toEqual(['monitor_only', 'scan_all']);

      // Every stage takes the same three actions now that the tool gate is
      // gone; nothing may advertise an action the validator would reject.
      for (const [stage, actions] of Object.entries(body.actions_by_stage)) {
        expect(VALID_STAGES).toContain(stage);
        expect(actions).toEqual(['block', 'flag', 'redact']);
      }

      expect(body.default_block_message).toBe(
        "Sorry, I can't help with that request.",
      );
      expect(body.pii_entities).toEqual([
        'CREDIT_CARD',
        'EMAIL',
        'IBAN',
        'IPV4',
        'PHONE',
        'US_SSN',
      ]);
      expect(body.default_pii_entities.length).toBeGreaterThan(0);
      for (const entity of body.default_pii_entities) {
        expect(
          body.pii_entities,
          `default PII entity ${entity} is not in the advertised entity list`,
        ).toContain(entity);
      }
      // No instance floor is configured in the e2e env, so the builder must
      // be told there is nothing to lock.
      expect(body.floor).toBeNull();
    } finally {
      await api.dispose();
    }
  });

  test('the catalog is not readable without a token', async () => {
    const api = await playwright.request.newContext({
      baseURL: process.env.API_URL ?? 'http://127.0.0.1:7099',
    });
    try {
      const res = await api.get('/api/guardrails/catalog');
      expect(
        res.status(),
        'the guardrail catalog must require authentication',
      ).toBe(401);
    } finally {
      await api.dispose();
    }
  });
});

test.describe('tier-b · guardrails builder UI', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('enabling a check in the agent builder persists it, and a reload rehydrates exactly what was saved', async ({
    browser,
  }) => {
    const { context, token } = await newUserContext(browser);
    const multipart = await multipartAuthedRequest(token);
    try {
      // Seed a DRAFT agent through the API so the builder opens in `draft`
      // mode, where "Save Draft" is available without a source/prompt.
      const createRes = await multipart.post('/api/create_agent', {
        multipart: {
          name: 'ui guardrails agent',
          description: 'built via the UI spec',
          status: 'draft',
          agent_type: 'classic',
          chunks: '2',
        },
      });
      expect(createRes.status()).toBe(201);
      const agentId = ((await createRes.json()) as { id: string }).id;
      expect(await dbAgentConfig(agentId)).toEqual({});

      const page = await context.newPage();
      await page.goto(`/agents/edit/${agentId}`);

      const section = page.getByTestId('guardrails-section');
      await expect(section).toBeVisible();

      // Collapsed by default — the whole point of the section is that it
      // costs nothing to ignore.
      await expect(page.getByTestId('guardrails-enabled')).toBeHidden();
      await page.getByTestId('guardrails-toggle').click();

      const enableSwitch = page.getByTestId('guardrails-enabled');
      await expect(enableSwitch).toBeVisible();
      await expect(enableSwitch).toHaveAttribute('data-state', 'unchecked');
      await enableSwitch.click();
      await expect(enableSwitch).toHaveAttribute('data-state', 'checked');

      // The catalog drives the check list; the cards only exist once
      // /api/guardrails/catalog has resolved.
      const secretsCard = page.getByTestId('guardrail-check-secrets');
      await expect(secretsCard).toBeVisible();

      // Attach `secrets` to the answer stage, then promote it from the
      // default `flag` to `redact`.
      await page.getByTestId('guardrail-stage-secrets-output').click();
      const actionTrigger = page.getByTestId('guardrail-action-secrets-output');
      await expect(actionTrigger).toBeVisible();
      await expect(actionTrigger).toHaveText(/flag only/i);
      await actionTrigger.click();
      await page.getByRole('option', { name: 'Redact' }).click();
      await expect(actionTrigger).toHaveText(/redact/i);

      // Enforce rather than monitor, and set a custom refusal message.
      const modeTrigger = page.getByTestId('guardrails-mode');
      await modeTrigger.click();
      await page.getByRole('option', { name: /enforce everywhere/i }).click();
      await expect(modeTrigger).toHaveText(/enforce everywhere/i);

      const blockMessage = page.getByTestId('guardrails-block-message');
      await blockMessage.fill('Refused by the UI spec.');

      const saveRequest = page.waitForResponse(
        (r) =>
          r.url().includes('/api/update_agent/') &&
          r.request().method() === 'PUT',
        { timeout: 20_000 },
      );
      await page.getByRole('button', { name: /save draft/i }).click();
      const saveRes = await saveRequest;
      expect(
        saveRes.status(),
        `saving the agent from the builder should be 200, got ${saveRes.status()}`,
      ).toBe(200);

      // ---- the row, not the redux store -------------------------------
      const stored = (await dbAgentConfig(agentId)) as {
        guardrails: {
          enabled: boolean;
          mode: string;
          block_message: string;
          controls: Array<{
            check: string;
            stage: string;
            action: string;
            enabled: boolean;
          }>;
        };
      };
      expect(
        stored?.guardrails,
        'the builder must write a guardrails block into agents.config',
      ).toBeTruthy();
      expect(stored.guardrails.enabled).toBe(true);
      expect(stored.guardrails.mode).toBe('scan_all');
      expect(stored.guardrails.block_message).toBe('Refused by the UI spec.');
      expect(stored.guardrails.controls).toHaveLength(1);
      expect(stored.guardrails.controls[0]).toMatchObject({
        check: 'secrets',
        stage: 'output',
        action: 'redact',
        enabled: true,
      });

      // ---- reload rehydrates the same state ---------------------------
      // This is the silent break: the backend normalises on write, so a
      // builder that renders from its own optimistic state would look right
      // until the operator came back tomorrow.
      await page.reload();
      await expect(page.getByTestId('guardrails-section')).toBeVisible();
      await page.getByTestId('guardrails-toggle').click();
      await expect(page.getByTestId('guardrails-enabled')).toHaveAttribute(
        'data-state',
        'checked',
      );
      await expect(page.getByTestId('guardrails-mode')).toHaveText(
        /enforce everywhere/i,
      );
      await expect(page.getByTestId('guardrails-block-message')).toHaveValue(
        'Refused by the UI spec.',
      );
      await expect(
        page.getByTestId('guardrail-action-secrets-output'),
        'the saved action must survive a reload — a control that rehydrates ' +
          'as "flag only" silently downgrades an operator-chosen redaction',
      ).toHaveText(/redact/i);
    } finally {
      await multipart.dispose();
      await context.close();
    }
  });
});
