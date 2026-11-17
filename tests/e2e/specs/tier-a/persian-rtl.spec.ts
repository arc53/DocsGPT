import { test, expect } from '@playwright/test';
import { fileURLToPath } from 'node:url';

const bundle = fileURLToPath(new URL('../../../../extensions/react-widget/dist/modern/browser.js', import.meta.url));

for (const width of [320, 390, 768, 1280]) {
  test(`Persian widget stays scoped and supports mixed content at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    let requests = 0;
    await page.route('**/stream', async (route) => {
      requests += 1;
      const events = [
        { type: 'id', id: 'a93066f8-c813-47aa-8463-e3cf947073da' },
        { type: 'answer', answer: 'پاسخ فارسی همراه English\n\n- مورد نخست\n\n| عنوان | شناسه |\n| --- | --- |\n| نمونه | ABC-123 |\n\n```js\nconst price = 123;\n```\n\n[منبع](https://example.com/)' },
        { type: 'end' },
      ];
      await route.fulfill({ contentType: 'text/event-stream', body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('') });
    });
    await page.setContent('<!DOCTYPE html><html lang="en" dir="ltr"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><h1>Host page</h1><div id="widget"></div></body></html>');
    await page.addScriptTag({ path: bundle });
    await page.evaluate(() => {
      const host = window as unknown as { renderDocsGPTWidget: (id: string, props: object) => void };
      host.renderDocsGPTWidget('widget', { locale: 'fa-IR', apiHost: 'https://fixture.invalid', apiKey: '', persistConversations: false, suggestedQuestions: [], showMicButton: false });
    });
    const launcher = page.locator('[data-docsgpt-launcher]');
    await expect(launcher).toHaveText('پرسیدن سؤال');
    expect(requests).toBe(0);
    await launcher.click();
    const panel = page.locator('[data-docsgpt-panel]');
    await expect(panel).toHaveAttribute('lang', 'fa');
    await expect(panel).toHaveAttribute('dir', 'rtl');
    await expect(page.locator('html')).toHaveAttribute('dir', 'ltr');
    const input = panel.locator('textarea');
    await input.fill('سؤال فارسی درباره English');
    await input.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', isComposing: true });
    expect(requests).toBe(0);
    await input.press('Shift+Enter');
    await expect(input).toHaveValue(/\n/);
    expect(requests).toBe(0);
    await input.press('Enter');
    await expect(panel.locator('pre')).toContainText('const price = 123;');
    await expect(panel.locator('pre')).toHaveCSS('direction', 'ltr');
    await expect(panel.getByRole('link', { name: 'منبع' })).toHaveAttribute('href', 'https://example.com/');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await panel.getByRole('button', { name: 'بستن گفتگو', exact: true }).click();
    await expect(launcher).toBeVisible();
  });
}

test('English widget remains LTR on a Persian host page', async ({ page }) => {
  await page.setContent('<!DOCTYPE html><html lang="fa" dir="rtl"><body><div id="widget"></div></body></html>');
  await page.addScriptTag({ path: bundle });
  await page.evaluate(() => {
    const host = window as unknown as { renderDocsGPTWidget: (id: string, props: object) => void };
    host.renderDocsGPTWidget('widget', { locale: 'en', apiKey: '', persistConversations: false, suggestedQuestions: [] });
  });
  const launcher = page.locator('[data-docsgpt-launcher]');
  await expect(launcher).toHaveText('Ask a question');
  await expect(launcher).toHaveAttribute('dir', 'ltr');
  await launcher.click();
  await expect(page.locator('[data-docsgpt-panel]')).toHaveAttribute('dir', 'ltr');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
});
