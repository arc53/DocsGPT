import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

import en from '../locale/en.json';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) =>
      key
        .split('.')
        .reduce<unknown>(
          (node, part) => (node as Record<string, unknown>)?.[part],
          en,
        ) ?? key,
  }),
}));

import ConversationBubble from './ConversationBubble';
import { ToolCallsType } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// Mirrors the mocked t(): the English copy, or the key while it is unmerged.
const tr = (key: string): string =>
  (key
    .split('.')
    .reduce<unknown>(
      (node, part) => (node as Record<string, unknown>)?.[part],
      en,
    ) as string | undefined) ?? key;

const makeStore = () =>
  configureStore({
    reducer: {
      preference: () => ({
        chunks: '2',
        selectedDocs: [],
        token: null,
        ttsAvailable: false,
      }),
    },
  });

const pendingCall: ToolCallsType = {
  tool_name: 'crm',
  action_name: 'crm_update',
  call_id: 'call-1',
  arguments: { id: 7 },
  status: 'awaiting_approval',
};

describe('ConversationBubble', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (ui: React.ReactElement) => {
    await act(async () => {
      root.render(<Provider store={makeStore()}>{ui}</Provider>);
    });
  };

  const buttonByText = (text: string) =>
    Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === text,
    ) as HTMLButtonElement;

  it('renders the approval bar on Button variants and disables Approve while a deny reason is typed', async () => {
    await render(
      <ConversationBubble
        type="ANSWER"
        toolCalls={[pendingCall]}
        onToolAction={() => {}}
      />,
    );

    const approve = buttonByText(tr('conversation.toolApproval.approve'));
    const deny = buttonByText(tr('conversation.toolApproval.deny'));
    expect(approve.dataset.variant).toBe('default');
    expect(approve.dataset.size).toBe('xs');
    expect(approve.dataset.shape).toBe('pill');
    expect(approve.disabled).toBe(false);
    expect(deny.dataset.variant).toBe('outline');
    expect(deny.dataset.size).toBe('xs');

    const details = container.querySelector(
      `button[aria-label="${tr('conversation.toolApproval.details')}"]`,
    ) as HTMLButtonElement;
    expect(details.dataset.variant).toBe('ghost-muted');
    expect(details.dataset.size).toBe('icon-xs');
    expect(details.hasAttribute('title')).toBe(false);
    expect(details.getAttribute('aria-expanded')).toBe('false');

    await act(async () => deny.click());
    const input = container.querySelector('input') as HTMLInputElement;
    expect(input.dataset.size).toBe('sm');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!;
      setter.call(input, 'wrong record');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });

    expect(buttonByText(tr('conversation.toolApproval.approve')).disabled).toBe(
      true,
    );
    expect(
      buttonByText(tr('conversation.toolApproval.deny')).dataset.variant,
    ).toBe('destructive-outline');
  });

  // L9: the arguments block sits on the muted approval card, so it is a
  // subtle Card (bordered well on the page background) around the recipe.
  it('shows the approval arguments in a subtle Card with the mono recipe', async () => {
    await render(
      <ConversationBubble
        type="ANSWER"
        toolCalls={[pendingCall]}
        onToolAction={() => {}}
      />,
    );
    const details = container.querySelector(
      `button[aria-label="${tr('conversation.toolApproval.details')}"]`,
    ) as HTMLButtonElement;
    await act(async () => details.click());
    const pre = container.querySelector('pre')!;
    expect(pre.textContent).toContain('"id": 7');
    expect(pre.className.split(' ')).toEqual(
      expect.arrayContaining([
        'font-mono',
        'text-xs',
        'whitespace-pre-wrap',
        'wrap-break-word',
      ]),
    );
    const card = pre.parentElement!;
    expect(card.getAttribute('data-slot')).toBe('card');
    expect(card.getAttribute('data-variant')).toBe('subtle');
    expect(card.getAttribute('data-padding')).toBe('sm');
  });

  it('renders artifact chips as secondary pills and feedback as muted icon buttons', async () => {
    await render(
      <ConversationBubble
        type="ANSWER"
        message="Done."
        feedback="LIKE"
        handleFeedback={() => {}}
        onOpenArtifact={() => {}}
        toolCalls={[
          {
            tool_name: 'code_executor',
            action_name: 'code_executor_run',
            call_id: 'call-2',
            arguments: {},
            status: 'completed',
            artifact_id: 'art-1',
          } as ToolCallsType,
        ]}
      />,
    );

    const viewArtifact =
      (en.conversation as Record<string, unknown>).viewArtifact ??
      'conversation.viewArtifact';
    const chips = container.querySelectorAll(
      `button[aria-label="${viewArtifact}"]`,
    );
    expect(chips.length).toBe(1);
    chips.forEach((chip) => {
      expect((chip as HTMLElement).dataset.variant).toBe('secondary');
      expect((chip as HTMLElement).dataset.shape).toBe('pill');
    });

    const like = container.querySelector(
      `button[aria-label="${tr('conversation.feedback.removeLike')}"]`,
    ) as HTMLButtonElement;
    expect(like.dataset.variant).toBe('ghost-muted');
    expect(like.dataset.size).toBe('icon-sm');
    expect(like.dataset.shape).toBe('pill');

    // Every icon button in the row under the answer is a 32px muted pill
    // with a tooltip trigger and no native title.
    const copy = container.querySelector(
      `button[aria-label="${en.conversation.copy}"]`,
    ) as HTMLButtonElement;
    const dislike = container.querySelector(
      `button[aria-label="${tr('conversation.feedback.dislike')}"]`,
    ) as HTMLButtonElement;
    for (const btn of [copy, like, dislike]) {
      expect(btn.dataset.variant).toBe('ghost-muted');
      expect(btn.dataset.size).toBe('icon-sm');
      expect(btn.dataset.shape).toBe('pill');
      expect(btn.hasAttribute('title')).toBe(false);
      expect(btn.dataset.state).toBe('closed');
    }
  });

  it('renders the question edit actions as pill buttons', async () => {
    await render(<ConversationBubble type="QUESTION" message="Hello" />);

    const edit = container.querySelector(
      `button[aria-label="${tr('conversation.edit.label')}"]`,
    ) as HTMLButtonElement;
    expect(edit.dataset.size).toBe('icon-xs');
    expect(edit.dataset.shape).toBe('pill');
    await act(async () => edit.click());

    const cancel = buttonByText(en.conversation.edit.cancel);
    const update = buttonByText(en.conversation.edit.update);
    expect(cancel.dataset.variant).toBe('ghost');
    expect(cancel.dataset.shape).toBe('pill');
    expect(update.dataset.variant).toBe('default');
    expect(update.dataset.shape).toBe('pill');
    expect(update.disabled).toBe(true);
  });

  it('renders the question on the secondary tint with a foreground chevron', async () => {
    const scrollHeight = vi
      .spyOn(HTMLElement.prototype, 'scrollHeight', 'get')
      .mockReturnValue(200);
    await render(<ConversationBubble type="QUESTION" message="Hello" />);
    scrollHeight.mockRestore();

    const bubble = Array.from(
      container.querySelectorAll<HTMLElement>('div'),
    ).find((el) => el.className.includes('rounded-3xl'))!;
    expect(bubble.className).toContain('bg-secondary');
    expect(bubble.className).toContain('text-foreground');
    expect(bubble.className).not.toMatch(/bg-primary|text-primary-foreground/);

    const toggle = bubble.querySelector<HTMLButtonElement>(
      `button[aria-label="${tr('conversation.question.expand')}"]`,
    )!;
    expect(toggle.dataset.variant).toBe('ghost');
    expect(toggle.className).not.toContain('white/20');
    expect(toggle.querySelector('img')).toBeNull();
    expect(toggle.querySelector('svg')).not.toBeNull();
  });
  describe('source cards', () => {
    const sources = [
      { title: 'Guide', text: 'Guide text', link: 'https://example.com/guide' },
      { title: 'Notes', text: 'Notes text', link: 'local' },
    ];
    const sheet = () => document.body.querySelector('[role="dialog"]');
    const cards = () =>
      Array.from(
        container.querySelectorAll<HTMLElement>('[id^="source-"] > div'),
      );
    const cardButton = (i: number) =>
      cards()[i].querySelector<HTMLButtonElement>(':scope > button')!;

    it('opens the sources sheet when a card is clicked', async () => {
      await render(
        <ConversationBubble type="ANSWER" message="Hi" sources={sources} />,
      );
      expect(sheet()).toBeNull();
      await act(async () => cardButton(1).click());
      expect(sheet()).not.toBeNull();
    });

    it('is a native stretched button with the focus ring on the card', async () => {
      await render(
        <ConversationBubble type="ANSWER" message="Hi" sources={sources} />,
      );
      const card = cards()[0];
      expect(card.getAttribute('role')).toBeNull();
      expect(card.hasAttribute('tabindex')).toBe(false);
      expect(card.className).toContain('relative');
      expect(card.className).toContain('has-[>button:focus-visible]:ring-3');
      const button = cardButton(0);
      expect(button.type).toBe('button');
      expect(button.className).toContain('outline-none');
      expect(button.className).toContain('after:absolute');
      expect(button.className).toContain('after:inset-0');
      // A button takes phrasing content only.
      expect(button.querySelector('p, div')).toBeNull();
      expect(button.textContent).toBe('Guide text');
    });

    it('keeps the link outside the button and in tab order after it', async () => {
      await render(
        <ConversationBubble type="ANSWER" message="Hi" sources={sources} />,
      );
      const card = cards()[0];
      expect(cardButton(0).querySelector('a')).toBeNull();
      const link = card.querySelector<HTMLAnchorElement>(':scope > a')!;
      expect(link).not.toBeNull();
      expect(link.className).toContain('relative');
      expect(link.className).toContain('z-10');
      const stops = Array.from(
        container.querySelectorAll<HTMLElement>(
          '[id^="source-"] button, [id^="source-"] a',
        ),
      );
      expect(stops).toEqual([cardButton(0), link, cardButton(1)]);
    });

    it('shows no hover preview', async () => {
      await render(
        <ConversationBubble type="ANSWER" message="Hi" sources={sources} />,
      );
      await act(async () => {
        cards()[0].dispatchEvent(
          new MouseEvent('mouseover', { bubbles: true }),
        );
      });
      expect(container.querySelector('.bg-popover')).toBeNull();
      expect(container.textContent?.match(/Guide text/g)?.length).toBe(1);
    });

    it('follows the link without opening the sheet', async () => {
      await render(
        <ConversationBubble type="ANSWER" message="Hi" sources={sources} />,
      );
      const link = cards()[0].querySelector('a')!;
      link.addEventListener('click', (e) => e.preventDefault());
      await act(async () => link.click());
      expect(sheet()).toBeNull();
    });

    it('renders "more sources" as a focus-ringed button that opens the sheet', async () => {
      const many = [1, 2, 3, 4, 5].map((n) => ({
        title: `S${n}`,
        text: `Text ${n}`,
        link: 'local',
      }));
      await render(
        <ConversationBubble type="ANSWER" message="Hi" sources={many} />,
      );
      const more = Array.from(
        container.querySelectorAll<HTMLButtonElement>('button'),
      ).find((b) => b.className.includes('flex-col-reverse'))!;
      expect(more).toBeDefined();
      expect(more.type).toBe('button');
      expect(more.getAttribute('role')).toBeNull();
      expect(more.className).toContain('outline-none');
      expect(more.className).toContain('focus-visible:ring-3');
      expect(more.className).toContain('text-left');
      await act(async () => more.click());
      expect(sheet()).not.toBeNull();
    });
  });
});
