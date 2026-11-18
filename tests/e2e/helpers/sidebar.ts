/**
 * Locators for the conversation list in the sidebar.
 *
 * Each conversation is a link to `/c/<id>` (frontend/src/conversation/
 * ConversationTile.tsx); "New Chat" is the `/c/new` link, so it is excluded.
 * The row's "Conversation actions" menu (Share / Rename / Delete) shows while
 * the row is hovered or current, and Rename swaps the link for a text input
 * with Save / Cancel buttons, the Cancel one carrying `id="img-<id>"`.
 */

import type { Locator, Page } from '@playwright/test';

/** Every conversation link in the sidebar, newest first. */
export function conversationLinks(page: Page): Locator {
  return page.locator('a[href^="/c/"]:not([href="/c/new"])');
}

/** The sidebar link for one conversation. */
export function conversationLink(page: Page, conversationId: string): Locator {
  return page.locator(`a[href="/c/${conversationId}"]`);
}

/**
 * The sidebar row for one conversation, in both its link and its rename
 * state (the link is gone while the name is being edited).
 */
export function conversationRow(page: Page, conversationId: string): Locator {
  return page
    .locator('div.group')
    .filter({
      has: page.locator(
        `a[href="/c/${conversationId}"], [id="img-${conversationId}"]`,
      ),
    });
}

/** Hover a conversation's row and pick `item` from its actions menu. */
export async function chooseConversationAction(
  page: Page,
  conversationId: string,
  item: 'Share' | 'Rename' | 'Delete',
): Promise<void> {
  const row = conversationRow(page, conversationId);
  await row.hover();
  await row.getByRole('button', { name: 'Conversation actions' }).click();
  await page.getByRole('menuitem', { name: item, exact: true }).click();
}
