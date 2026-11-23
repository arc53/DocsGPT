import { act, useContext } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const state = {
  preference: { token: null, selectedAgent: null, agents: [] },
  conversation: { conversationId: null, queries: [], status: 'idle' },
  upload: { attachments: [] },
};
vi.mock('react-redux', () => ({
  useSelector: (selector: (s: typeof state) => unknown) => selector(state),
  useDispatch: () => vi.fn(),
}));
vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({}),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));
vi.mock('../components/MessageInput', () => ({ default: () => null }));
vi.mock('../components/ArtifactPanel', () => ({ default: () => null }));
vi.mock('./ArtifactsPanel', () => ({ default: () => null }));
// The sources panel's header, so its X closes the docked slot.
vi.mock('./SourcesPanel', async () => {
  const { PanelHeader } = await import('../components/ui/side-panel');
  return { default: () => <PanelHeader title="Sources" /> };
});
// The message list opens the sources and reports the layout it is given.
vi.mock('./ConversationMessages', async () => {
  const { ChatCompanionContext } = await import('./chatCompanion');
  return {
    default: ({ isSplitView }: { isSplitView: boolean }) => {
      const companion = useContext(ChatCompanionContext);
      return (
        <button
          type="button"
          data-testid="messages"
          data-split={String(isSplitView)}
          onClick={() => companion?.openSources?.([])}
        />
      );
    },
  };
});

import Conversation from './Conversation';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.useFakeTimers();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
});

const messages = () =>
  container.querySelector<HTMLElement>('[data-testid="messages"]')!;

describe('Conversation docked companion', () => {
  it('keeps the split layout until the panel has shrunk out', async () => {
    await act(async () => root.render(<Conversation />));
    expect(messages().dataset.split).toBe('false');

    await act(async () => messages().click());
    expect(messages().dataset.split).toBe('true');

    await act(async () =>
      container
        .querySelector<HTMLButtonElement>(
          'button[aria-label="sidePanel.close"]',
        )!
        .click(),
    );
    // The columns widen with the panel, not while it is still shrinking.
    expect(messages().dataset.split).toBe('true');
    await act(async () => vi.advanceTimersByTime(300));
    expect(messages().dataset.split).toBe('false');
  });
});
