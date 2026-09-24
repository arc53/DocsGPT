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

    const approve = buttonByText('Approve');
    const deny = buttonByText('Deny');
    expect(approve.dataset.variant).toBe('default');
    expect(approve.dataset.size).toBe('xs');
    expect(approve.dataset.shape).toBe('pill');
    expect(approve.disabled).toBe(false);
    expect(deny.dataset.variant).toBe('outline');
    expect(deny.dataset.size).toBe('xs');

    const details = container.querySelector(
      'button[title="Details"]',
    ) as HTMLButtonElement;
    expect(details.dataset.variant).toBe('ghost-muted');
    expect(details.dataset.size).toBe('icon-xs');

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

    expect(buttonByText('Approve').disabled).toBe(true);
    expect(buttonByText('Deny').dataset.variant).toBe('destructive-outline');
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

    const chips = container.querySelectorAll(
      'button[aria-label="View artifact"]',
    );
    expect(chips.length).toBe(1);
    chips.forEach((chip) => {
      expect((chip as HTMLElement).dataset.variant).toBe('secondary');
      expect((chip as HTMLElement).dataset.shape).toBe('pill');
    });

    const like = container.querySelector(
      'button[aria-label="Remove like"]',
    ) as HTMLButtonElement;
    expect(like.dataset.variant).toBe('ghost-muted');
    expect(like.dataset.size).toBe('icon-sm');
    expect(like.dataset.shape).toBe('pill');
  });

  it('renders the question edit actions as pill buttons', async () => {
    await render(<ConversationBubble type="QUESTION" message="Hello" />);

    const edit = container.querySelector('img[alt="Edit"]')!
      .parentElement as HTMLButtonElement;
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
      'button[aria-label="Toggle"]',
    )!;
    expect(toggle.dataset.variant).toBe('ghost');
    expect(toggle.className).not.toContain('white/20');
    expect(toggle.querySelector('img')).toBeNull();
    expect(toggle.querySelector('svg')).not.toBeNull();
  });
});
