/**
 * Opening a step while the chat follows a streaming answer.
 *
 * Once an answer outgrows the screen the chat follows its end. Opening the
 * Reasoning step above it grew the content, and the follow scrolled straight
 * back to the bottom: the header just clicked jumped away from the pointer.
 * A toggle now stops the follow the way a wheel does, so the header stays
 * where it was clicked while the answer keeps streaming below it.
 *
 * UI-driven on purpose: what's under test is where the rendered header sits,
 * which only a real layout can measure.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { Page } from '@playwright/test';

import { newUserContext } from '../../helpers/auth.js';
import { resetDb } from '../../helpers/reset.js';

const VIEWPORT = '[data-slot="message-scroller-viewport"]';

/**
 * A reply the mock LLM streams slowly: a few lines of reasoning, then a list
 * long enough to outgrow the screen, one short line every 150ms.
 */
function slowPlanDirective(): string {
  const plan = {
    think: Array.from(
      { length: 6 },
      (_, i) => `Reasoning line ${i + 1}: weighing the next part of the answer.`,
    ),
    answer: Array.from({ length: 70 }, (_, i) => `- item ${i + 1}`).join('\n'),
    chunks: 140,
    chunk_ms: 150,
  };
  const encoded = Buffer.from(JSON.stringify(plan)).toString('base64url');
  return `[[MOCK_LLM_PLAN:${encoded}]]`;
}

/** The chat sits at the answer's end, with no pin spacer holding the question. */
async function isFollowing(page: Page): Promise<boolean> {
  return page.evaluate((selector) => {
    const vp = document.querySelector<HTMLElement>(selector);
    if (!vp) return false;
    const spacer = vp.querySelector<HTMLElement>('[data-message-scroller-spacer]');
    const dist = vp.scrollHeight - vp.scrollTop - vp.clientHeight;
    return (
      vp.scrollHeight > vp.clientHeight + 100 &&
      (!spacer || spacer.offsetHeight === 0) &&
      dist < 2
    );
  }, VIEWPORT);
}

async function answerLength(page: Page): Promise<number> {
  return page.evaluate(
    (selector) =>
      document.querySelector(selector)?.querySelectorAll('li').length ?? 0,
    VIEWPORT,
  );
}

test.describe('tier-a · opening a step while following', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('an opened or closed Reasoning header stays put; following resumes at the end', async ({
    browser,
  }) => {
    const { context } = await newUserContext(browser);
    try {
      const page = await context.newPage();
      await page.setViewportSize({ width: 1280, height: 800 });
      await page.goto('/');
      const input = page.locator('#message-input');
      await expect(input).toBeVisible();
      await input.fill(`List some items. ${slowPlanDirective()}`);
      await input.press('Enter');

      const header = page.getByRole('button', { name: /^Reasoning/ });
      await expect(header).toBeVisible({ timeout: 30_000 });
      await expect.poll(() => isFollowing(page), { timeout: 30_000 }).toBe(true);

      const box = await header.boundingBox();
      expect(box, 'the header is on screen to click').not.toBeNull();
      const before = box!.y;
      const linesBefore = await answerLength(page);

      await page.mouse.click(box!.x + 20, box!.y + box!.height / 2);
      await expect(header).toHaveAttribute('aria-expanded', 'true');
      // Long enough for the follow to have run after the body opened and for
      // several more lines to land.
      await page.waitForTimeout(1_500);

      expect(await answerLength(page), 'still streaming').toBeGreaterThan(
        linesBefore,
      );
      const afterOpen = (await header.boundingBox())!.y;
      expect(Math.abs(afterOpen - before)).toBeLessThanOrEqual(2);

      // Closing it leaves it in place too, and the chat stays where the
      // reader left it while lines keep landing below.
      await page.mouse.click(box!.x + 20, afterOpen + box!.height / 2);
      await expect(header).toHaveAttribute('aria-expanded', 'false');
      await page.waitForTimeout(1_000);
      const afterClose = (await header.boundingBox())!.y;
      expect(Math.abs(afterClose - before)).toBeLessThanOrEqual(2);
      expect(await isFollowing(page)).toBe(false);

      // Scrolling back to the end follows the answer again.
      const viewport = (await page.locator(VIEWPORT).boundingBox())!;
      await page.mouse.move(
        viewport.x + viewport.width / 2,
        viewport.y + viewport.height / 2,
      );
      for (let i = 0; i < 10; i++) await page.mouse.wheel(0, 800);
      const linesAtEnd = await answerLength(page);
      await page.waitForTimeout(1_000);
      expect(await answerLength(page), 'still streaming').toBeGreaterThan(
        linesAtEnd,
      );
      expect(await isFollowing(page)).toBe(true);
    } finally {
      await context.close();
    }
  });
});
