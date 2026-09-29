import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mocks = vi.hoisted(() => ({
  shareAgent: vi.fn(),
  getAgentWebhook: vi.fn(),
  regenerateAgentKey: vi.fn(),
}));

vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) =>
    selector({ preference: { token: null } }),
}));

vi.mock('../api/services/userService', () => ({ default: mocks }));
// Tested on its own; it needs the store and the tool list.
vi.mock('../agents/ApiWriteAllowlist', () => ({ default: () => null }));

vi.mock('./ConfirmationModal', () => ({
  default: ({
    modalState,
    handleSubmit,
  }: {
    modalState: string;
    handleSubmit: () => void;
  }) =>
    modalState === 'ACTIVE' ? (
      <button type="button" data-testid="confirm-key" onClick={handleSubmit} />
    ) : null,
}));

import type { Agent } from '../agents/types';
import AgentDetailsModal from './AgentDetailsModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const respond = (body: unknown, ok = true) =>
  Promise.resolve({ ok, json: () => Promise.resolve(body) });

describe('AgentDetailsModal', () => {
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
    Object.values(mocks).forEach((m) => m.mockReset());
    document.body.innerHTML = '';
  });

  const render = async (agent: Partial<Agent>) => {
    await act(async () => {
      root.render(
        <AgentDetailsModal
          agent={{ id: 'a1', name: 'Bot', ...agent } as Agent}
          mode="edit"
          modalState="ACTIVE"
          setModalState={() => undefined}
        />,
      );
    });
  };

  // The three sections each have a Generate button until they hold a value.
  const generateButtons = () =>
    Array.from(document.querySelectorAll('button')).filter(
      (b) => b.textContent === 'modals.agentDetails.generate',
    );

  it('generates a missing API key through the reset confirmation', async () => {
    mocks.regenerateAgentKey.mockReturnValue(respond({ key: 'new-key' }));
    await render({ status: 'published' });
    const [, apiKey] = generateButtons();
    await act(async () => apiKey.click());
    await act(async () =>
      document
        .querySelector<HTMLButtonElement>('[data-testid="confirm-key"]')!
        .click(),
    );
    expect(mocks.regenerateAgentKey).toHaveBeenCalledWith('a1', null);
    expect(document.body.textContent).toContain('new-key');
  });

  it('asks a draft to publish first instead of offering a key', async () => {
    await render({ status: 'draft' });
    expect(generateButtons()).toHaveLength(2);
    expect(document.body.textContent).toContain(
      'modals.agentDetails.apiKeyAfterPublish',
    );
  });

  it('shows a refused public link in an alert', async () => {
    mocks.shareAgent.mockReturnValue(
      respond({ success: false, message: 'Not allowed' }, false),
    );
    await render({ status: 'published' });
    await act(async () => generateButtons()[0].click());
    const alert = document.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('Not allowed');
    // Destructive Alerts lead with CircleAlert, like every other one.
    expect(alert?.querySelector('svg.lucide-circle-alert')).not.toBeNull();
    expect(alert?.querySelector('svg.lucide-circle-x')).toBeNull();
  });

  it('shows a failed webhook in an alert with a fallback message', async () => {
    mocks.getAgentWebhook.mockReturnValue(respond({}, false));
    await render({ status: 'published' });
    const buttons = generateButtons();
    await act(async () => buttons[buttons.length - 1].click());
    const alert = document.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('modals.agentDetails.actionFailed');
  });
});
