import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({
  useSelector: () => null,
  useDispatch: () => vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('react-router-dom', () => ({
  useParams: () => ({ agentId: 'share-token' }),
}));

vi.mock('../components/MessageInput', () => ({ default: () => null }));
vi.mock('../conversation/ConversationMessages', () => ({
  default: () => <div data-testid="messages" />,
}));
vi.mock('./SharedAgentCard', () => ({ default: () => null }));
vi.mock('../conversation/conversationSlice', () => ({
  addQuery: vi.fn(),
  fetchAnswer: vi.fn(),
  resendQuery: vi.fn(),
  selectQueries: () => [],
  selectStatus: () => 'idle',
}));

const getSharedAgent = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    getSharedAgent: (...args: unknown[]) => getSharedAgent(...args),
  },
}));

import SharedAgent from './SharedAgent';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('SharedAgent', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getSharedAgent.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = () => act(async () => root.render(<SharedAgent />));
  const state = () =>
    container.querySelector<HTMLElement>('[data-slot="empty-state"]');

  it('says the agent is not found on a 404', async () => {
    getSharedAgent.mockResolvedValue({ ok: false, status: 404 });
    await render();
    expect(state()?.dataset.tone).toBe('neutral');
    expect(state()?.textContent).toContain('agents.shared.notFound');
    expect(state()?.querySelector('button')).toBeNull();
  });

  it('shows a failed load as an error with Retry, not "not found"', async () => {
    getSharedAgent.mockRejectedValue(new TypeError('Failed to fetch'));
    await render();
    expect(state()?.dataset.tone).toBe('destructive');
    expect(state()?.textContent).toContain('agents.shared.loadError');
    expect(state()?.textContent).not.toContain('agents.shared.notFound');

    getSharedAgent.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: 'a1', name: 'Vendor Due Diligence' }),
    });
    const retry = Array.from(state()!.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    )!;
    await act(async () => retry.click());
    expect(getSharedAgent).toHaveBeenCalledTimes(2);
    expect(state()).toBeNull();
    expect(container.textContent).toContain('Vendor Due Diligence');
  });

  it('treats a 500 as a failed load too', async () => {
    getSharedAgent.mockResolvedValue({ ok: false, status: 500 });
    await render();
    expect(state()?.dataset.tone).toBe('destructive');
  });
});
