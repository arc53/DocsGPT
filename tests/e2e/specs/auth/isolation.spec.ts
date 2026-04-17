/**
 * Phase 1 — P1-C · cross-user isolation.
 *
 * Covers the Phase 1 acceptance criterion: two freshly-minted users (A and
 * B) must not see each other's writes. User A creates a prompt; user B's
 * `/api/get_prompts` must not include it, and the DB must report zero
 * `prompts` rows for user B.
 *
 * This spec is mode-agnostic — it drives the API directly with signed
 * tokens and doesn't touch the JWT modal — so it runs under both
 * `AUTH_TYPE=session_jwt` and `AUTH_TYPE=simple_jwt` (though simple_jwt
 * would in practice reject distinct subs: the server still accepts any
 * HS256-signed token with the shared secret, per application/auth.py).
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { authedRequest } from '../../helpers/api.js';
import { signJwt } from '../../helpers/auth.js';
import { countRows } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

const USER_A_SUB = 'e2e-isolation-a';
const USER_B_SUB = 'e2e-isolation-b';

type Prompt = { id: string; name: string; type: 'public' | 'private' };

test.describe('auth · cross-user isolation', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test("isolation: user A's prompt is invisible to user B across API and DB", async () => {
    const tokenA = signJwt(USER_A_SUB);
    const tokenB = signJwt(USER_B_SUB);

    const apiA = await authedRequest(playwright, tokenA);
    const apiB = await authedRequest(playwright, tokenB);

    try {
      // User A creates a prompt. Contract per
      // application/api/user/prompts/routes.py:19-50 — POST JSON body with
      // `name` + `content`, returns `{id}` on 200.
      const promptName = 'e2e-isolation-prompt';
      const promptContent = 'Isolation check — only user A should see me.';

      const createRes = await apiA.post('/api/create_prompt', {
        data: { name: promptName, content: promptContent },
      });
      expect(createRes.status()).toBe(200);
      const createBody = (await createRes.json()) as { id: string };
      expect(createBody.id).toBeTruthy();

      // User A can see the prompt in their list.
      const listARes = await apiA.get('/api/get_prompts');
      expect(listARes.status()).toBe(200);
      const listA = (await listARes.json()) as Prompt[];
      const privateAPrompts = listA.filter((p) => p.type === 'private');
      expect(privateAPrompts).toHaveLength(1);
      expect(privateAPrompts[0].name).toBe(promptName);
      expect(privateAPrompts[0].id).toBe(createBody.id);

      // User B cannot see it. The three built-in public prompts
      // (default/creative/strict) are always returned by /get_prompts —
      // the isolation assertion is on the `private` slice.
      const listBRes = await apiB.get('/api/get_prompts');
      expect(listBRes.status()).toBe(200);
      const listB = (await listBRes.json()) as Prompt[];
      const privateBPrompts = listB.filter((p) => p.type === 'private');
      expect(privateBPrompts).toHaveLength(0);
      expect(listB.find((p) => p.id === createBody.id)).toBeUndefined();

      // DB-level assertion — UI/API view can lie (bugs like missing
      // WHERE user_id clauses) but the underlying row count cannot.
      const aRowCount = await countRows('prompts', {
        sql: 'user_id = $1',
        params: [USER_A_SUB],
      });
      expect(aRowCount).toBe(1);

      const bRowCount = await countRows('prompts', {
        sql: 'user_id = $1',
        params: [USER_B_SUB],
      });
      expect(bRowCount).toBe(0);
    } finally {
      await apiA.dispose();
      await apiB.dispose();
    }
  });
});
